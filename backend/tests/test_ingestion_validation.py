import asyncio
import csv
import io
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from app.routes import ingestion as ingestion_route
from app.services import ingestion_service


PERSON_COLUMNS = ingestion_service.CSV_SPECS["persons.csv"][1]
COMMUNICATION_COLUMNS = ingestion_service.CSV_SPECS["communications.csv"][1]
OPTIONAL_FILES = [
    "location_events.csv",
    "locations.csv",
    "vehicles.csv",
    "vehicle_assignments.csv",
    "transactions.csv",
    "loyalty_events.csv",
    "identity_resolution.csv",
]


def write_csv(root, name, columns, rows=None):
    path = root / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        if rows:
            writer.writerows(rows)
    return path


def make_dataset(tmp_path, *, communications=False, cdr=False, optional=False, persons=True):
    if persons:
        write_csv(tmp_path, "persons.csv", PERSON_COLUMNS)
    if communications:
        write_csv(tmp_path, "communications.csv", COMMUNICATION_COLUMNS)
    if cdr:
        write_csv(tmp_path, "cdr_records.csv", ["caller_person_id", "receiver_person_id", "caller_phone"])
    if optional:
        for name in OPTIONAL_FILES:
            write_csv(tmp_path, name, ingestion_service.CSV_SPECS[name][1])
    return tmp_path


def test_persons_and_communications_only_is_valid(tmp_path):
    validation = ingestion_service.validate_dataset_directory(make_dataset(tmp_path, communications=True))
    assert validation["valid"] is True


def test_persons_and_cdr_only_is_valid(tmp_path):
    validation = ingestion_service.validate_dataset_directory(make_dataset(tmp_path, cdr=True))
    assert validation["valid"] is True


def test_persons_with_both_communication_sources_is_valid(tmp_path):
    validation = ingestion_service.validate_dataset_directory(
        make_dataset(tmp_path, communications=True, cdr=True)
    )
    assert validation["valid"] is True


def test_persons_without_communication_source_is_invalid(tmp_path):
    validation = ingestion_service.validate_dataset_directory(make_dataset(tmp_path))
    assert validation["valid"] is False
    assert "communications.csv or cdr_records.csv" in validation["missing_files"]


def test_missing_persons_is_invalid(tmp_path):
    validation = ingestion_service.validate_dataset_directory(
        make_dataset(tmp_path, communications=True, persons=False)
    )
    assert validation["valid"] is False
    assert "persons.csv" in validation["missing_files"]


def test_all_optional_files_can_be_absent(tmp_path):
    validation = ingestion_service.validate_dataset_directory(make_dataset(tmp_path, communications=True))
    assert validation["valid"] is True
    assert validation["locations"] == {
        "source_rows": 0,
        "unique_location_ids": 0,
        "canonical_rows": 0,
        "coordinate_conflict_groups": 0,
        "invalid_coordinate_rows": 0,
        "rejected_groups": 0,
    }


def test_optional_files_are_validated_when_present(tmp_path):
    validation = ingestion_service.validate_dataset_directory(
        make_dataset(tmp_path, communications=True, optional=True)
    )
    assert validation["valid"] is True
    assert validation["optional_missing"] == []


def test_graph_import_files_are_not_required(tmp_path):
    validation = ingestion_service.validate_dataset_directory(make_dataset(tmp_path, communications=True))
    assert validation["valid"] is True
    assert "graph_nodes.csv" not in validation["missing_files"]
    assert "graph_edges.csv" not in validation["missing_files"]


def test_dry_run_uses_the_same_required_file_rules(tmp_path):
    archive = tmp_path / "missing.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("persons.csv", "person_id\n")
    result = ingestion_service.ingest_archive(archive, dry_run=True)
    assert result["status"] == "validation_failed"


def make_upload_archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    stream.seek(0)
    return UploadFile(file=stream, filename="dataset.zip")


def test_upload_returns_http_400_for_invalid_archive(tmp_path):
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("persons.csv", "person_id\n")
    upload = UploadFile(file=archive.open("rb"), filename="dataset.zip")
    with pytest.raises(HTTPException) as error:
        asyncio.run(ingestion_route.upload_dataset(upload, dry_run=True))
    assert error.value.status_code == 400


