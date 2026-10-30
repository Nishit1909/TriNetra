import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.investigation import analysis, graph


def model_result():
    weights = json.loads(analysis.WEIGHTS_PATH.read_bytes())
    return analysis.run_case_analysis(pd.DataFrame({"person_id":["A","B"]}),
        pd.DataFrame([dict(person_a="A",person_b="B",relationship_type="MEETINGS",weight=1,is_inferred=False,evidence_refs=["EV"])]),
        "observed_only",weights)


@pytest.mark.parametrize("mutation",["unknown_person","duplicate_metric","nonfinite","nan_metric","duplicate_link","unknown_evidence","lying_status"])
def test_output_validation_prevents_bad_results(mutation):
    result = model_result()
    if mutation == "unknown_person":
        result["person_metrics"].loc[0,"person_id"] = "OTHER_CASE"
    elif mutation == "duplicate_metric":
        result["person_metrics"] = pd.concat([result["person_metrics"],result["person_metrics"].iloc[[0]]])
    elif mutation == "nonfinite":
        result["person_metrics"].loc[0,"pagerank"] = float("inf")
    elif mutation == "nan_metric":
        result["person_metrics"].loc[0,"pagerank"] = float("nan")
    elif mutation == "duplicate_link":
        result["predicted_links"] = pd.concat([result["predicted_links"]]*2)
    elif mutation == "unknown_evidence":
        result["predicted_links"].at[0,"evidence_refs"] = ["OTHER_CASE_EVENT"]
    else:
        result["status"] = "partial"
    with pytest.raises(ValueError):
        analysis.validate_output(result,{"A","B"},{"EV"})


def test_real_model_output_and_version_are_accepted():
    result = model_result()
    metrics,links = analysis.validate_output(result,{"A","B"},{"EV"})
    assert len(metrics) == 2 and links[0]["evidence_refs"] == ["EV"]
    assert result["weights_version"] == "v1.1"


@pytest.mark.parametrize("missing",[float("nan"),float("inf"),pd.NA,None])
def test_nullable_community_is_normalized_without_stringifying_nan(missing):
    result = model_result()
    result["person_metrics"]["community_id"] = missing
    metrics,_ = analysis.validate_output(result,{"A","B"},{"EV"})
    assert all(row["community_id"] is None for row in metrics)


@pytest.fixture
def api(monkeypatch):
    dsn = os.getenv("INV_TEST_DSN")
    if not dsn:
        pytest.skip("needs disposable INV_TEST_DSN")
    case = "ANALYSIS_" + uuid4().hex
    other = case + "_OTHER"
    @contextmanager
    def connect():
        with psycopg.connect(dsn,row_factory=dict_row) as conn:
            yield conn
    with connect() as conn:
        if not conn.execute("SELECT to_regclass('inv.cases') name").fetchone()["name"]:
            conn.execute((Path(__file__).resolve().parents[2]/"db/migrations/001_case_scoped_schema.sql").read_text())
        if not conn.execute("SELECT to_regclass('inv.predicted_link_reviews') name").fetchone()["name"]:
            conn.execute((Path(__file__).resolve().parents[2]/"db/migrations/002_analysis_review_audit.sql").read_text())
        for cid in (case,other):
            conn.execute("INSERT INTO inv.cases(case_id,name,source,is_synthetic,role) VALUES (%s,%s,'test',true,'investigation')",(cid,cid))
            for pid in "ABC":
                conn.execute("INSERT INTO inv.persons(case_id,person_id,display_name) VALUES (%s,%s,%s)",(cid,pid,pid))
            conn.execute("INSERT INTO inv.relationships(case_id,person_a,person_b,relationship_type,source_table) VALUES (%s,'A','B','MEETINGS','test')",(cid,))
        conn.execute("INSERT INTO inv.relationships(case_id,person_a,person_b,relationship_type,weight,source_table) VALUES (%s,'B','C','EMAILED',99,'communication_events')",(case,))
        conn.execute("""INSERT INTO inv.communication_events(case_id,communication_id,source_person_id,target_person_id,communication_type,time_known,is_broadcast)
          VALUES (%s,'BROADCAST','B','C','email',false,true),(%s,'DIRECT','B','C','email',false,false)""",(case,case))
    monkeypatch.setattr(analysis,"connect",connect)
    monkeypatch.setattr(graph,"connect",connect)
    def no_neo(*args):
        raise RuntimeError("Test Neo4j outage")
    monkeypatch.setattr(graph,"neo_graph",no_neo)
    app = FastAPI()
    @app.middleware("http")
    async def identity(request, call_next):
        request.state.principal = SimpleNamespace(local=False,user_id="verified-reviewer")
        return await call_next(request)
    app.include_router(analysis.router)
    app.include_router(graph.router)
    try:
        with TestClient(app) as client:
            yield client,case,other,connect
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM inv.cases WHERE case_id IN (%s,%s)",(case,other))


