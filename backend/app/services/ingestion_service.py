import csv
import json
import logging
import math
import os
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

import pandas as pd
import psycopg

from app.analytics.entity_resolution import (
    STATUS_AUTO_MERGED,
    STATUS_NEW_PERSON,
    STATUS_NEEDS_REVIEW,
    resolve_names_batch,
)
from app.config import settings
from app.db.neo4j import get_driver

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
BATCH_SIZE = 1000
ENTITY_REVIEW_THRESHOLD = 55
ENTITY_AUTO_MERGE_THRESHOLD = 80
MAX_ENTITY_RESOLUTION_DETAILS = 100

CSV_SPECS = {
    "persons.csv": ("persons", ["person_id", "source_domain", "source_entity_id", "display_name", "department", "job_title", "identity_bridge_type"], ["person_id"]),
    "communications.csv": ("communications", ["communication_id", "source_person_id", "target_person_id", "communication_type", "source_dataset"], ["communication_id"]),
    "vehicles.csv": ("vehicles", ["vehicle_id", "car_id", "department", "owner_job_title", "source_dataset"], ["vehicle_id"]),
    "vehicle_assignments.csv": ("vehicle_assignments", ["vehicle_id", "person_id", "relationship", "source_dataset"], ["vehicle_id", "person_id", "relationship"]),
    "locations.csv": ("locations", ["location_id", "latitude", "longitude", "source_dataset"], ["location_id"]),
    "location_events.csv": ("location_events", ["event_id", "person_id", "vehicle_id", "location_id", "timestamp", "event_type", "source_dataset"], ["event_id"]),
    "transactions.csv": ("transactions", ["transaction_id", "event_time", "merchant_location", "amount", "card_last4", "transaction_type", "source_dataset"], ["transaction_id"]),
    "loyalty_events.csv": ("loyalty_events", ["loyalty_event_id", "event_time", "merchant_location", "amount", "loyalty_number", "source_dataset"], ["loyalty_event_id"]),
    "identity_resolution.csv": ("identity_resolution", ["record_id", "canonical_person_id", "canonical_name", "observed_name", "match_label", "provenance"], ["record_id"]),
}
REQUIRED_FILES = {"persons.csv"}
COMMUNICATION_FILES = {"communications.csv", "cdr_records.csv"}
CDR_REQUIRED_COLUMNS = ["caller_person_id", "receiver_person_id"]
LOAD_ORDER = [
    "persons.csv", "vehicles.csv", "locations.csv", "vehicle_assignments.csv",
    "identity_resolution.csv", "communications.csv", "location_events.csv",
    "transactions.csv", "loyalty_events.csv",
]
RELATIONSHIP_TYPES = {"COMMUNICATES_WITH", "VISITED", "ASSIGNED_TO"}


def validate_dataset_directory(root: Path) -> dict:
    files = sorted(path.name for path in root.glob("*.csv"))
    missing = sorted(name for name in REQUIRED_FILES if not (root / name).is_file())
    if not any((root / name).is_file() for name in COMMUNICATION_FILES):
        missing.append("communications.csv or cdr_records.csv")
    invalid_columns = {}
    for name, (_, required, _) in CSV_SPECS.items():
        path = root / name
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        absent = [column for column in required if column not in header]
        if absent:
            invalid_columns[name] = {"missing": absent, "headers": header}
    cdr_path = root / "cdr_records.csv"
    if cdr_path.is_file():
        with cdr_path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
        absent = [column for column in CDR_REQUIRED_COLUMNS if column not in header]
        if absent:
            invalid_columns["cdr_records.csv"] = {"missing": absent, "headers": header}

    location_stats = _location_stats(root / "locations.csv")

    return {
        "files": files,
        "missing_files": missing,
        "invalid_columns": invalid_columns,
        "valid": not missing and not invalid_columns,
        "optional_missing": sorted(
            name for name in CSV_SPECS
            if name not in REQUIRED_FILES and not (root / name).is_file()
        ),
        "malformed_graph_edges_skipped": 0,
        "locations": location_stats,
    }


