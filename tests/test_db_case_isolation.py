"""Case isolation checks for the inv schema.

Needs a disposable Postgres database:  INV_TEST_DSN=postgresql://... pytest tests/test_db_case_isolation.py
Each test creates schema inv from the migration in a fresh transaction and rolls it back.
"""
import os
from pathlib import Path

import psycopg
import pytest

DSN = os.environ.get("INV_TEST_DSN")
MIGRATION = Path(__file__).resolve().parents[1] / "db" / "migrations" / "001_case_scoped_schema.sql"
pytestmark = pytest.mark.skipif(not DSN, reason="set INV_TEST_DSN to a disposable Postgres database")


@pytest.fixture()
def cur():
    with psycopg.connect(DSN) as conn:
        conn.autocommit = False
        c = conn.cursor()
        c.execute("DROP SCHEMA IF EXISTS inv CASCADE")
        c.execute(MIGRATION.read_text())
        for case in ("CASE_A", "CASE_B"):
            c.execute("INSERT INTO inv.cases (case_id, name, source, is_synthetic, role) VALUES (%s, %s, 'test', TRUE, 'investigation')",
                      (case, case))
        # the SAME source IDs in both cases
        c.execute("INSERT INTO inv.persons (case_id, person_id, display_name) VALUES "
                  "('CASE_A','P0001','Alice A'),('CASE_A','P0002','Bob A'),('CASE_B','P0001','Alice B'),('CASE_B','P0003','Carol B')")
        c.execute("INSERT INTO inv.relationships (case_id, person_a, person_b, relationship_type, source_table) "
                  "VALUES ('CASE_A','P0001','P0002','EMAILED','test')")
        yield c
        conn.rollback()


def expect_fk_error(cur, sql, params=()):
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        cur.execute(sql, params)
    cur.execute("ROLLBACK TO SAVEPOINT s")


def test_same_ids_coexist_without_overwriting(cur):
    cur.execute("SELECT case_id, display_name FROM inv.persons WHERE person_id='P0001' ORDER BY case_id")
    assert cur.fetchall() == [("CASE_A", "Alice A"), ("CASE_B", "Alice B")]


def test_relationship_cannot_reference_person_of_other_case(cur):
    # P0003 exists only in CASE_B
    expect_fk_error(cur, "INSERT INTO inv.relationships (case_id, person_a, person_b, relationship_type, source_table) "
                         "VALUES ('CASE_A','P0001','P0003','EMAILED','test')")


def test_analysis_result_cannot_mix_cases(cur):
    cur.execute("INSERT INTO inv.analysis_runs (case_id, mode, algorithm, status) VALUES ('CASE_A','observed_only','test','completed') "
                "RETURNING analysis_run_id")
    run = cur.fetchone()[0]
    # result row claiming CASE_B for a CASE_A run
    expect_fk_error(cur, "INSERT INTO inv.person_metrics (case_id, analysis_run_id, person_id) VALUES ('CASE_B', %s, 'P0001')", (run,))
    # CASE_A run pointing at a person who exists only in CASE_B
    expect_fk_error(cur, "INSERT INTO inv.person_metrics (case_id, analysis_run_id, person_id) VALUES ('CASE_A', %s, 'P0003')", (run,))
    cur.execute("INSERT INTO inv.person_metrics (case_id, analysis_run_id, person_id, pagerank) VALUES ('CASE_A', %s, 'P0001', 0.5)", (run,))


def test_evidence_cannot_cross_cases(cur):
    cur.execute("INSERT INTO inv.vehicles (case_id, vehicle_id) VALUES ('CASE_A','V001')")
    cur.execute("INSERT INTO inv.locations (case_id, location_id, latitude, longitude) VALUES ('CASE_B','L1',36.0,24.8)")
    # CASE_A GPS row pointing at a CASE_B location
    expect_fk_error(cur, "INSERT INTO inv.location_events (case_id, event_id, vehicle_id, location_id, observed_at, event_type) "
                         "VALUES ('CASE_A','E1','V001','L1','2014-01-06 08:00','VEHICLE_GPS')")


def test_queries_and_graph_view_are_case_scoped(cur):
    cur.execute("SELECT count(*) FROM inv.case_graph_edges WHERE case_id='CASE_B'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT count(*) FROM inv.case_graph_edges WHERE case_id='CASE_A'")
    assert cur.fetchone()[0] == 1


def test_deleting_one_case_leaves_the_other_intact(cur):
    cur.execute("DELETE FROM inv.cases WHERE case_id='CASE_A'")
    cur.execute("SELECT case_id, count(*) FROM inv.persons GROUP BY case_id")
    assert cur.fetchall() == [("CASE_B", 2)]
    cur.execute("SELECT count(*) FROM inv.relationships")
    assert cur.fetchone()[0] == 0


def test_gps_person_must_stay_in_case_and_may_be_null(cur):
    cur.execute("INSERT INTO inv.vehicles (case_id, vehicle_id) VALUES ('CASE_A','V001')")
    cur.execute("INSERT INTO inv.locations (case_id, location_id, latitude, longitude) VALUES ('CASE_A','L1',36.0,24.8)")
    cur.execute("INSERT INTO inv.location_events (case_id, event_id, vehicle_id, location_id, observed_at, event_type) "
                "VALUES ('CASE_A','E1','V001','L1','2014-01-06 08:00','VEHICLE_GPS')")
    expect_fk_error(cur, "INSERT INTO inv.location_events (case_id, event_id, vehicle_id, person_id, location_id, observed_at, event_type) "
                         "VALUES ('CASE_A','E2','V001','P0003','L1','2014-01-06 08:05','VEHICLE_GPS')")
