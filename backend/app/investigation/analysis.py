"""Case-scoped adapter for the versioned, database-free analysis model."""
import hashlib
import json
import math
from pathlib import Path
from typing import Literal
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .common import connect, json_safe, require_case
from analysis_model.run_case_analysis import run_case_analysis

router = APIRouter(prefix="/api/cases/{case_id}", tags=["analysis"])
WEIGHTS_PATH = Path(__file__).resolve().parents[3] / "analysis_model" / "weights" / "v1_1.json"


class AnalysisRequest(BaseModel):
    mode: Literal["observed_only", "observed_plus_inferred"] = "observed_only"
    weights_version: Literal["v1.1"] = "v1.1"


class ReviewRequest(BaseModel):
    status: Literal["confirmed", "dismissed"]
    reason: str = Field(default="", max_length=2000)


def load_inputs(conn, case_id, mode):
    people = conn.execute("SELECT person_id, display_name, department FROM inv.persons WHERE case_id=%s ORDER BY person_id", (case_id,)).fetchall()
    edges = conn.execute("""
        WITH mail AS (
          SELECT LEAST(source_person_id,target_person_id) a,
                 GREATEST(source_person_id,target_person_id) b,
                 count(*) email_events, count(*) FILTER (WHERE NOT is_broadcast) direct_email_events,
                 array_agg(communication_id ORDER BY communication_id) refs
          FROM inv.communication_events WHERE case_id=%s GROUP BY 1,2)
        SELECT r.person_a,r.person_b,r.relationship_type,FALSE is_inferred,r.weight,
          CASE WHEN m.a IS NULL THEN NULL ELSE jsonb_build_object(
            'email_events',m.email_events,'direct_email_events',m.direct_email_events) END factors,
          COALESCE(m.refs,ARRAY[]::text[]) evidence_refs
        FROM inv.relationships r LEFT JOIN mail m ON r.relationship_type='EMAILED'
          AND m.a=r.person_a AND m.b=r.person_b
        WHERE r.case_id=%s ORDER BY r.person_a,r.person_b,r.relationship_type
        """, (case_id, case_id)).fetchall()
    if mode == "observed_plus_inferred":
        edges += conn.execute("""SELECT person_a,person_b,relationship_type,TRUE is_inferred,
            lead_strength/100.0 weight,
            factors || jsonb_build_object('supporting_colocation_ids',supporting_colocation_ids) factors,
            supporting_colocation_ids evidence_refs FROM inv.inferred_relationships
            WHERE case_id=%s AND relationship_type<>'WORKPLACE_ONLY'
            ORDER BY person_a,person_b""", (case_id,)).fetchall()
    return (pd.DataFrame(people, columns=["person_id", "display_name", "department"]),
            pd.DataFrame(edges, columns=["person_a", "person_b", "relationship_type", "is_inferred", "weight", "factors", "evidence_refs"]))