def ingest_archive(archive_path: Path, dry_run: bool = False) -> dict:
    started = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="sih-ingestion-") as temporary:
        root = Path(temporary) / "dataset"
        root.mkdir()
        _safe_extract(archive_path, root)
        logger.info("Ingestion ZIP extraction complete: root=%s", root)
        validation = validate_dataset_directory(root)
        logger.info(
            "Ingestion validation complete: valid=%s files=%d malformed_graph_edges_skipped=%d",
            validation["valid"],
            len(validation["files"]),
            validation["malformed_graph_edges_skipped"],
        )
        if not validation["valid"]:
            return {"status": "validation_failed", "validation": validation}
        if dry_run:
            return {"status": "validated", "validation": validation}

        metadata = _read_metadata(root)
        counts = _load_supabase(root, metadata, archive_path.name)
        try:
            logger.info("Ingestion Neo4j graph update started")
            neo4j_counts = _update_neo4j(root, counts.get("entity_resolution", {}).get("id_mapping", {}))
            logger.info("Ingestion Neo4j graph update completed: %s", neo4j_counts)
        except Exception:
            logger.exception("Neo4j graph update failed after Supabase load")
            _mark_latest_run_failed()
            raise

        logger.info("Ingestion run completed: status=completed duration_seconds=%.3f", (datetime.now(timezone.utc) - started).total_seconds())
    return {
        "status": "completed",
        "files": validation["files"],
        "rows_processed": {
            key: value for key, value in counts.items()
            if key not in {"locations_metadata", "entity_resolution"}
        },
        "rows_inserted_or_upserted": {
            key: value for key, value in counts.items()
            if key not in {"locations_metadata", "entity_resolution"}
        },
        "rows_skipped": {
            "malformed_graph_edges_skipped": neo4j_counts["malformed_graph_edges_skipped"],
            "locations_rejected_groups": counts["locations_metadata"]["rejected_groups"],
        },
        "locations": counts["locations_metadata"],
        "entity_resolution": {
            key: value for key, value in counts["entity_resolution"].items()
            if key != "id_mapping"
        },
        "neo4j": neo4j_counts,
        "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 3),
    }


def list_ingestion_runs(limit: int = 20) -> list[dict]:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ingestion_run_id, case_id, source_file, source_dataset,
                       status, row_count, started_at, completed_at
                FROM public.ingestion_runs
                ORDER BY started_at DESC NULLS LAST, ingestion_run_id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [_run_row(row) for row in cursor.fetchall()]


def get_ingestion_run(ingestion_run_id: UUID) -> dict | None:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT ingestion_run_id, case_id, source_file, source_dataset,
                       status, row_count, started_at, completed_at
                FROM public.ingestion_runs
                WHERE ingestion_run_id = %s
                """,
                (ingestion_run_id,),
            )
            row = cursor.fetchone()
    return _run_row(row) if row else None


def _safe_extract(archive_path: Path, destination: Path) -> None:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError("The uploaded file is not a valid ZIP archive.")
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if os.path.commonpath((str(destination.resolve()), str(target))) != str(destination.resolve()):
                raise ValueError("The ZIP archive contains an unsafe path.")
        archive.extractall(destination)


def _read_metadata(root: Path) -> dict:
    path = root / "DATASET_METADATA.json"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_supabase(root: Path, metadata: dict, source_file: str) -> dict[str, Any]:
    source_dataset = metadata.get("dataset", "SIH26189 dataset")
    counts: Counter[str] = Counter()
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.transaction():
            logger.info("Ingestion Supabase transaction started")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.ingestion_runs
                        (source_file, source_dataset, status, row_count, started_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING ingestion_run_id
                    """,
                    (source_file, source_dataset, "running", 0, datetime.now(timezone.utc)),
                )
                ingestion_run_id = cursor.fetchone()[0]
                person_mapping, entity_resolution = _upsert_persons(
                    cursor,
                    root / "persons.csv",
                    root / "cdr_records.csv",
                )
                counts["persons"] = entity_resolution["processed"]
                for filename in LOAD_ORDER:
                    path = root / filename
                    if filename == "persons.csv" or not path.is_file():
                        continue
                    table, columns, keys = CSV_SPECS[filename]
                    logger.info("Ingestion dataset batch phase started: %s", table)
                    if filename == "locations.csv":
                        count, location_metadata = _upsert_locations(cursor, path)
                        counts["locations_metadata"] = location_metadata
                    elif filename == "location_events.csv":
                        count = _bulk_upsert_location_events(cursor, path, person_mapping)
                    else:
                        count = _upsert_csv(
                            cursor,
                            path,
                            table,
                            columns,
                            keys,
                            progress_interval=25_000 if filename == "location_events.csv" else None,
                            person_mapping=person_mapping,
                        )
                    counts[table] = count
                    logger.info("Ingestion dataset batch phase completed: %s rows=%d", table, count)
                _insert_generated_resolution_records(cursor, entity_resolution["audit_records"])
                counts.setdefault("locations_metadata", _empty_location_metadata())
                cursor.execute(
                    """
                    UPDATE public.ingestion_runs
                    SET status = %s, row_count = %s, completed_at = %s
                    WHERE ingestion_run_id = %s
                    """,
                    (
                        "completed",
                        sum(value for key, value in counts.items() if key not in {"locations_metadata", "entity_resolution"}),
                        datetime.now(timezone.utc),
                        ingestion_run_id,
                    ),
                )
                logger.info("Ingestion Supabase transaction committed: %s", counts)
    counts["entity_resolution"] = {
        key: value for key, value in entity_resolution.items()
        if key not in {"processed", "audit_records"}
    }
    counts["entity_resolution"]["id_mapping"] = person_mapping
    return dict(counts)


