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

# Scores are only comparable within one method, so lists are ordered by method first, then score.
METHOD_ORDER = ["tie_without_recorded_communication", "hidden_link_ranker",
                "network_proximity_ppr", "network_proximity_adamic_adar"]
METHOD_BASIS = {
    "tie_without_recorded_communication": ("evidence", "Linked by direct evidence (meeting, co-location or another tie) but no recorded communication"),
    "hidden_link_ranker": ("structural_pattern", "Network structure resembles hidden links in real covert networks; a ranking, not a probability"),
    "network_proximity_ppr": ("structural_pattern", "Close in the network (personalised PageRank fallback); a ranking, not a probability"),
    "network_proximity_adamic_adar": ("structural_pattern", "Many shared contacts (Adamic-Adar fallback); a ranking, not a probability"),
}
METHOD_SQL = "array_position(ARRAY['" + "','".join(METHOD_ORDER) + "']::text[], method)"


def annotate_links(rows):
    """Add rank within method, basis and a plain explanation. Scores are never presented as probabilities."""
    ranks = {}
    for row in rows:
        ranks[row["method"]] = ranks.get(row["method"], 0) + 1
        basis, note = METHOD_BASIS.get(row["method"], ("structural_pattern", "Model suggestion; a ranking, not a probability"))
        row["rank_in_method"] = ranks[row["method"]]
        row["basis"] = basis
        row["basis_note"] = note
    return rows
WEIGHTS_PATH = Path(__file__).resolve().parents[3] / "analysis_model" / "weights" / "v1_2.json"


class AnalysisRequest(BaseModel):
    mode: Literal["observed_only", "observed_plus_inferred"] = "observed_only"
    weights_version: Literal["v1.2"] = "v1.2"


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


@router.get("/analysis/compare")
def compare_runs(case_id: str, run_a: UUID, run_b: UUID, top: int = Query(10, ge=1, le=50)):
    """What changes between two runs (e.g. observed_only vs observed_plus_inferred)."""
    with connect() as conn:
        require_case(case_id, conn)
        runs = {k: get_run(conn, case_id, rid) for k, rid in (("a", run_a), ("b", run_b))}
        for r in runs.values():
            if r["status"] not in {"completed", "partial"}:
                raise HTTPException(422, "Both runs need completed results")
        m = {k: {row["person_id"]: row for row in conn.execute(
                "SELECT * FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s", (case_id, r["analysis_run_id"])).fetchall()}
             for k, r in runs.items()}
        l = {k: {(row["person_a"], row["person_b"], row["method"]): row for row in conn.execute(
                "SELECT * FROM inv.predicted_links WHERE case_id=%s AND analysis_run_id=%s", (case_id, r["analysis_run_id"])).fetchall()}
             for k, r in runs.items()}
        names = {row["person_id"]: row["display_name"] for row in conn.execute(
            "SELECT person_id,display_name FROM inv.persons WHERE case_id=%s", (case_id,)).fetchall()}

    def ranks(metrics):
        order = sorted(metrics.values(), key=lambda r: (-(r["pagerank"] or 0), r["person_id"]))
        return {r["person_id"]: i + 1 for i, r in enumerate(order)}
    ra, rb = ranks(m["a"]), ranks(m["b"])
    # Community numbers are arbitrary labels in each run. Match each run-A community to the run-B community it overlaps most,
    # and count a person as moved only if they are not in that matched community (so pure relabelling is not a change).
    def groups(metrics):
        g = {}
        for pid, row in metrics.items():
            if row["community_id"] is not None:
                g.setdefault(row["community_id"], set()).add(pid)
        return g
    ga, gb = groups(m["a"]), groups(m["b"])
    match = {ca: max(gb, key=lambda cb: (len(members & gb[cb]), str(cb))) if gb else None for ca, members in ga.items()}
    moved = {p for p in set(m["a"]) & set(m["b"])
             if m["a"][p]["community_id"] is not None and match.get(m["a"][p]["community_id"]) != m["b"][p]["community_id"]}
    movers = sorted(({"person_id": p, "display_name": names.get(p), "pagerank_rank_a": ra.get(p), "pagerank_rank_b": rb.get(p),
                      "rank_change": ra[p] - rb[p],
                      "community_a": m["a"][p]["community_id"], "community_b": m["b"][p]["community_id"],
                      "community_moved": p in moved,
                      "hub_a": m["a"][p]["hub_flag"], "hub_b": m["b"][p]["hub_flag"]}
                     for p in set(ra) & set(rb)), key=lambda r: (-abs(r["rank_change"]), r["person_id"]))
    movers = [r for r in movers if r["rank_change"] != 0 or r["community_moved"] or r["hub_a"] != r["hub_b"]]

    def link_view(keys, src):
        rows = sorted((src[k] for k in keys), key=lambda r: (METHOD_ORDER.index(r["method"]) if r["method"] in METHOD_ORDER else 99, -r["score"]))
        return [{"person_a": r["person_a"], "person_b": r["person_b"], "names": [names.get(r["person_a"]), names.get(r["person_b"])],
                 "method": r["method"], "score": r["score"]} for r in rows]
    return json_safe({
        "run_a": {"analysis_run_id": run_a, "mode": runs["a"]["mode"], "weights_version": runs["a"]["weights_version"]},
        "run_b": {"analysis_run_id": run_b, "mode": runs["b"]["mode"], "weights_version": runs["b"]["weights_version"]},
        "biggest_rank_changes": movers[:top],
        "community_changes": len(moved),
        "hub_changes": [r for r in movers if r["hub_a"] != r["hub_b"]],
        "links_only_in_b": link_view(set(l["b"]) - set(l["a"]), l["b"])[:top * 5],
        "links_only_in_a": link_view(set(l["a"]) - set(l["b"]), l["a"])[:top * 5],
        "links_in_both": len(set(l["a"]) & set(l["b"])),
        "note": "Community labels are recomputed per run, so a label change alone may not mean a real regrouping.",
    })