def test_analysis_roundtrip_isolation_and_fallback_graph(api):
    client,case,other,connect = api
    base = f"/api/cases/{case}"
    result = client.post(base+"/analysis",json={"mode":"observed_only"}).json()
    assert result["run"]["status"] == "completed",result
    run_id = result["run"]["analysis_run_id"]
    assert len(result["person_metrics"]) == 3
    assert {row["method"] for row in result["predicted_links"]} == {"tie_without_recorded_communication","network_proximity_ppr"}
    retrieved = client.get(base+f"/analysis/{run_id}").json()
    assert retrieved["predicted_links"] == result["predicted_links"]
    assert all(isinstance(row["factor_breakdown"],dict) for row in retrieved["predicted_links"])
    assert len(result["run"]["parameters"]["input_sha256"]) == 64
    assert result["run"]["parameters"]["stages"]["link_prediction"]["status"] == "ok"
    assert client.get(f"/api/cases/{other}/analysis/{run_id}").status_code == 404
    assert client.get(f"/api/cases/{other}/graph?run_id={run_id}").status_code == 404
    graph_result = client.get(base+f"/graph?run_id={run_id}&include=observed,predicted&limit=2&edge_limit=1").json()
    assert graph_result["graph_source"] == "postgresql_fallback"
    assert graph_result["warnings"] and graph_result["counts"]["shown_nodes"] == 2
    assert client.get(base+"/analysis?limit=101").status_code == 422
    assert client.get(base+"/graph?include=bad").status_code == 422
    assert client.get(base+"/graph?limit=101").status_code == 422
    assert client.get(base+f"/graph?run_id={run_id}&mode=observed_plus_inferred").status_code == 422
    with connect() as conn:
        _,edges = analysis.load_inputs(conn,case,"observed_only")
        mail = edges[edges.relationship_type == "EMAILED"].iloc[0]
        assert mail.factors == {"email_events":2,"direct_email_events":1}
        assert mail.evidence_refs == ["BROADCAST","DIRECT"]


def test_model_exception_fails_exact_run_and_preserves_prior_run(api,monkeypatch):
    client,case,_,_ = api
    base = f"/api/cases/{case}"
    first = client.post(base+"/analysis",json={}).json()["run"]
    def broken(*args):
        raise RuntimeError("postgresql://private:secret@database/internal SELECT private_column FROM private_table")
    monkeypatch.setattr(analysis,"run_case_analysis",broken)
    failed = client.post(base+"/analysis",json={}).json()
    assert failed["run"]["status"] == "failed"
    assert failed["run"]["parameters"]["failure"] == {"code":"analysis_execution_failed","phase":"model","exception_type":"RuntimeError"}
    assert "secret" not in json.dumps(failed) and "private_column" not in json.dumps(failed)
    assert failed["person_metrics"] == [] and failed["predicted_links"] == []
    assert client.get(base+"/analysis/"+first["analysis_run_id"]).json()["run"]["status"] == "completed"


def test_partial_stages_and_invalid_output_are_persisted_honestly(api,monkeypatch):
    client,case,_,_ = api
    real = analysis.run_case_analysis
    def partial(*args):
        output = real(*args)
        output["status"] = "partial"
        output["stages"]["communities"].update(status="failed",error="forced community failure")
        output["person_metrics"]["community_id"] = float("nan")
        return output
    monkeypatch.setattr(analysis,"run_case_analysis",partial)
    base = f"/api/cases/{case}"
    result = client.post(base+"/analysis",json={}).json()
    assert result["run"]["status"] == "partial"
    assert result["run"]["parameters"]["stages"]["communities"]["error"] == "forced community failure"
    assert all(row["community_id"] is None for row in result["person_metrics"])
    with api[3]() as conn:
        stored = conn.execute("SELECT community_id FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s",(case,result["run"]["analysis_run_id"])).fetchall()
        assert all(row["community_id"] is None for row in stored)
    def invalid(*args):
        output = real(*args)
        output["person_metrics"].loc[0,"person_id"] = "OTHER_CASE_PERSON"
        return output
    monkeypatch.setattr(analysis,"run_case_analysis",invalid)
    result = client.post(base+"/analysis",json={}).json()
    assert result["run"]["status"] == "failed"
    assert result["person_metrics"] == [] and result["predicted_links"] == []