def _upsert_persons(cursor, path: Path, cdr_path: Path | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    cursor.execute("SELECT person_id, display_name FROM public.persons")
    existing = {str(person_id): (display_name or "") for person_id, display_name in cursor.fetchall()}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        incoming_rows = list(csv.DictReader(handle))
    names_to_resolve = list(dict.fromkeys(
        (row.get("display_name") or "").strip()
        for row in incoming_rows
        if (row.get("person_id") or "").strip() not in existing
    ))
    roster = pd.DataFrame(
        [{"person_id": person_id, "display_name": display_name} for person_id, display_name in existing.items()]
    )
    cdr_df, phones = _read_entity_resolution_phone_data(cdr_path, incoming_rows)
    batch_resolutions = resolve_names_batch(names_to_resolve, roster, phones=phones, cdr_df=cdr_df)
    resolutions_by_name = {
        row["raw_name"]: row for row in batch_resolutions.to_dict("records")
    }

    mapping: dict[str, str] = {}
    details: list[dict[str, Any]] = []
    audit_records: list[dict[str, str]] = []
    stats = {"checked": 0, "auto_merged": 0, "review_required": 0, "kept_separate": 0, "processed": 0}
    normal_statement = _person_upsert_statement()
    merge_statement = _person_upsert_statement(preserve_existing=True)
    normal_batch = []
    merge_batch = []

    new_person_ids_by_temp_id: dict[str, str] = {}
    for raw in incoming_rows:
        incoming_id = (raw.get("person_id") or "").strip()
        raw_name = (raw.get("display_name") or "").strip()
        resolution = resolutions_by_name.get(raw_name)
        if incoming_id not in existing and resolution is not None:
            stats["checked"] += 1
            status = resolution["status"]
            if status == STATUS_AUTO_MERGED:
                mapping[incoming_id] = str(resolution["matched_person_id"])
                stats["auto_merged"] += 1
            elif status == STATUS_NEEDS_REVIEW:
                stats["review_required"] += 1
            elif status == STATUS_NEW_PERSON:
                stats["kept_separate"] += 1
                temp_id = resolution.get("new_person_temp_id")
                if temp_id:
                    canonical_new_id = new_person_ids_by_temp_id.setdefault(temp_id, incoming_id)
                    if canonical_new_id != incoming_id:
                        mapping[incoming_id] = canonical_new_id

            score = float(resolution["score"])
            if score >= ENTITY_REVIEW_THRESHOLD and len(details) < MAX_ENTITY_RESOLUTION_DETAILS:
                details.append({
                    "incoming_person_id": incoming_id,
                    "candidate_id": resolution["matched_person_id"],
                    "candidate_name": resolution["matched_display_name"],
                    "score": score,
                    "status": status,
                    "auto_merged": incoming_id in mapping and status == STATUS_AUTO_MERGED,
                })
            if status == STATUS_AUTO_MERGED and incoming_id in mapping:
                canonical_id = mapping[incoming_id]
                audit_records.append({
                    "record_id": f"INGESTION-{incoming_id}-{canonical_id}",
                    "canonical_person_id": canonical_id,
                    "canonical_name": existing[canonical_id],
                    "observed_name": raw_name,
                    "match_label": "1",
                    "provenance": f"ingestion_entity_resolution; similarity_score={score:.2f}; incoming_person_id={incoming_id}",
                })
        target_id = mapping.get(incoming_id, incoming_id)
        values = tuple(
            _convert_value("persons", column, target_id if column == "person_id" else raw.get(column))
            for column in CSV_SPECS["persons.csv"][1]
        )
        (merge_batch if incoming_id in mapping else normal_batch).append(values)
        stats["processed"] += 1
        if len(normal_batch) >= BATCH_SIZE:
            cursor.executemany(normal_statement, normal_batch)
            normal_batch.clear()
        if len(merge_batch) >= BATCH_SIZE:
            cursor.executemany(merge_statement, merge_batch)
            merge_batch.clear()
    if normal_batch:
        cursor.executemany(normal_statement, normal_batch)
    if merge_batch:
        cursor.executemany(merge_statement, merge_batch)
    return mapping, {**stats, "matches": details, "audit_records": audit_records}


def _read_entity_resolution_phone_data(
    cdr_path: Path | None,
    incoming_rows: list[dict[str, str]],
) -> tuple[pd.DataFrame | None, dict[str, str]]:
    if cdr_path is None or not cdr_path.is_file():
        return None, {}
    cdr_df = pd.read_csv(cdr_path)
    person_names = {
        (row.get("person_id") or "").strip(): (row.get("display_name") or "").strip()
        for row in incoming_rows
        if (row.get("person_id") or "").strip() and (row.get("display_name") or "").strip()
    }
    phones: dict[str, str] = {}
    for person_column, phone_column in (
        ("caller_person_id", "caller_phone"),
        ("receiver_person_id", "receiver_phone"),
    ):
        if person_column not in cdr_df or phone_column not in cdr_df:
            continue
        for person_id, phone in zip(cdr_df[person_column], cdr_df[phone_column]):
            if pd.notna(person_id) and pd.notna(phone):
                name = person_names.get(str(person_id).strip())
                if name and str(phone).strip():
                    phones[name] = str(phone).strip()
    for name_column, phone_column in (("caller_name", "caller_phone"), ("receiver_name", "receiver_phone")):
        if name_column not in cdr_df or phone_column not in cdr_df:
            continue
        for name, phone in zip(cdr_df[name_column], cdr_df[phone_column]):
            if pd.notna(name) and pd.notna(phone) and str(name).strip() and str(phone).strip():
                phones[str(name).strip()] = str(phone).strip()
    return cdr_df, phones


def _person_upsert_statement(preserve_existing: bool = False) -> str:
    columns = CSV_SPECS["persons.csv"][1]
    assignments = ", ".join(
        f"{column} = COALESCE(public.persons.{column}, EXCLUDED.{column})" if preserve_existing
        else f"{column} = EXCLUDED.{column}"
        for column in columns if column != "person_id"
    )
    return f"INSERT INTO public.persons ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT (person_id) DO UPDATE SET {assignments}"


def _insert_generated_resolution_records(cursor, records: list[dict[str, str]]) -> None:
    if records:
        cursor.executemany(
            "INSERT INTO public.identity_resolution (record_id, canonical_person_id, canonical_name, observed_name, match_label, provenance) VALUES (%(record_id)s, %(canonical_person_id)s, %(canonical_name)s, %(observed_name)s, %(match_label)s, %(provenance)s) ON CONFLICT (record_id) DO NOTHING",
            records,
        )


def _upsert_csv(
    cursor,
    path: Path,
    table: str,
    columns: list[str],
    keys: list[str],
    progress_interval: int | None = None,
    person_mapping: dict[str, str] | None = None,
) -> int:
    placeholders = ", ".join(["%s"] * len(columns))
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in keys)
    conflict = ", ".join(keys)
    statement = f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO UPDATE SET {assignments}" if assignments else f"INSERT INTO public.{table} ({', '.join(columns)}) VALUES ({placeholders}) ON CONFLICT ({conflict}) DO NOTHING"
    processed = 0
    batch = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            _map_person_references(table, raw, person_mapping)
            batch.append(tuple(_convert_value(table, column, raw.get(column)) for column in columns))
            if len(batch) >= BATCH_SIZE:
                cursor.executemany(statement, batch)
                processed += len(batch)
                batch.clear()
                if progress_interval and processed % progress_interval == 0:
                    logger.info("Ingestion batch progress: table=%s rows=%d", table, processed)
        if batch:
            cursor.executemany(statement, batch)
            processed += len(batch)
            if progress_interval:
                logger.info("Ingestion batch progress: table=%s rows=%d", table, processed)
    return processed


