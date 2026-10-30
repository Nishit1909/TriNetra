"""Generalisation stress test (public function 7).

Runs the *entire* pipeline — projection → centrality → communities → link
prediction (heuristics + GNN + benchmark) → feature engineering → risk
scoring → ``person_metrics`` assembly — against synthetic investigation graphs
that are deliberately shaped unlike the demo case:

* ``sparse_20``          – 20 persons, very few ties, all data types present
* ``dense_500``          – 500 persons, dense ties, a planted hub that must rank #1
* ``no_timestamps_100``  – graph only: no CDR, no location events (temporal
  features must be NaN, nothing may crash)
* ``no_communication_60``– location evidence only: no COMMUNICATES_WITH edges
* ``tiny_5_no_edges``    – 5 isolated persons (GNN must skip gracefully,
  heuristics return nothing, every table still has one row per person)
* ``isolated_mix_80``    – 80 persons of which a quarter are isolated

For each scenario the report records whether it ran without raising, whether
required outputs are complete and finite, structural sanity checks (rank is
a permutation, planted hub found, one row per person), the surfaced
link-prediction method, whether the GNN trained/degraded, and timings.

This test proves the pipeline is **robust** to different data shapes; it does
not (and cannot) prove predictive accuracy on unseen real data — that needs
labelled data of the new case.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Callable, Dict, List, Optional, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from .centrality import run_centrality_analysis, run_community_detection
from .graph_utils import LOCATION, PERSON, VEHICLE, build_person_graph
from .link_prediction.benchmark import run_link_prediction
from .risk_scoring.elliptic_train import RiskModel, make_synthetic_elliptic_like_table, train_risk_model
from .risk_scoring.features import MODEL_FEATURES, engineer_case_features
from .risk_scoring.score_case import assemble_person_metrics, score_case_risk

logger = logging.getLogger(__name__)

CASE_START = pd.Timestamp("2014-01-06")
CASE_DAYS = 14


# --------------------------------------------------------------------------- #
# Synthetic scenario builders
# --------------------------------------------------------------------------- #
def _persons(n: int) -> List[str]:
    return [f"S{i:04d}" for i in range(n)]


def _graph_from(persons: List[str], comm_edges: List[Tuple[str, str]], visits: Dict[str, List[str]] | None = None) -> nx.Graph:
    g = nx.Graph()
    for p in persons:
        g.add_node(p, node_type=PERSON, name=p)
    for a, b in comm_edges:
        if a != b:
            g.add_edge(a, b, relationship_type="COMMUNICATES_WITH", count=1)
    for loc, people in (visits or {}).items():
        g.add_node(loc, node_type=LOCATION)
        for p in people:
            g.add_edge(p, loc, relationship_type="VISITED", count=1)
    return g


def _random_comm_edges(persons: List[str], avg_degree: float, rng: np.random.Generator) -> List[Tuple[str, str]]:
    n = len(persons)
    m = int(n * avg_degree / 2)
    edges = set()
    while len(edges) < m and n > 1:
        a, b = rng.integers(n), rng.integers(n)
        if a != b:
            edges.add(tuple(sorted((persons[a], persons[b]))))
    return sorted(edges)


def _synthetic_cdr(comm_edges: List[Tuple[str, str]], rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i, (a, b) in enumerate(comm_edges):
        for _ in range(int(rng.integers(1, 4))):
            t = CASE_START + pd.Timedelta(seconds=int(rng.integers(0, CASE_DAYS * 86400)))
            rows.append({"cdr_id": f"C{i}_{_}", "caller_person_id": a, "receiver_person_id": b,
                         "call_start_time": t, "call_duration_seconds": int(rng.integers(15, 1800))})
    return pd.DataFrame(rows)


def _synthetic_location_events(persons: List[str], rng: np.random.Generator, n_rare_meetings: int = 30) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """Background pings at a shared 'office' plus rare two-person meetings at private spots."""
    rows, visits = [], {}
    office = "L_OFFICE"
    visits[office] = list(persons)
    for p in persons:
        for d in range(CASE_DAYS):
            t = CASE_START + pd.Timedelta(days=d, hours=9, minutes=int(rng.integers(0, 30)))
            rows.append({"person_id": p, "location_id": office, "timestamp": t})
    for k in range(n_rare_meetings):
        if len(persons) < 2:
            break
        a, b = rng.choice(len(persons), 2, replace=False)
        loc = f"L_PRIV{k:03d}"
        visits[loc] = [persons[a], persons[b]]
        for rep in range(int(rng.integers(3, 6))):
            t = CASE_START + pd.Timedelta(days=int(rng.integers(0, CASE_DAYS)), hours=int(rng.integers(0, 24)))
            rows.append({"person_id": persons[a], "location_id": loc, "timestamp": t})
            rows.append({"person_id": persons[b], "location_id": loc, "timestamp": t + pd.Timedelta(minutes=int(rng.integers(0, 10)))})
    return pd.DataFrame(rows), visits


def scenario_sparse_20(seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    persons = _persons(20)
    edges = _random_comm_edges(persons, 1.6, rng)
    events, visits = _synthetic_location_events(persons, rng, n_rare_meetings=6)
    return {"graph": _graph_from(persons, edges, visits), "cdr_df": _synthetic_cdr(edges, rng), "location_events_df": events, "persons": persons}


def scenario_dense_500(seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    persons = _persons(500)
    edges = set(_random_comm_edges(persons, 20, rng))
    hub = persons[0]
    for p in persons[1:301]:  # planted hub talks to 60 % of everyone
        edges.add(tuple(sorted((hub, p))))
    edges = sorted(edges)
    events, visits = _synthetic_location_events(persons, rng, n_rare_meetings=60)
    return {"graph": _graph_from(persons, edges, visits), "cdr_df": _synthetic_cdr(edges, rng), "location_events_df": events,
            "persons": persons, "planted_hub": hub}


def scenario_no_timestamps_100(seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    persons = _persons(100)
    edges = _random_comm_edges(persons, 5, rng)
    return {"graph": _graph_from(persons, edges), "cdr_df": None, "location_events_df": None, "persons": persons}


def scenario_no_communication_60(seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    persons = _persons(60)
    events, visits = _synthetic_location_events(persons, rng, n_rare_meetings=40)
    return {"graph": _graph_from(persons, [], visits), "cdr_df": None, "location_events_df": events, "persons": persons}


def scenario_tiny_5_no_edges(seed: int) -> Dict:
    persons = _persons(5)
    return {"graph": _graph_from(persons, []), "cdr_df": None, "location_events_df": None, "persons": persons}


def scenario_isolated_mix_80(seed: int) -> Dict:
    rng = np.random.default_rng(seed)
    persons = _persons(80)
    connected = persons[:60]
    edges = _random_comm_edges(connected, 4, rng)
    return {"graph": _graph_from(persons, edges), "cdr_df": _synthetic_cdr(edges, rng), "location_events_df": None, "persons": persons}


SCENARIOS: Dict[str, Callable[[int], Dict]] = {
    "sparse_20": scenario_sparse_20,
    "dense_500": scenario_dense_500,
    "no_timestamps_100": scenario_no_timestamps_100,
    "no_communication_60": scenario_no_communication_60,
    "tiny_5_no_edges": scenario_tiny_5_no_edges,
    "isolated_mix_80": scenario_isolated_mix_80,
}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _smoke_risk_model(seed: int) -> RiskModel:
    table = make_synthetic_elliptic_like_table(n_nodes=2000, seed=seed)
    model, _ = train_risk_model(feature_table=table, n_folds=3, seed=seed, training_dataset="synthetic_smoke")
    model.notes.append("SMOKE-TEST MODEL trained on synthetic Elliptic-shaped data — its metrics are not a validation claim.")
    return model


def run_scenario(name: str, data: Dict, risk_model: RiskModel, include_gnn: bool, gnn_epochs: int, seed: int) -> Dict:
    report: Dict = {"scenario": name, "passed": False, "checks": {}, "warnings": [], "timings_s": {}}
    persons = data["persons"]
    n = len(persons)
    try:
        t0 = time.time()
        pg = build_person_graph(data["graph"], location_events_df=data["location_events_df"])
        report["timings_s"]["projection"] = round(time.time() - t0, 2)
        report["graph"] = {"persons": pg.number_of_nodes(), "edges": pg.number_of_edges()}

        t0 = time.time()
        cen = run_centrality_analysis(pg)
        com = run_community_detection(pg)
        report["timings_s"]["layer1"] = round(time.time() - t0, 2)

        t0 = time.time()
        lp = run_link_prediction(pg, k=10, include_gnn=include_gnn, gnn_epochs=gnn_epochs, seed=seed)
        report["timings_s"]["layer2"] = round(time.time() - t0, 2)

        t0 = time.time()
        feats = engineer_case_features(pg, cen, com, cdr_df=data["cdr_df"], location_events_df=data["location_events_df"], link_prediction_result=lp)
        risk = score_case_risk(risk_model, feats)
        pm = assemble_person_metrics(cen, risk)
        report["timings_s"]["layer3"] = round(time.time() - t0, 2)

        c = report["checks"]
        c["one_row_per_person_centrality"] = len(cen) == n and set(cen.person_id) == set(persons)
        c["one_row_per_person_community"] = len(com) == n
        c["one_row_per_person_metrics"] = len(pm) == n
        c["centrality_finite"] = bool(np.isfinite(cen[["degree_centrality", "betweenness_centrality", "pagerank"]].values).all())
        c["risk_finite"] = bool(np.isfinite(pm["risk_score"].values).all())
        c["risk_in_unit_interval"] = bool(((pm["risk_score"] >= 0) & (pm["risk_score"] <= 1)).all())
        c["rank_is_permutation"] = sorted(pm["rank"].tolist()) == list(range(1, n + 1))
        c["all_have_community"] = com["community_id"].notna().all()
        c["feature_table_complete"] = set(MODEL_FEATURES) <= set(feats.columns) and len(feats) == n
        c["benchmark_present"] = all(k in lp["benchmark"] for k in ("heuristic_recall_at_k", "gnn_recall_at_k", "winner"))
        c["predictions_well_formed"] = all(
            set(p) >= {"source_person_id", "target_person_id", "method", "probability", "explanation", "review_status"}
            for p in lp["surfaced_predictions"]
        )
        c["no_prediction_on_existing_edge"] = not any(pg.has_edge(p["source_person_id"], p["target_person_id"]) for p in lp["surfaced_predictions"])
        if data["cdr_df"] is None and data["location_events_df"] is None:
            c["temporal_features_nan_when_no_timestamps"] = bool(feats[["odd_hour_ratio", "dormant_reactivation_flag", "fan_out_flag"]].isna().all().all())
        if "planted_hub" in data:
            c["planted_hub_is_rank_1"] = pm.iloc[0]["person_id"] == data["planted_hub"]
        if pg.number_of_edges() == 0:
            c["no_edges_handled"] = len(lp["surfaced_predictions"]) == 0

        report["gnn"] = {"trained": lp["meta"]["gnn_trained"], "backend": lp["meta"]["gnn_backend"],
                         "gnn_recall_at_k": lp["benchmark"]["gnn_recall_at_k"],
                         "heuristic_recall_at_k": lp["benchmark"]["heuristic_recall_at_k"],
                         "surfaced_method": lp["meta"]["surfaced_method"]}
        report["warnings"] = list(lp["meta"]["warnings"])
        if include_gnn and not lp["meta"]["gnn_trained"]:
            report["warnings"].append("GNN degraded/skipped for this shape; heuristic fallback produced the surfaced predictions.")
        report["feature_availability"] = {k: round(float(feats[k].notna().mean()), 2) for k in MODEL_FEATURES}
        report["passed"] = all(bool(v) for v in c.values())
    except Exception as exc:  # the point of the test is to surface these
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    return report


def run_generalization_stress_test(
    risk_model: Optional[RiskModel] = None,
    scenarios: Optional[List[str]] = None,
    include_gnn: bool = True,
    gnn_epochs: int = 60,
    seed: int = 42,
) -> Dict:
    """Run the full pipeline against synthetic graphs of different shapes (function 7).

    Parameters
    ----------
    risk_model
        A trained :class:`RiskModel` (ideally the Elliptic one).  If ``None`` a
        throw-away model is trained on synthetic Elliptic-shaped data purely
        so scoring can execute — flagged in the report as ``synthetic_smoke``.
    scenarios
        Subset of :data:`SCENARIOS` names; default all.
    include_gnn, gnn_epochs, seed
        Link-prediction settings (fewer epochs than production to keep the
        test fast).

    Returns
    -------
    dict
        ``passed`` (bool), ``risk_model_source``, ``gnn_backend`` and
        ``scenarios`` → per-scenario report (checks, warnings, timings, GNN
        status, feature availability, error/traceback on failure).
    """
    names = scenarios or list(SCENARIOS)
    source = "provided"
    if risk_model is None:
        risk_model = _smoke_risk_model(seed)
        source = "synthetic_smoke (NOT a validation source)"
    from .link_prediction.gnn_model import gnn_backend

    reports = {name: run_scenario(name, SCENARIOS[name](seed), risk_model, include_gnn, gnn_epochs, seed) for name in names}
    return {
        "passed": all(r.get("passed", False) for r in reports.values()),
        "risk_model_source": source,
        "risk_model_version": risk_model.model_version,
        "gnn_backend": gnn_backend(),
        "scenarios": reports,
        "note": "Robustness test only: proves the pipeline runs and stays well-formed on different data shapes; "
                "it does not measure predictive accuracy on unseen real data.",
    }


def summarize_stress_report(report: Dict) -> str:
    """Human-readable one-line-per-scenario summary."""
    lines = [f"overall: {'PASS' if report['passed'] else 'FAIL'} | risk model: {report['risk_model_source']} | GNN backend: {report['gnn_backend']}"]
    for name, r in report["scenarios"].items():
        if "error" in r:
            lines.append(f"  {name:22s} ERROR {r['error']}")
            continue
        failed = [k for k, v in r["checks"].items() if not v]
        g = r.get("gnn", {})
        lines.append(
            f"  {name:22s} {'PASS' if r['passed'] else 'FAIL'} | persons={r['graph']['persons']} edges={r['graph']['edges']} "
            f"| surfaced={g.get('surfaced_method')} gnn_trained={g.get('trained')} "
            f"| t={sum(r['timings_s'].values()):.1f}s" + (f" | failed: {failed}" if failed else "")
        )
    return "\n".join(lines)
