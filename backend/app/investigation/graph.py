"""A bounded display graph; analysis always uses the complete canonical case."""
import json
import math
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.db.neo4j import get_driver
from .analysis import METHOD_BASIS, METHOD_ORDER, WEIGHTS_PATH, get_run, load_inputs
from .common import connect, json_safe, require_case
from analysis_model.run_case_analysis import _edge_strength

router = APIRouter(prefix="/api/cases/{case_id}", tags=["graph"])


def neo_graph(case_id):
    with get_driver().session(database=settings.neo4j_database) as session:
        snapshot = session.run("MATCH (c:InvCase {case_id:$case_id}) RETURN c.active_snapshot_id AS snapshot_id",case_id=case_id).single()
        if not snapshot or not snapshot["snapshot_id"]:
            raise RuntimeError("No active Neo4j case snapshot")
        params = {"case_id":case_id,"snapshot_id":snapshot["snapshot_id"]}
        nodes = [dict(row) for row in session.run("""MATCH (p:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id})
            RETURN p.person_id AS id,p.label AS label,p.department AS department""",**params)]
        edges = [dict(row) for row in session.run("""MATCH
            (a:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id})-[r:INV_LINK {case_id:$case_id,snapshot_id:$snapshot_id}]->
            (b:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id})
            RETURN r.edge_id AS id,a.person_id AS source,b.person_id AS target,
              r.kind AS kind,r.is_inferred AS is_inferred,r.relationship_type AS type,
              r.weight AS weight,r.attributes_json AS attributes_json""",**params)]
    for edge in edges:
        attrs = edge.pop("attributes_json",None)
        if isinstance(attrs,str):
            attrs = json.loads(attrs)
        edge["lead_strength"] = (attrs or {}).get("lead_strength")
        edge["kind"] = "inferred" if edge.pop("is_inferred",False) else (edge.get("kind") or "observed")
    return nodes,edges


def postgres_graph(conn, case_id):
    nodes = conn.execute("SELECT person_id id,display_name label,department FROM inv.persons WHERE case_id=%s ORDER BY person_id",(case_id,)).fetchall()
    edges = conn.execute("""SELECT person_a source,person_b target,relationship_type type,weight,
        CASE WHEN is_inferred THEN 'inferred' ELSE 'observed' END kind,
        CASE WHEN is_inferred THEN weight*100 ELSE NULL END lead_strength
        FROM inv.case_graph_edges WHERE case_id=%s ORDER BY person_a,person_b,relationship_type,is_inferred""",(case_id,)).fetchall()
    return nodes,edges


