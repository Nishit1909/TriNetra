import csv

import pandas as pd

from app.services import ingestion_service


class FakeCursor:
    def __init__(self, existing):
        self.existing = existing
        self.execute_calls = []
        self.executemany_calls = []

    def execute(self, statement, params=None):
        self.execute_calls.append((statement, params))

    def fetchall(self):
        return self.existing

    def executemany(self, statement, rows):
        self.executemany_calls.append((statement, list(rows)))


def write_persons(tmp_path, rows):
    path = tmp_path / "persons.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ingestion_service.CSV_SPECS["persons.csv"][1])
        writer.writeheader()
        writer.writerows(rows)
    return path


def person(person_id, name):
    return {
        "person_id": person_id,
        "source_domain": "TEST",
        "source_entity_id": person_id,
        "display_name": name,
        "department": "Engineering",
        "job_title": "Engineer",
        "identity_bridge_type": "",
    }


def resolution(raw_name, status, score, matched_person_id="P0001", matched_display_name="Canonical Name", temp_id=None):
    return {
        "raw_name": raw_name,
        "matched_person_id": matched_person_id if status != "created_new" else None,
        "matched_display_name": matched_display_name if status != "created_new" else None,
        "score": score,
        "runner_up_score": 0.0,
        "ambiguous": False,
        "corroboration_available": False,
        "corroborated": None,
        "effective_threshold_high": 80.0,
        "status": status,
        "new_person_temp_id": temp_id,
    }


def test_existing_person_id_uses_normal_upsert_without_matching(tmp_path, monkeypatch):
    cursor = FakeCursor([("P0001", "Canonical Name")])

    mapping, stats = ingestion_service._upsert_persons(cursor, write_persons(tmp_path, [person("P0001", "Changed Name")]))

    assert mapping == {}
    assert stats["checked"] == 0
    assert len(cursor.execute_calls) == 1
    assert "COALESCE" not in cursor.executemany_calls[0][0]


def test_new_person_high_score_resolves_and_is_audited(tmp_path, monkeypatch):
    cursor = FakeCursor([("P0001", "Canonical Name")])
    monkeypatch.setattr(
        ingestion_service,
        "resolve_names_batch",
        lambda names, _roster, **_kwargs: pd.DataFrame([
            resolution(names[0], "auto_merged", 85),
        ]),
    )

    mapping, stats = ingestion_service._upsert_persons(cursor, write_persons(tmp_path, [person("P9999", "Variant Name")]))

    assert mapping == {"P9999": "P0001"}
    assert stats["auto_merged"] == 1
    assert stats["matches"][0]["auto_merged"] is True
    assert stats["audit_records"][0]["canonical_person_id"] == "P0001"
    assert len(cursor.executemany_calls) == 1
    assert "COALESCE" in cursor.executemany_calls[0][0]


def test_medium_and_low_scores_remain_separate(tmp_path, monkeypatch):
    cursor = FakeCursor([("P0001", "Canonical Name")])
    monkeypatch.setattr(
        ingestion_service,
        "resolve_names_batch",
        lambda names, _roster, **_kwargs: pd.DataFrame([
            resolution(names[0], "needs_human_review", 65),
            resolution(names[1], "created_new", 40, temp_id="NEW-0001"),
        ]),
    )

    mapping, stats = ingestion_service._upsert_persons(
        cursor,
        write_persons(tmp_path, [person("P9998", "Review Name"), person("P9997", "Different Name")]),
    )

    assert mapping == {}
    assert stats["review_required"] == 1
    assert stats["kept_separate"] == 1
    assert stats["matches"][0]["candidate_id"] == "P0001"
    assert stats["matches"][0]["score"] == 65


def test_resolved_ids_propagate_to_all_person_references():
    mapping = {"P9999": "P0001"}
    communications = {"source_person_id": "P9999", "target_person_id": "P0002"}
    assignments = {"person_id": "P9999"}
    events = {"person_id": "P9999"}

    ingestion_service._map_person_references("communications", communications, mapping)
    ingestion_service._map_person_references("vehicle_assignments", assignments, mapping)
    ingestion_service._map_person_references("location_events", events, mapping)

    assert communications == {"source_person_id": "P0001", "target_person_id": "P0002"}
    assert assignments["person_id"] == "P0001"
    assert events["person_id"] == "P0001"


def test_person_matching_loads_existing_people_once(tmp_path, monkeypatch):
    cursor = FakeCursor([("P0001", "Canonical Name"), ("P0002", "Another Name")])

    ingestion_service._upsert_persons(cursor, write_persons(tmp_path, [person("P9999", "New Name")]))

    assert len(cursor.execute_calls) == 1
    assert cursor.execute_calls[0][0].startswith("SELECT person_id, display_name")


def test_person_graph_node_is_remapped_but_non_person_node_is_not():
    mapping = {"P9999": "P0001"}
    person_node = {"node_type": "PERSON", "node_id": "P9999"}
    vehicle_node = {"node_type": "VEHICLE", "node_id": "P9999"}

    ingestion_service._map_graph_node_person_id(person_node, mapping)
    ingestion_service._map_graph_node_person_id(vehicle_node, mapping)

    assert person_node["node_id"] == "P0001"
    assert vehicle_node["node_id"] == "P9999"


def test_graph_edges_map_only_person_endpoints_by_relationship():
    mapping = {"P9999": "P0001", "P0002": "P0003"}
    person_ids = {"P9999", "P0002"}

    communication = {"source_id": "P9999", "target_id": "P0002"}
    assignment = {"source_id": "P9999", "target_id": "P0002"}
    visited = {"source_id": "P9999", "target_id": "P0002"}

    ingestion_service._map_graph_edge_person_ids(communication, "COMMUNICATES_WITH", mapping, person_ids)
    ingestion_service._map_graph_edge_person_ids(assignment, "ASSIGNED_TO", mapping, person_ids)
    ingestion_service._map_graph_edge_person_ids(visited, "VISITED", mapping, person_ids)

    assert communication == {"source_id": "P0001", "target_id": "P0003"}
    assert assignment == {"source_id": "P0001", "target_id": "P0002"}
    assert visited == {"source_id": "P0001", "target_id": "P0002"}