def test_modes_keep_inferred_inputs_and_supporting_ids_distinct(api):
    client,case,_,connect = api
    with connect() as conn:
        conn.execute("""INSERT INTO inv.inferred_relationships
          (case_id,person_a,person_b,relationship_type,person_attribution,lead_strength,lead_level,factors,
           possible_innocent_explanations,supporting_colocation_ids,email_ids)
          VALUES (%s,'A','C','MET_PRIVATELY','assigned_driver_assumed',60,'medium',
            '{"private_days":2,"home_visits":1,"private_meetings":2,"after_hours_private":2}',
            'May be friends',ARRAY['COLOCATION_SUPPORT'],ARRAY[]::text[])""",(case,))
        _,observed = analysis.load_inputs(conn,case,"observed_only")
        _,mixed = analysis.load_inputs(conn,case,"observed_plus_inferred")
        assert len(mixed) == len(observed) + 1
        assert mixed.iloc[-1].evidence_refs == ["COLOCATION_SUPPORT"]
    base = f"/api/cases/{case}"
    result = client.post(base+"/analysis",json={"mode":"observed_plus_inferred"}).json()
    assert result["run"]["status"] == "completed",result
    lead = next(row for row in result["predicted_links"] if row["person_a"] == "A" and row["person_b"] == "C")
    assert lead["evidence_refs"] == ["COLOCATION_SUPPORT"]
    observed_graph = client.get(base+"/graph?mode=observed_only&include=observed,inferred").json()
    assert all(edge["kind"] == "observed" for edge in observed_graph["edges"])


def test_broadcast_only_email_edges_are_absent_from_computed_display_graph(api):
    client,case,_,connect = api
    with connect() as conn:
        conn.execute("DELETE FROM inv.communication_events WHERE case_id=%s AND communication_id='DIRECT'",(case,))
    base = f"/api/cases/{case}"
    result = client.post(base+"/analysis",json={}).json()
    assert result["run"]["status"] == "completed"
    isolated = next(row for row in result["person_metrics"] if row["person_id"] == "C")
    assert isolated["degree"] == 0
    display = client.get(base+"/graph").json()
    assert display["counts"]["total_edges"] == 1
    assert all(edge["type"] != "EMAILED" for edge in display["edges"])


def test_filtered_neo_snapshot_is_reconciled_to_full_canonical_topology(api,monkeypatch):
    client,case,_,connect = api
    with connect() as conn:
        conn.execute("""INSERT INTO inv.inferred_relationships
          (case_id,person_a,person_b,relationship_type,person_attribution,lead_strength,lead_level,factors,
           possible_innocent_explanations,supporting_colocation_ids,email_ids)
          VALUES (%s,'A','C','MET_PRIVATELY','assigned_driver_assumed',10,'weak',
            '{"private_days":1,"private_meetings":1,"after_hours_private":1}',
            'May be friends',ARRAY[]::text[],ARRAY[]::text[])""",(case,))
    url = f"/api/cases/{case}/graph?mode=observed_plus_inferred&include=observed,inferred"
    fallback = client.get(url).json()
    assert fallback["graph_source"] == "postgresql_fallback"
    def filtered_neo(case_id):
        with connect() as conn:
            nodes,edges = graph.postgres_graph(conn,case_id)
        return nodes,[edge for edge in edges if edge["kind"] == "observed"]
    monkeypatch.setattr(graph,"neo_graph",filtered_neo)
    projected = client.get(url).json()
    assert projected["graph_source"] == "neo4j_reconciled"
    assert any("restored 0 people and 1 positive-strength ties" in warning for warning in projected["warnings"])
    for key in ("nodes","edges","counts","truncated"):
        assert projected[key] == fallback[key]
    assert projected["counts"]["total_edges"] == 3


def test_review_appends_immutable_audit_with_verified_actor(api,monkeypatch):
    client,case,_,connect = api
    result = client.post(f"/api/cases/{case}/analysis",json={}).json()
    run_id = result["run"]["analysis_run_id"]
    row = result["predicted_links"][0]
    # Keep review mutations in one rolled-back transaction, preserving the append-only audit.
    with connect() as conn:
        @contextmanager
        def review_connection():
            yield conn
        monkeypatch.setattr(analysis,"connect",review_connection)
        path = f"/api/cases/{case}/predicted_links/{run_id}/{row['person_a']}/{row['person_b']}/review"
        for status in ("confirmed","dismissed"):
            response = client.post(path,json={"status":status,"reason":"Checked supporting records"})
            assert response.status_code == 200,response.text
        audits = conn.execute("SELECT * FROM inv.predicted_link_reviews WHERE case_id=%s ORDER BY review_id",(case,)).fetchall()
        assert [a["status"] for a in audits] == ["confirmed","dismissed"]
        assert all(a["reviewed_by"] == "verified-reviewer" for a in audits)
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute("DELETE FROM inv.predicted_link_reviews WHERE case_id=%s",(case,))
        conn.rollback()