def _upsert_locations(cursor, path: Path) -> tuple[int, dict[str, int]]:
    logger.info("Ingestion locations canonicalization started")
    locations, metadata = _canonical_locations(path)
    statement = """
        INSERT INTO public.locations
            (location_id, latitude, longitude, source_dataset)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (location_id) DO UPDATE SET
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            source_dataset = EXCLUDED.source_dataset
    """
    for start in range(0, len(locations), BATCH_SIZE):
        cursor.executemany(statement, locations[start:start + BATCH_SIZE])
    logger.info("Ingestion locations canonicalization completed: %s", metadata)
    return len(locations), metadata


def _bulk_upsert_location_events(cursor, path: Path, person_mapping: dict[str, str] | None = None) -> int:
    columns = CSV_SPECS["location_events.csv"][1]
    column_list = ", ".join(columns)
    started = perf_counter()
    logger.info("Ingestion location_events bulk load started")
    cursor.execute(
        """
        CREATE TEMPORARY TABLE _location_events_stage
        (LIKE public.location_events INCLUDING DEFAULTS)
        ON COMMIT DROP
        """
    )

    processed = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        with cursor.copy(
            f"COPY _location_events_stage ({column_list}) FROM STDIN"
        ) as copy:
            for raw in reader:
                _map_person_references("location_events", raw, person_mapping)
                copy.write_row(tuple(raw.get(column) or None for column in columns))
                processed += 1
                if processed % 25_000 == 0:
                    logger.info("Ingestion batch progress: table=location_events rows=%d", processed)

    logger.info(
        "Ingestion location_events COPY/staging load complete: rows=%d duration_seconds=%.3f",
        processed,
        perf_counter() - started,
    )
    assignments = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in columns if column != "event_id"
    )
    cursor.execute(
        f"""
        INSERT INTO public.location_events ({column_list})
        SELECT {column_list}
        FROM _location_events_stage
        ON CONFLICT (event_id) DO UPDATE SET {assignments}
        """
    )
    logger.info(
        "Ingestion location_events final upsert complete: rows=%d duration_seconds=%.3f",
        processed,
        perf_counter() - started,
    )
    return processed


