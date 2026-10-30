"""Read API contract against disposable Postgres; transactions always roll back."""
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.investigation import evidence

pytestmark = pytest.mark.skipif(not os.getenv("INV_TEST_DSN"), reason="needs disposable INV_TEST_DSN")


@pytest.fixture
def api(monkeypatch):
    conn = psycopg.connect(os.environ["INV_TEST_DSN"], row_factory=dict_row)
    try:
        if not conn.execute("SELECT to_regclass('inv.cases') AS name").fetchone()["name"]:
            migration = Path(__file__).resolve().parents[2] / "db/migrations/001_case_scoped_schema.sql"
            conn.execute(migration.read_text())
        case = "API_EVIDENCE_" + uuid4().hex
        other = case + "_OTHER"
        for case_id in (case, other):
            conn.execute("INSERT INTO inv.cases(case_id,name,source,is_synthetic,role) VALUES (%s,%s,'test',true,'investigation')", (case_id, case_id))
            conn.execute("INSERT INTO inv.persons(case_id,person_id,display_name,department) VALUES (%s,'A',%s,'Security'),(%s,'B','Bob','Engineering')", (case_id, case_id, case_id))
            conn.execute("INSERT INTO inv.relationships(case_id,person_a,person_b,relationship_type,source_table,source_note) VALUES (%s,'A','B','MEETING','coded_source','original row')", (case_id,))
        conn.execute("INSERT INTO inv.persons(case_id,person_id,display_name) VALUES (%s,'ONLY_OTHER','Hidden')", (other,))
        conn.execute("INSERT INTO inv.communication_events(case_id,communication_id,source_person_id,target_person_id,communication_type,time_known,is_broadcast,subject,source_file,source_row) VALUES (%s,'E','B','A','email',false,false,'Actual header','headers.csv',9)", (case,))
        conn.execute("INSERT INTO inv.documents(case_id,document_id,document_type,body) VALUES (%s,'D','text','Alice evidence')", (case,))
        conn.execute("INSERT INTO inv.document_mentions(case_id,document_id,entity_type,entity_id,matched_text,start_char,end_char,method) VALUES (%s,'D','PERSON','A','Alice',0,5,'exact')", (case,))
        conn.execute("INSERT INTO inv.inferred_relationships(case_id,person_a,person_b,relationship_type,person_attribution,lead_strength,lead_level,factors,possible_innocent_explanations,supporting_colocation_ids,email_ids) VALUES (%s,'B','A','MET_PRIVATELY','assigned_driver_assumed',45,'medium','{\"chance_p_value\":0.5}','May share a workplace', '{}','{E}')", (case,))
        for case_id in (case, other):
            conn.execute("INSERT INTO inv.places(case_id,place_id,latitude,longitude,stops,vehicles,place_type) VALUES (%s,'PL',1,2,2,2,'public')", (case_id,))
            conn.execute("INSERT INTO inv.locations(case_id,location_id,latitude,longitude) VALUES (%s,'L',1,2)", (case_id,))
            for person in ('A', 'B'):
                conn.execute("INSERT INTO inv.vehicles(case_id,vehicle_id) VALUES (%s,%s)", (case_id, person))
                conn.execute("INSERT INTO inv.vehicle_assignments(case_id,vehicle_id,person_id,relationship) VALUES (%s,%s,%s,'assigned')", (case_id, person, person))
                conn.execute("INSERT INTO inv.location_events(case_id,event_id,vehicle_id,location_id,observed_at,event_type) VALUES (%s,%s,%s,'L','2014-01-01 10:00','GPS')", (case_id, person, person))
                conn.execute("INSERT INTO inv.vehicle_stops(case_id,stop_id,vehicle_id,assigned_person_id,person_attribution,place_id,stop_start,stop_end,duration_min,last_gps_event_id,inference_status) VALUES (%s,%s,%s,%s,'assigned_driver_assumed','PL','2014-01-01 10:00','2014-01-01 11:00',60,%s,'inferred_stationary')", (case_id, person, person, person, person))
            conn.execute("INSERT INTO inv.colocation_events(case_id,colocation_id,vehicle_id_a,vehicle_id_b,person_a,person_b,person_attribution,place_id,context,overlap_start,overlap_end,overlap_min,after_hours,stop_a,stop_b) VALUES (%s,'CO','B','A','B','A','assigned_driver_assumed','PL','public','2014-01-01 10:00','2014-01-01 11:00',60,false,'B','A')", (case_id,))

        @contextmanager
        def connect():
            yield conn

        monkeypatch.setattr(evidence, "connect", connect)
        app = FastAPI()
        app.include_router(evidence.router)
        with TestClient(app) as client:
            yield client, case, other, conn
    finally:
        conn.rollback()
        conn.close()