def compact_graph(nodes, edges, metrics, include, mode, limit, edge_limit, focus):
    """Stable ranking, full-network counts, and no dangling display edges."""
    by_id = {row["id"]:dict(row) for row in nodes}
    if focus is not None and focus not in by_id:
        raise HTTPException(404,"Person not found")
    allowed = set(include)
    if mode == "observed_only":
        allowed.discard("inferred")
    valid = []
    degree = dict.fromkeys(by_id,0)
    strength = dict.fromkeys(by_id,0.0)
    neighbours = {pid:set() for pid in by_id}
    for item in edges:
        edge = dict(item)
        weight = edge.get("weight")
        a,b = edge["source"],edge["target"]
        if (edge.get("kind") not in allowed or a not in by_id or b not in by_id or a == b
                or weight is None or not math.isfinite(float(weight)) or float(weight) <= 0):
            continue
        edge["id"] = edge.get("id") or ":".join((edge["kind"],a,b,edge["type"],edge.get("method", "")))
        edge.setdefault("lead_strength",None)
        valid.append(edge)
        for pid,other in ((a,b),(b,a)):
            if edge["kind"] != "predicted":   # suggestions aren't evidence; don't let them inflate a person's strength
                strength[pid] += float(weight)
            neighbours[pid].add(other)
    for pid in by_id:
        degree[pid] = len(neighbours[pid])
        metric = metrics.get(pid,{})
        by_id[pid].update({key:metric.get(key) for key in ("pagerank","betweenness","community_id","hub_flag")})
        by_id[pid]["degree"] = metric.get("degree",degree[pid])
    def rank(pid):
        score = metrics.get(pid,{}).get("pagerank")
        return (-(float(score) if score is not None else strength[pid]),pid)
    ordered = sorted(by_id,key=rank)
    if focus is not None:
        ordered = [focus] + sorted(neighbours[focus],key=rank) + [pid for pid in ordered if pid != focus and pid not in neighbours[focus]]
    selected = ordered[:limit]
    selected_ids = set(selected)
    visible = [edge for edge in valid if edge["source"] in selected_ids and edge["target"] in selected_ids]
    # Strengths of different kinds aren't on one scale (prediction scores are rankings within a method),
    # so inferred and predicted edges get reserved shares of edge_limit instead of competing with
    # observed strength. Unused share flows back to the others.
    # In a focused view the focused person's own links come first, so the budget never hides them.
    own = (lambda e: 0 if focus in (e["source"], e["target"]) else 1) if focus is not None else (lambda e: 0)
    tie = lambda edge:(edge["source"],edge["target"],edge["kind"],edge["type"],edge["id"])
    groups = {
        "observed": sorted((e for e in visible if e["kind"] == "observed"),key=lambda e:(own(e),-float(e["weight"]),*tie(e))),
        "inferred": sorted((e for e in visible if e["kind"] == "inferred"),key=lambda e:(own(e),-float(e["weight"]),*tie(e))),
        "predicted": sorted((e for e in visible if e["kind"] == "predicted"),
                            key=lambda e:(own(e),METHOD_ORDER.index(e["type"]) if e["type"] in METHOD_ORDER else 99,-float(e["weight"]),*tie(e))),
    }
    share = {"inferred":edge_limit//4,"predicted":edge_limit//3}
    take = {k:min(len(groups[k]),max(1,share[k]) if groups[k] else 0) for k in share}
    take["observed"] = min(len(groups["observed"]),edge_limit-sum(take.values()))
    spare = edge_limit-sum(take.values())
    for k in ("observed","inferred","predicted"):
        extra = min(spare,len(groups[k])-take[k])
        take[k] += extra; spare -= extra
    visible = groups["observed"][:take["observed"]]+groups["inferred"][:take["inferred"]]+groups["predicted"][:take["predicted"]]
    return {"nodes":[by_id[pid] for pid in selected],"edges":visible,
            "counts":{"total_nodes":len(by_id),"total_edges":len(valid),"shown_nodes":len(selected),"shown_edges":len(visible)},
            "shown_by_kind":{k:sum(1 for e in visible if e["kind"]==k) for k in ("observed","inferred","predicted")},
            "truncated":len(selected)<len(by_id) or len(visible)<len(valid)}


@router.get("/graph")
def graph(case_id: str, run_id: UUID | None = None,
          mode: Literal["observed_only","observed_plus_inferred"] | None = None,
          include: str = "observed,inferred", limit: int = Query(25,ge=1,le=100),
          edge_limit: int = Query(75,ge=1,le=300), focus: str | None = None):
    kinds = set(include.split(","))
    if not kinds or not kinds <= {"observed","inferred","predicted"}:
        raise HTTPException(422,"include must contain observed, inferred, or predicted")
    warnings = []
    with connect() as conn:
        require_case(case_id,conn)
        if run_id:
            run = get_run(conn,case_id,run_id)
            mode = mode or run["mode"]          # a run carries its own mode; no need to repeat it
        else:
            mode = mode or "observed_only"
            run = conn.execute("""SELECT * FROM inv.analysis_runs
            WHERE case_id=%s AND mode=%s AND status IN ('completed','partial')
            ORDER BY started_at DESC,analysis_run_id DESC LIMIT 1""",(case_id,mode)).fetchone()
        if run and run["mode"] != mode:
            raise HTTPException(422,"Analysis run mode does not match graph mode")
        if run and run["status"] not in {"completed","partial"}:
            raise HTTPException(422,"Analysis run has no completed results")
        run_id = run["analysis_run_id"] if run else None
        metrics = {}
        if run:
            metrics = {row["person_id"]:row for row in conn.execute("SELECT * FROM inv.person_metrics WHERE case_id=%s AND analysis_run_id=%s",(case_id,run_id)).fetchall()}
            warnings.extend(run["parameters"].get("warnings",[]))
            if run["status"] == "partial":
                warnings.append("Analysis is partial; see the run's stage errors.")
        # Use the model's own strength rules so broadcasts and discounted ties match the analysed network.
        persons,inputs = load_inputs(conn,case_id,mode)
        strengths = _edge_strength(persons,inputs,json.loads(WEIGHTS_PATH.read_bytes()),warnings)
        by_tie = {(row.a,row.b,row.type,"inferred" if row.is_inferred else "observed"):row.strength
                  for row in strengths.itertuples(index=False)}
        nodes,edges = postgres_graph(conn,case_id)
        for edge in edges:
            a,b = sorted((edge["source"],edge["target"]))
            edge["weight"] = by_tie.get((a,b,edge["type"],edge["kind"]),0)
        try:
            neo_nodes,neo_edges = neo_graph(case_id)
            canonical_nodes = {node["id"] for node in nodes}
            projected_nodes = {node["id"] for node in neo_nodes}
            projected_ties = {(*sorted((edge["source"],edge["target"])),edge["type"],edge["kind"])
                              for edge in neo_edges}
            positive_ties = {tie for tie,strength in by_tie.items() if strength > 0}
            missing_nodes = canonical_nodes - projected_nodes
            missing_ties = positive_ties - projected_ties
            # Canonical topology keeps filtered Neo4j projections from hiding model-positive evidence.
            if missing_nodes or missing_ties or projected_nodes - canonical_nodes:
                source = "neo4j_reconciled"
                warnings.append(f"Neo4j's active snapshot was reconciled with PostgreSQL: restored {len(missing_nodes)} people and {len(missing_ties)} positive-strength ties.")
            else:
                source = "neo4j"
        except Exception:
            source = "postgresql_fallback"
            warnings.append("Neo4j is unavailable or has no active case snapshot; showing the canonical PostgreSQL graph.")
        if run and "predicted" in kinds:
            rows = conn.execute("""SELECT person_a source,person_b target,method,score weight
                FROM inv.predicted_links WHERE case_id=%s AND analysis_run_id=%s AND review_status<>'dismissed'
                ORDER BY person_a,person_b,method""",(case_id,run_id)).fetchall()
            for row in rows:
                basis = METHOD_BASIS.get(row["method"],("structural_pattern",""))[0]
                edges.append({**row,"kind":"predicted","type":row["method"],"basis":basis,"lead_strength":None})
    result = compact_graph(nodes,edges,metrics,kinds,mode,limit,edge_limit,focus)
    result.update({"case_id":case_id,"run_id":run_id,"mode":mode,"graph_source":source,
                   "warnings":list(dict.fromkeys(warnings))})
    return json_safe(result)