@router.get("/analysis/{run_id}")
def analysis_detail(case_id: str, run_id: UUID):
    with connect() as conn:
        require_case(case_id, conn)
        run = get_run(conn,case_id,run_id)
        metrics = conn.execute("SELECT * FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s ORDER BY pagerank DESC NULLS LAST,person_id", (case_id,run_id)).fetchall()
        links = conn.execute(f"""SELECT l.*, pa.display_name person_a_name, pb.display_name person_b_name
          FROM inv.predicted_links l
          JOIN inv.persons pa ON pa.case_id=l.case_id AND pa.person_id=l.person_a
          JOIN inv.persons pb ON pb.case_id=l.case_id AND pb.person_id=l.person_b
          WHERE l.case_id=%s AND l.analysis_run_id=%s
          ORDER BY {METHOD_SQL} NULLS LAST,method,score DESC,person_a,person_b""", (case_id,run_id)).fetchall()
    links = annotate_links(links)
    by_method = {}
    for row in links:
        by_method.setdefault(row["method"], []).append(row)
    return json_safe({"run": run, "person_metrics": metrics, "predicted_links": links,
                      "predicted_links_by_method": by_method,
                      "score_note": "Scores rank pairs within one method; they are not probabilities and are not comparable across methods."})


@router.get("/analysis/{run_id}/predicted_links")
def list_predicted_links(case_id: str, run_id: UUID, method: str | None = None,
                         basis: Literal["evidence", "structural_pattern"] | None = None,
                         person_id: str | None = None,
                         limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    methods = None
    if method:
        methods = [method]
    elif basis:
        methods = [k for k, (b, _) in METHOD_BASIS.items() if b == basis]
    where, params = ["case_id=%s", "analysis_run_id=%s"], [case_id, run_id]
    if methods is not None:
        where.append("method = ANY(%s)"); params.append(methods)
    if person_id:
        where.append("(person_a=%s OR person_b=%s)"); params += [person_id, person_id]
    with connect() as conn:
        require_case(case_id, conn)
        get_run(conn, case_id, run_id)
        total = conn.execute(f"SELECT count(*) n FROM inv.predicted_links WHERE {' AND '.join(where)}", params).fetchone()["n"]
        # rank_in_method must be global within the method, so compute it in SQL before paging.
        rows = conn.execute(f"""SELECT y.*, pa.display_name person_a_name, pb.display_name person_b_name FROM (
              SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY method ORDER BY score DESC,person_a,person_b) rank_in_method
                FROM inv.predicted_links WHERE case_id=%s AND analysis_run_id=%s) x
              WHERE {' AND '.join(where)} ORDER BY {METHOD_SQL} NULLS LAST,method,score DESC,person_a,person_b LIMIT %s OFFSET %s) y
            JOIN inv.persons pa ON pa.case_id=y.case_id AND pa.person_id=y.person_a
            JOIN inv.persons pb ON pb.case_id=y.case_id AND pb.person_id=y.person_b
            ORDER BY {METHOD_SQL} NULLS LAST,y.method,y.score DESC,y.person_a,y.person_b""",
            [case_id, run_id] + params + [limit, offset]).fetchall()
    for row in rows:
        b, note = METHOD_BASIS.get(row["method"], ("structural_pattern", "Model suggestion; a ranking, not a probability"))
        row["basis"], row["basis_note"] = b, note
    return json_safe({"items": rows, "total": total, "limit": limit, "offset": offset,
                      "score_note": "Scores rank pairs within one method; they are not probabilities."})


@router.get("/persons/{person_id}/explain")
def explain_person(case_id: str, person_id: str, run_id: UUID | None = None,
                   mode: Literal["observed_only", "observed_plus_inferred"] = "observed_plus_inferred"):
    """Why this person ranks where they do in an analysis run, in plain terms with supporting numbers."""
    with connect() as conn:
        require_case(case_id, conn)
        person = conn.execute("SELECT person_id,display_name,department,job_title FROM inv.persons WHERE case_id=%s AND person_id=%s",
                              (case_id, person_id)).fetchone()
        if person is None:
            raise HTTPException(404, "Person not found")
        if run_id:
            run = get_run(conn, case_id, run_id)
        else:
            run = conn.execute("""SELECT * FROM inv.analysis_runs WHERE case_id=%s AND mode=%s AND status IN ('completed','partial')
                ORDER BY started_at DESC,analysis_run_id DESC LIMIT 1""", (case_id, mode)).fetchone()
            if run is None:
                raise HTTPException(404, "No completed analysis run for this case and mode; run POST /analysis first")
        if run["status"] not in {"completed", "partial"}:
            raise HTTPException(422, "Analysis run has no completed results")
        rid = run["analysis_run_id"]
        metrics = conn.execute("SELECT * FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s", (case_id, rid)).fetchall()
        links = conn.execute(f"""SELECT * FROM inv.predicted_links WHERE case_id=%s AND analysis_run_id=%s AND (person_a=%s OR person_b=%s)
            ORDER BY {METHOD_SQL} NULLS LAST,score DESC""", (case_id, rid, person_id, person_id)).fetchall()
        names = {r["person_id"]: r["display_name"] for r in conn.execute(
            "SELECT person_id,display_name FROM inv.persons WHERE case_id=%s", (case_id,)).fetchall()}
        persons_df, edges_df = load_inputs(conn, case_id, run["mode"])
    me = next((m for m in metrics if m["person_id"] == person_id), None)
    if me is None:
        raise HTTPException(404, "Person has no metrics in this run")
    n = len(metrics)

    def rank_of(key):
        vals = sorted(((m[key] or 0) for m in metrics), reverse=True)
        return vals.index(me[key] or 0) + 1
    ranks = {k: rank_of(k) for k in ("pagerank", "betweenness", "degree", "weighted_degree")}
    group = [m["person_id"] for m in metrics if me["community_id"] is not None and m["community_id"] == me["community_id"]]

    # Strongest ties, using the model's own edge-strength rules for this run's weights.
    from analysis_model.run_case_analysis import _edge_strength
    weights = json.loads(WEIGHTS_PATH.read_bytes())
    st = _edge_strength(persons_df, edges_df, weights, [])
    st = st[((st.a == person_id) | (st.b == person_id)) & (st.strength > 0)]
    ties = {}
    for row in st.itertuples(index=False):
        other = row.b if row.a == person_id else row.a
        t = ties.setdefault(other, {"person_id": other, "display_name": names.get(other), "strength": 0.0, "types": set(), "inferred": False})
        t["strength"] += float(row.strength)
        t["types"].add(row.type)
        t["inferred"] |= bool(row.is_inferred)
    top_ties = sorted(ties.values(), key=lambda t: (-t["strength"], t["person_id"]))[:8]
    for t in top_ties:
        t["types"] = sorted(t["types"])
        t["strength"] = round(t["strength"], 4)

    reasons = []
    def pct(r): return f"top {max(1, round(100 * r / n))}%"
    reasons.append(f"Influence (PageRank) rank {ranks['pagerank']} of {n} ({pct(ranks['pagerank'])}).")
    reasons.append(f"Bridge between groups (betweenness) rank {ranks['betweenness']} of {n}.")
    reasons.append(f"{int(me['degree'] or 0)} direct connections (rank {ranks['degree']}); strongest: "
                   + (", ".join(f"{t['display_name'] or t['person_id']}" for t in top_ties[:3]) or "none") + ".")
    if me["community_id"]:
        reasons.append(f"Belongs to group {me['community_id']} with {len(group) - 1} others (a group of people who interact closely, not a verified gang).")
    if me["hub_flag"]:
        reasons.append("Flagged as a hub: unusually many contacts. Check whether this is a real role or a mass-contact artefact (e.g. broadcast emails).")
    ev = [l for l in links if METHOD_BASIS.get(l["method"], ("",))[0] == "evidence"]
    if ev:
        reasons.append(f"Appears in {len(ev)} evidence-based lead(s): linked by direct evidence but no recorded communication.")
    for i, l in enumerate(links):
        l["other_person"] = l["person_b"] if l["person_a"] == person_id else l["person_a"]
        l["other_name"] = names.get(l["other_person"])
        l["basis"] = METHOD_BASIS.get(l["method"], ("structural_pattern", ""))[0]
    return json_safe({
        "person": person, "run": {"analysis_run_id": rid, "mode": run["mode"], "weights_version": run["weights_version"], "status": run["status"]},
        "metrics": me, "ranks": ranks, "people_in_case": n,
        "community": {"community_id": me["community_id"], "size": len(group),
                      "members": [{"person_id": p, "display_name": names.get(p)} for p in group][:25]},
        "top_ties": top_ties, "suggested_links": links, "reasons": reasons,
        "note": "Network position describes how connected someone is in the recorded evidence. It is not evidence of guilt.",
        "ties_note": "Scores and ranks are the saved results of this run. Strongest ties are recomputed from the case's current evidence "
                     "with the same weights, so they can differ if evidence was added to the case after the run.",
    })


@router.post("/predicted_links/{run_id}/{a}/{b}/review")
def review_prediction(case_id: str, run_id: UUID, a: str, b: str, body: ReviewRequest, request: Request):
    principal = getattr(request.state,"principal",None)
    if principal is None:
        raise HTTPException(401,"Authentication required")
    actor = "local" if principal.local else principal.user_id
    if body.status == "dismissed":
        request.state.audit_action = "dismiss_lead"
    a,b = sorted((a,b))
    with connect() as conn:
        get_run(conn,case_id,run_id)
        rows = conn.execute("""UPDATE inv.predicted_links SET review_status=%s,review_reason=%s,reviewed_by=%s,reviewed_at=now()
          WHERE case_id=%s AND analysis_run_id=%s AND person_a=%s AND person_b=%s RETURNING *""", (body.status,body.reason,actor,case_id,run_id,a,b)).fetchall()
        if not rows:
            raise HTTPException(404,"This pair is not a suggested link in the selected analysis run. Open it from Leads & Predictions for the current run.")
        for row in rows:
            conn.execute("""INSERT INTO inv.predicted_link_reviews
              (case_id,analysis_run_id,person_a,person_b,method,status,reason,reviewed_by)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (case_id,run_id,a,b,row["method"],body.status,body.reason,actor))
    return json_safe({"reviews":rows})


@router.get("/predicted_links/{run_id}/{a}/{b}/reviews")
def prediction_reviews(case_id: str, run_id: UUID, a: str, b: str):
    """Review history for one suggested link (newest first)."""
    a, b = sorted((a, b))
    with connect() as conn:
        get_run(conn, case_id, run_id)
        rows = conn.execute("""SELECT r.review_id, r.case_id, r.analysis_run_id, r.person_a, r.person_b, r.method, r.status, r.reason,
                   r.reviewed_at, COALESCE(u.email, r.reviewed_by) AS reviewed_by
            FROM inv.predicted_link_reviews r
            LEFT JOIN inv.app_users u ON u.user_id::text = r.reviewed_by
            WHERE r.case_id=%s AND r.analysis_run_id=%s AND r.person_a=%s AND r.person_b=%s
            ORDER BY r.reviewed_at DESC""", (case_id, run_id, a, b)).fetchall()
    return json_safe(rows)


@router.get("/analysis/{run_id}/strongest_ties")
def strongest_ties(case_id: str, run_id: UUID, limit: int = Query(15, ge=1, le=100)):
    """Pairs with the strongest combined evidence in this run (calls + money + meetings + recorded ties), using the
    model's own edge-strength rules. Complements the leads, which only cover pairs with NO recorded communication."""
    with connect() as conn:
        run = get_run(conn, case_id, run_id)
        names = {r["person_id"]: r["display_name"] for r in conn.execute(
            "SELECT person_id,display_name FROM inv.persons WHERE case_id=%s", (case_id,)).fetchall()}
        persons_df, edges_df = load_inputs(conn, case_id, run["mode"])
    from analysis_model.run_case_analysis import _edge_strength
    weights = json.loads(WEIGHTS_PATH.read_bytes())
    st = _edge_strength(persons_df, edges_df, weights, [])
    st = st[st.strength > 0]
    comm_types = {t.upper() for t in weights.get("communication_types", [])}
    pairs = {}
    for r in st.itertuples(index=False):
        p = pairs.setdefault((r.a, r.b), {"person_a": r.a, "person_b": r.b, "strength": 0.0, "types": set(), "sources": set(),
                                          "inferred": False})
        p["strength"] += float(r.strength)
        p["types"].add(r.type)
        kind = "communication" if r.type.upper() in comm_types else ("money" if r.type.upper() == "BUSINESS&FINANCE" else
                ("location" if r.is_inferred else "recorded tie"))
        p["sources"].add(kind)
        p["inferred"] = p["inferred"] or bool(r.is_inferred)
    rows = sorted(pairs.values(), key=lambda p: (-len(p["sources"]), -p["strength"], p["person_a"], p["person_b"]))[:limit]
    for p in rows:
        p.update(name_a=names.get(p["person_a"]), name_b=names.get(p["person_b"]), strength=round(p["strength"], 3),
                 types=sorted(p["types"]), sources=sorted(p["sources"]), corroboration=len(p["sources"]))
    return json_safe({"items": rows, "run": {"analysis_run_id": run["analysis_run_id"], "mode": run["mode"]},
                      "note": "Sorted by how many independent kinds of evidence link the pair, then by combined strength. "
                              "Strong evidence of contact is not evidence of wrongdoing."})