def test_person_pagination_profile_and_isolation(api):
    client, case, _, _ = api
    base = f"/api/cases/{case}"
    result = client.get(base + "/persons", params={"department": "Security", "q": case, "limit": 1}).json()
    assert result["total"] == 1
    assert result["items"][0]["display_name"] == case
    profile = client.get(base + "/persons/A").json()
    assert profile["counts"] == {"emails": 1, "colocations": 1, "documents": 1}
    assert profile["vehicle_assignments"][0]["person_attribution"] == "assigned_driver_assumed"
    assert client.get(base + "/persons/ONLY_OTHER").status_code == 404
    assert client.get("/api/cases/MISSING/persons").status_code == 404
    assert client.get(base + "/persons?limit=0").status_code == 422
    assert client.get(base + "/persons?offset=-1").status_code == 422
    assert client.get(base + "/persons?offset=500").json()["total"] == 2


def test_pair_evidence_both_directions_and_coded_ties(api):
    client, case, other, _ = api
    result = client.get(f"/api/cases/{case}/relationships/B/A").json()
    assert result["emails"]["items"][0]["subject"] == "Actual header"
    assert result["emails"]["items"][0]["source_row"] == 9
    assert result["inferred_relationships"][0]["factors"]["chance_p_value"] == 0.5
    assert result["inferred_relationships"][0]["is_inferred"] is True
    assert result["inferred_relationships"][0]["possible_innocent_explanations"] == "May share a workplace"
    colocation = result["colocation_events"]["items"][0]
    assert colocation["place"]["case_id"] == case
    assert colocation["stop_a"]["assigned_person_id"] == "B"
    assert colocation["stop_b"]["person_attribution"] == "assigned_driver_assumed"
    coded = client.get(f"/api/cases/{other}/relationships/A/B").json()
    assert coded["emails"]["items"] == []
    assert coded["observed_relationships"][0]["source_table"] == "coded_source"
    assert client.get(f"/api/cases/{case}/relationships/A/ONLY_OTHER").status_code == 404


def test_edges_leads_documents_timeline_summary(api):
    client, case, _, _ = api
    base = f"/api/cases/{case}"
    edges = client.get(base + "/relationships?kind=inferred").json()
    assert edges["total"] == 1
    assert edges["items"][0]["lead_strength"] == 45
    assert client.get(base + "/relationships?kind=bogus").status_code == 422
    assert client.get(base + "/leads").json()["total"] == 1
    assert client.get(base + "/leads?level=strong").json()["total"] == 0
    assert client.get(base + "/documents/D").json()["mentions"][0]["end_char"] == 5
    assert client.get(base + "/documents/MISSING").status_code == 404
    assert client.get(base + "/places/MISSING").status_code == 404
    timeline = client.get(base + "/persons/A/timeline").json()
    assert timeline["total"] == 2
    assert timeline["items"][0]["event_type"] == "vehicle_stop"
    assert timeline["items"][0]["evidence"]["person_attribution"] == "assigned_driver_assumed"
    assert timeline["items"][1]["event_type"] == "email"
    assert client.get(base + "/places/PL").json()["vehicle_stops"]["total"] == 2
    assert client.get(base + "/summary").json()["counts"]["persons"] == 2


def test_reversed_inference_rows_do_not_multiply_graph_edges(api):
    client, case, _, conn = api
    conn.execute("""INSERT INTO inv.inferred_relationships
        SELECT case_id,person_b,person_a,relationship_type,person_attribution,lead_strength,
               lead_level,factors,possible_innocent_explanations,supporting_colocation_ids,email_ids,relationship_key
        FROM inv.inferred_relationships WHERE case_id=%s""", (case,))
    result = client.get(f"/api/cases/{case}/relationships?kind=inferred").json()
    assert result["total"] == 2
    assert all(row["lead_strength"] == 45 for row in result["items"])