def test_upload_succeeds_for_valid_archive(monkeypatch):
    monkeypatch.setattr(
        ingestion_route,
        "ingest_archive",
        lambda _path, dry_run=False: {"status": "validated" if dry_run else "completed"},
    )
    upload = make_upload_archive({
        "persons.csv": ",".join(PERSON_COLUMNS) + "\n",
        "cdr_records.csv": "caller_person_id,receiver_person_id,caller_phone\n",
    })
    result = asyncio.run(ingestion_route.upload_dataset(upload, dry_run=True))
    assert result == {"status": "validated"}


def test_neo4j_graph_rows_derive_from_supported_uploads(tmp_path):
    write_csv(tmp_path, "persons.csv", PERSON_COLUMNS, [{
        "person_id": "P1",
        "source_domain": "TEST",
        "source_entity_id": "P1",
        "display_name": "Person One",
    }])
    write_csv(tmp_path, "communications.csv", COMMUNICATION_COLUMNS, [{
        "communication_id": "C1",
        "source_person_id": "P1",
        "target_person_id": "P1",
    }])
    write_csv(tmp_path, "vehicles.csv", ingestion_service.CSV_SPECS["vehicles.csv"][1], [{
        "vehicle_id": "V1",
        "car_id": "1",
    }])
    write_csv(tmp_path, "vehicle_assignments.csv", ingestion_service.CSV_SPECS["vehicle_assignments.csv"][1], [{
        "vehicle_id": "V1",
        "person_id": "P1",
    }])
    write_csv(tmp_path, "locations.csv", ingestion_service.CSV_SPECS["locations.csv"][1], [{
        "location_id": "L1",
        "latitude": "1",
        "longitude": "2",
    }])
    write_csv(tmp_path, "location_events.csv", ingestion_service.CSV_SPECS["location_events.csv"][1], [{
        "event_id": "E1",
        "person_id": "P1",
        "location_id": "L1",
    }])

    person_ids = set()
    nodes = list(ingestion_service._iter_graph_nodes(tmp_path, {}, person_ids))
    edges = list(ingestion_service._iter_graph_edges(tmp_path, {}, person_ids))

    assert {node["node_type"] for node in nodes} == {"PERSON", "VEHICLE", "LOCATION"}
    assert {relationship for _, relationship in edges} == {
        "COMMUNICATES_WITH",
        "ASSIGNED_TO",
        "VISITED",
    }


def test_cdr_only_communication_source_derives_communication_edges(tmp_path):
    write_csv(tmp_path, "persons.csv", PERSON_COLUMNS, [{
        "person_id": "P1",
        "source_domain": "TEST",
        "source_entity_id": "P1",
        "display_name": "Person One",
    }, {
        "person_id": "P2",
        "source_domain": "TEST",
        "source_entity_id": "P2",
        "display_name": "Person Two",
    }])
    write_csv(tmp_path, "cdr_records.csv", ["caller_person_id", "receiver_person_id", "call_start_time"], [{
        "caller_person_id": "P1",
        "receiver_person_id": "P2",
        "call_start_time": "2026-01-01T00:00:00Z",
    }])

    person_ids = set()
    list(ingestion_service._iter_graph_nodes(tmp_path, {}, person_ids))
    edges = list(ingestion_service._iter_graph_edges(tmp_path, {}, person_ids))

    assert edges == [
        ({"source_id": "P1", "target_id": "P2"}, "COMMUNICATES_WITH"),
    ]


def test_communications_source_remains_preferred_when_cdr_also_exists(tmp_path):
    write_csv(tmp_path, "communications.csv", COMMUNICATION_COLUMNS, [{
        "communication_id": "C1",
        "source_person_id": "P1",
        "target_person_id": "P2",
    }])
    write_csv(tmp_path, "cdr_records.csv", ["caller_person_id", "receiver_person_id"], [{
        "caller_person_id": "P3",
        "receiver_person_id": "P4",
    }])

    edges = list(ingestion_service._iter_graph_edges(tmp_path, {}, {"P1", "P2", "P3", "P4"}))

    assert edges == [
        ({"source_id": "P1", "target_id": "P2"}, "COMMUNICATES_WITH"),
    ]