def _map_person_references(table: str, row: dict[str, str], person_mapping: dict[str, str] | None) -> None:
    if not person_mapping:
        return
    reference_columns = {
        "communications": ("source_person_id", "target_person_id"),
        "vehicle_assignments": ("person_id",),
        "location_events": ("person_id",),
    }.get(table, ())
    for column in reference_columns:
        value = row.get(column)
        if value in person_mapping:
            row[column] = person_mapping[value]


def _location_stats(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {
            "source_rows": 0,
            "unique_location_ids": 0,
            "canonical_rows": 0,
            "coordinate_conflict_groups": 0,
            "invalid_coordinate_rows": 0,
            "rejected_groups": 0,
        }
    _, metadata = _canonical_locations(path)
    return metadata


def _canonical_locations(path: Path) -> tuple[list[tuple], dict[str, int]]:
    aggregates: dict[str, dict[str, Any]] = {}
    source_rows = 0
    invalid_coordinate_rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source_rows += 1
            location_id = (row.get("location_id") or "").strip()
            if not location_id:
                invalid_coordinate_rows += 1
                continue
            aggregate = aggregates.setdefault(
                location_id,
                {
                    "latitude_sum": 0.0,
                    "longitude_sum": 0.0,
                    "valid_count": 0,
                    "latitude_min": None,
                    "latitude_max": None,
                    "longitude_min": None,
                    "longitude_max": None,
                    "source_dataset": row.get("source_dataset") or None,
                },
            )
            try:
                latitude = float(row.get("latitude", ""))
                longitude = float(row.get("longitude", ""))
                if not math.isfinite(latitude) or not math.isfinite(longitude):
                    raise ValueError
            except (TypeError, ValueError):
                invalid_coordinate_rows += 1
                continue
            aggregate["latitude_sum"] += latitude
            aggregate["longitude_sum"] += longitude
            aggregate["valid_count"] += 1
            aggregate["latitude_min"] = _minimum(aggregate["latitude_min"], latitude)
            aggregate["latitude_max"] = _maximum(aggregate["latitude_max"], latitude)
            aggregate["longitude_min"] = _minimum(aggregate["longitude_min"], longitude)
            aggregate["longitude_max"] = _maximum(aggregate["longitude_max"], longitude)

    locations = []
    coordinate_conflict_groups = 0
    rejected_groups = 0
    for location_id, aggregate in aggregates.items():
        if aggregate["valid_count"] == 0:
            rejected_groups += 1
            continue
        if (
            aggregate["latitude_min"] != aggregate["latitude_max"]
            or aggregate["longitude_min"] != aggregate["longitude_max"]
        ):
            coordinate_conflict_groups += 1
        locations.append(
            (
                location_id,
                aggregate["latitude_sum"] / aggregate["valid_count"],
                aggregate["longitude_sum"] / aggregate["valid_count"],
                aggregate["source_dataset"],
            )
        )

    metadata = {
        "source_rows": source_rows,
        "unique_location_ids": len(aggregates),
        "canonical_rows": len(locations),
        "coordinate_conflict_groups": coordinate_conflict_groups,
        "invalid_coordinate_rows": invalid_coordinate_rows,
        "rejected_groups": rejected_groups,
    }
    return locations, metadata


def _minimum(current: float | None, value: float) -> float:
    return value if current is None else min(current, value)


def _maximum(current: float | None, value: float) -> float:
    return value if current is None else max(current, value)


def _empty_location_metadata() -> dict[str, int]:
    return {
        "source_rows": 0,
        "unique_location_ids": 0,
        "canonical_rows": 0,
        "coordinate_conflict_groups": 0,
        "invalid_coordinate_rows": 0,
        "rejected_groups": 0,
    }


def _convert_value(table: str, column: str, value: str | None) -> Any:
    if value is None or value == "":
        return None
    if column in {"car_id", "match_label"}:
        return int(value)
    if column == "amount":
        return float(value)
    return value


def _update_neo4j(root: Path, person_mapping: dict[str, str] | None = None) -> dict[str, int]:
    node_count = 0
    edge_counts: Counter[str] = Counter()
    malformed_graph_edges_skipped = 0
    driver = get_driver()
    with driver.session(database=settings.neo4j_database) as session:
        node_batch = []
        person_node_ids: set[str] = set()
        for row in _iter_graph_nodes(root, person_mapping, person_node_ids):
            if row["node_type"] == "PERSON":
                person_node_ids.add(row["node_id"])
            node_batch.append(row)
            if len(node_batch) >= BATCH_SIZE:
                _merge_nodes(session, node_batch)
                node_count += len(node_batch)
                node_batch.clear()
        if node_batch:
            _merge_nodes(session, node_batch)
            node_count += len(node_batch)

        edge_batches: dict[str, list[dict]] = {relationship: [] for relationship in RELATIONSHIP_TYPES}
        for row, relationship in _iter_graph_edges(root, person_mapping, person_node_ids):
            if relationship == "VISITED" and not row["source_id"].strip():
                malformed_graph_edges_skipped += 1
                continue
            edge_batches[relationship].append(row)
            if len(edge_batches[relationship]) >= BATCH_SIZE:
                _merge_edges(session, relationship, edge_batches[relationship])
                edge_counts[relationship] += len(edge_batches[relationship])
                edge_batches[relationship].clear()
        for relationship, batch in edge_batches.items():
            if batch:
                _merge_edges(session, relationship, batch)
                edge_counts[relationship] += len(batch)
    return {
        "nodes": node_count,
        "relationships": sum(edge_counts.values()),
        "malformed_graph_edges_skipped": malformed_graph_edges_skipped,
        **edge_counts,
    }


def _iter_graph_nodes(
    root: Path,
    person_mapping: dict[str, str] | None,
    person_node_ids: set[str],
):
    if (path := root / "persons.csv").is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                person_node_ids.add(source["person_id"])
                person_id = person_mapping.get(source["person_id"], source["person_id"]) if person_mapping else source["person_id"]
                person_node_ids.add(person_id)
                yield {
                    "node_id": person_id,
                    "node_type": "PERSON",
                    "name": source.get("display_name"),
                    "source_domain": source.get("source_domain"),
                    "source_entity_id": source.get("source_entity_id"),
                }
    if (path := root / "vehicles.csv").is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                yield {
                    "node_id": source["vehicle_id"],
                    "node_type": "VEHICLE",
                    "name": source.get("car_id") or source["vehicle_id"],
                    "source_domain": source.get("source_dataset"),
                    "source_entity_id": source["vehicle_id"],
                }
    if (path := root / "locations.csv").is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                yield {
                    "node_id": source["location_id"],
                    "node_type": "LOCATION",
                    "name": source["location_id"],
                    "source_domain": source.get("source_dataset"),
                    "source_entity_id": source["location_id"],
                }


def _iter_graph_edges(root: Path, person_mapping: dict[str, str] | None, person_node_ids: set[str]):
    path = root / "communications.csv"
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = {"source_id": source["source_person_id"], "target_id": source["target_person_id"]}
                _map_graph_edge_person_ids(row, "COMMUNICATES_WITH", person_mapping, person_node_ids)
                yield row, "COMMUNICATES_WITH"
    elif (path := root / "cdr_records.csv").is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = {"source_id": source["caller_person_id"], "target_id": source["receiver_person_id"]}
                _map_graph_edge_person_ids(row, "COMMUNICATES_WITH", person_mapping, person_node_ids)
                yield row, "COMMUNICATES_WITH"
    path = root / "vehicle_assignments.csv"
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                row = {"source_id": source["person_id"], "target_id": source["vehicle_id"]}
                _map_graph_edge_person_ids(row, "ASSIGNED_TO", person_mapping, person_node_ids)
                yield row, "ASSIGNED_TO"
    path = root / "location_events.csv"
    if path.is_file():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                if not source.get("person_id") or not source.get("location_id"):
                    continue
                row = {"source_id": source["person_id"], "target_id": source["location_id"]}
                _map_graph_edge_person_ids(row, "VISITED", person_mapping, person_node_ids)
                yield row, "VISITED"


def _map_graph_edge_person_ids(
    row: dict[str, str],
    relationship: str,
    person_mapping: dict[str, str] | None,
    person_node_ids: set[str],
) -> None:
    if not person_mapping:
        return
    endpoint_columns = {
        "COMMUNICATES_WITH": ("source_id", "target_id"),
        "ASSIGNED_TO": ("source_id",),
        "VISITED": ("source_id",),
    }[relationship]
    for column in endpoint_columns:
        node_id = row[column]
        if node_id in person_node_ids:
            row[column] = person_mapping.get(node_id, node_id)


def _map_graph_node_person_id(row: dict[str, str], person_mapping: dict[str, str] | None) -> None:
    if row.get("node_type") == "PERSON" and row.get("node_id") and person_mapping:
        row["node_id"] = person_mapping.get(row["node_id"], row["node_id"])


def _count_malformed_graph_edges(path: Path) -> int:
    if not path.is_file():
        return 0
    skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("relationship_type") == "VISITED" and not (row.get("source_id") or "").strip():
                skipped += 1
    return skipped


def _merge_nodes(session, rows: list[dict]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (node:Entity {node_id: row.node_id})
        SET node.node_type = row.node_type,
            node.name = row.name,
            node.source_domain = row.source_domain,
            node.source_entity_id = row.source_entity_id
        """,
        rows=rows,
    ).consume()


def _merge_edges(session, relationship: str, rows: list[dict]) -> None:
    session.run(
        f"""
        UNWIND $rows AS row
        MATCH (source:Entity {{node_id: row.source_id}})
        MATCH (target:Entity {{node_id: row.target_id}})
        MERGE (source)-[:{relationship}]->(target)
        """,
        rows=rows,
    ).consume()


def _mark_latest_run_failed() -> None:
    try:
        with psycopg.connect(settings.supabase_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE public.ingestion_runs
                    SET status = %s, completed_at = %s
                    WHERE ingestion_run_id = (
                        SELECT ingestion_run_id FROM public.ingestion_runs
                        ORDER BY started_at DESC NULLS LAST LIMIT 1
                    )
                    """,
                    ("failed", datetime.now(timezone.utc)),
                )
    except Exception:
        logger.exception("Failed to record ingestion failure")


def _run_row(row: tuple) -> dict:
    return dict(zip(("ingestion_run_id", "case_id", "source_file", "source_dataset", "status", "row_count", "started_at", "completed_at"), row))