def validate_output(output, person_ids, evidence_ids=None):
    """Reject invalid references and numbers before opening the results transaction."""
    if output.get("status") not in {"ok", "partial", "failed"}:
        raise ValueError("Unknown model status")
    stages = output["stages"]
    expected = {"validate_input", "edge_strength", "graph", "centrality", "communities", "link_prediction"}
    if set(stages) != expected or any(stage.get("status") not in {"ok","failed","skipped"} for stage in stages.values()):
        raise ValueError("Invalid model stages")
    critical_failed = any(stages[name]["status"] != "ok" for name in ("validate_input","edge_strength","graph"))
    all_ok = all(stage["status"] == "ok" for stage in stages.values())
    expected_status = "failed" if critical_failed else ("ok" if all_ok else "partial")
    if output["status"] != expected_status:
        raise ValueError("Model status contradicts stage results")
    metrics = output["person_metrics"].to_dict("records")
    links = output["predicted_links"].to_dict("records")
    seen = set()
    for row in metrics:
        pid = row["person_id"]
        if pid not in person_ids or pid in seen:
            raise ValueError("Unknown or duplicate metric person")
        seen.add(pid)
        for key in ("degree", "weighted_degree", "betweenness", "pagerank"):
            value = row.get(key)
            if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
                raise ValueError("Invalid metric number")
        community = json_safe(row.get("community_id"))
        if community is None or pd.isna(community):
            row["community_id"] = None
        elif isinstance(community,str):
            row["community_id"] = community
        else:
            raise ValueError("Invalid community identifier")
    if output["status"] != "failed" and seen != person_ids:
        raise ValueError("Missing person metrics")
    seen = set()
    for row in links:
        a, b = sorted((row["person_a"], row["person_b"]))
        if not isinstance(row["method"],str) or not row["method"] or not isinstance(row["factor_breakdown"],dict):
            raise ValueError("Invalid prediction method or factor breakdown")
        key = (a, b, row["method"])
        if a == b or a not in person_ids or b not in person_ids or key in seen:
            raise ValueError("Unknown or duplicate predicted pair")
        if not math.isfinite(float(row["score"])) or row["score"] < 0:
            raise ValueError("Invalid prediction score")
        # JSON serialization also rejects nested nonfinite factor values.
        json.dumps(row["factor_breakdown"], allow_nan=False)
        if not isinstance(row["evidence_refs"], list) or not all(isinstance(x, str) for x in row["evidence_refs"]):
            raise ValueError("Invalid evidence references")
        if evidence_ids is not None and not set(row["evidence_refs"]) <= evidence_ids:
            raise ValueError("Unknown evidence reference")
        row["person_a"], row["person_b"] = a, b
        seen.add(key)
    return metrics, links


def get_run(conn, case_id, run_id):
    row = conn.execute("SELECT * FROM inv.analysis_runs WHERE case_id=%s AND analysis_run_id=%s", (case_id, run_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Analysis run not found")
    return row


@router.post("/analysis")
def create_analysis(case_id: str, body: AnalysisRequest):
    raw = WEIGHTS_PATH.read_bytes()
    weights = json.loads(raw)
    parameters = {"weights_sha256": hashlib.sha256(raw).hexdigest(), "weights_version": weights["version"],
                  "algorithm": "analysis_model.run_case_analysis", "execution": "synchronous_worker_thread",
                  "algorithm_sha256": hashlib.sha256((WEIGHTS_PATH.parent.parent / "run_case_analysis.py").read_bytes()).hexdigest()}
    with connect() as conn:
        require_case(case_id, conn)
        run = conn.execute("""INSERT INTO inv.analysis_runs
          (case_id,mode,weights_version,algorithm,parameters,status) VALUES (%s,%s,%s,%s,%s,'running') RETURNING *""",
          (case_id, body.mode, weights["version"], parameters["algorithm"], Jsonb(parameters))).fetchone()
    run_id = run["analysis_run_id"]
    phase = "load_inputs"
    try:
        with connect() as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            persons, edges = load_inputs(conn, case_id, body.mode)
        phase = "fingerprint_inputs"
        serialized = json.dumps({"persons": persons.to_dict("records"), "edges": edges.to_dict("records")}, sort_keys=True, separators=(",", ":"), allow_nan=False)
        parameters["input_sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
        parameters["input_counts"] = {"persons": len(persons), "edges": len(edges)}
        phase = "model"
        output = run_case_analysis(persons, edges, body.mode, weights)
        parameters.update({"stages": output["stages"], "warnings": output["warnings"], "model_status": output["status"]})
        refs = {ref for row in edges.to_dict("records") for ref in (row.get("evidence_refs") or [])}
        phase = "validate_output"
        metrics, links = validate_output(output, set(persons.person_id), refs)
        status = {"ok": "completed", "partial": "partial", "failed": "failed"}[output["status"]]
        errors = [f"{name}: {stage['error']}" for name, stage in output["stages"].items() if stage.get("error")]
        phase = "persist_results"
        with connect() as conn:
            if status != "failed":
                with conn.cursor() as cursor:
                    cursor.executemany("""INSERT INTO inv.person_metrics
                      (case_id,analysis_run_id,person_id,degree,weighted_degree,betweenness,pagerank,community_id,hub_flag)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      [(case_id,run_id,row["person_id"],row.get("degree"),row.get("weighted_degree"),row.get("betweenness"),row.get("pagerank"),row.get("community_id"),bool(row.get("hub_flag"))) for row in metrics])
                    cursor.executemany("""INSERT INTO inv.predicted_links
                      (case_id,analysis_run_id,person_a,person_b,method,score,factor_breakdown,evidence_refs)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                      [(case_id,run_id,row["person_a"],row["person_b"],row["method"],row["score"],Jsonb(row["factor_breakdown"]),row["evidence_refs"]) for row in links])
            conn.execute("""UPDATE inv.analysis_runs SET status=%s,error=%s,parameters=%s,completed_at=now()
              WHERE case_id=%s AND analysis_run_id=%s""", (status,"; ".join(errors) or None,Jsonb(json_safe(parameters)),case_id,run_id))
    except Exception as exc:
        parameters["failure"] = {"code":"analysis_execution_failed","phase":phase,"exception_type":type(exc).__name__}
        with connect() as conn:
            conn.execute("""UPDATE inv.analysis_runs SET status='failed',error=%s,parameters=%s,completed_at=now()
              WHERE case_id=%s AND analysis_run_id=%s""", (f"Analysis failed during {phase} ({type(exc).__name__}).",Jsonb(json_safe(parameters)),case_id,run_id))
    return analysis_detail(case_id, run_id)


@router.get("/analysis")
def list_analysis(case_id: str, limit: int = Query(25, ge=1, le=100)):
    with connect() as conn:
        require_case(case_id, conn)
        rows = conn.execute("SELECT * FROM inv.analysis_runs WHERE case_id=%s ORDER BY started_at DESC,analysis_run_id DESC LIMIT %s", (case_id,limit)).fetchall()
    return json_safe(rows)


@router.get("/analysis/{run_id}")
def analysis_detail(case_id: str, run_id: UUID):
    with connect() as conn:
        require_case(case_id, conn)
        run = get_run(conn,case_id,run_id)
        metrics = conn.execute("SELECT * FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s ORDER BY pagerank DESC NULLS LAST,person_id", (case_id,run_id)).fetchall()
        links = conn.execute("SELECT * FROM inv.predicted_links WHERE case_id=%s AND analysis_run_id=%s ORDER BY score DESC,person_a,person_b,method", (case_id,run_id)).fetchall()
    return json_safe({"run": run, "person_metrics": metrics, "predicted_links": links})


@router.post("/predicted_links/{run_id}/{a}/{b}/review")
def review_prediction(case_id: str, run_id: UUID, a: str, b: str, body: ReviewRequest, request: Request):
    principal = getattr(request.state,"principal",None)
    if principal is None:
        raise HTTPException(401,"Authentication required")
    actor = "local" if principal.local else principal.user_id
    a,b = sorted((a,b))
    with connect() as conn:
        get_run(conn,case_id,run_id)
        rows = conn.execute("""UPDATE inv.predicted_links SET review_status=%s,review_reason=%s,reviewed_by=%s,reviewed_at=now()
          WHERE case_id=%s AND analysis_run_id=%s AND person_a=%s AND person_b=%s RETURNING *""", (body.status,body.reason,actor,case_id,run_id,a,b)).fetchall()
        if not rows:
            raise HTTPException(404,"Predicted link not found")
        for row in rows:
            conn.execute("""INSERT INTO inv.predicted_link_reviews
              (case_id,analysis_run_id,person_a,person_b,method,status,reason,reviewed_by)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (case_id,run_id,a,b,row["method"],body.status,body.reason,actor))
    return json_safe({"reviews":rows})
