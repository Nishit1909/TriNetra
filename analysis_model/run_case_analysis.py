"""run_case_analysis: one case in, person metrics + predicted links out, with honest stage status.

Contract (agreed with the backend):

    run_case_analysis(persons, edges, mode, weights) -> {
        "status": "ok" | "partial" | "failed",
        "stages": {stage: {"status": "ok" | "failed" | "skipped", "error": str | None, "rows": int | None}},
        "person_metrics": DataFrame[person_id, degree, weighted_degree, betweenness, pagerank, community_id, hub_flag],
        "predicted_links": DataFrame[person_a, person_b, method, score, factor_breakdown, evidence_refs],
        "warnings": [str],
        "mode": str, "weights_version": str,
    }

persons: DataFrame with person_id (unique), optional department.
edges:   DataFrame with person_a, person_b, relationship_type, is_inferred (bool), weight (float),
         optional factors (dict or JSON string) and evidence_refs (list or ';'-separated string).
mode:    "observed_only" drops every inferred edge; "observed_plus_inferred" keeps them.
weights: the parsed weights JSON (see weights/v1.json); its "version" is echoed back.

"ok" with empty predicted_links means "no findings". A failed stage is reported as failed with its error
and never as an empty success. Pure function: no database, no network, deterministic for a given seed.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

import networkx as nx
import numpy as np
import pandas as pd

MODES = ("observed_only", "observed_plus_inferred")
METRIC_COLUMNS = ["person_id", "degree", "weighted_degree", "betweenness", "pagerank", "community_id", "hub_flag"]
LINK_COLUMNS = ["person_a", "person_b", "method", "score", "factor_breakdown", "evidence_refs"]
STAGES = ["validate_input", "edge_strength", "graph", "centrality", "communities", "link_prediction"]
CRITICAL = {"validate_input", "edge_strength", "graph"}


class InputError(ValueError):
    pass


# ------------------------------------------------------------------ helpers
def _as_dict(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_list(v: Any) -> list:
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x)]
    if isinstance(v, np.ndarray):
        return [str(x) for x in v.tolist() if str(x)]
    if isinstance(v, str) and v.strip():
        return [x for x in v.replace(",", ";").split(";") if x]
    return []


def _num(d: dict, k: str, default: float = 0.0) -> float:
    try:
        x = float(d.get(k, default))
        return default if math.isnan(x) else x
    except (TypeError, ValueError):
        return 1.0 if str(d.get(k)).lower() == "true" else default


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


# ------------------------------------------------------------------ stages
def _validate(persons: pd.DataFrame, edges: pd.DataFrame, mode: str, weights: dict, warnings: list) -> tuple[pd.DataFrame, pd.DataFrame]:
    if mode not in MODES:
        raise InputError(f"mode must be one of {MODES}, got {mode!r}")
    if not isinstance(weights, dict) or not weights.get("version"):
        raise InputError("weights must be a dict with a 'version'")
    if persons is None or "person_id" not in persons:
        raise InputError("persons must have a person_id column")
    p = persons.copy()
    p["person_id"] = p["person_id"].astype(str)
    if p.person_id.duplicated().any():
        raise InputError(f"duplicate person_id: {sorted(p.person_id[p.person_id.duplicated()].unique())[:5]}")
    e = edges.copy() if edges is not None else pd.DataFrame()
    need = ["person_a", "person_b", "relationship_type", "is_inferred", "weight"]
    missing = [c for c in need if c not in e.columns]
    if missing and len(e):
        raise InputError(f"edges missing columns {missing}")
    if not len(e):
        return p, pd.DataFrame(columns=need + ["factors", "evidence_refs"])
    e["person_a"], e["person_b"] = e.person_a.astype(str), e.person_b.astype(str)
    known = set(p.person_id)
    unknown = sorted((set(e.person_a) | set(e.person_b)) - known)
    if unknown:
        raise InputError(f"edges reference unknown persons (other case?): {unknown[:5]}")
    self_loops = int((e.person_a == e.person_b).sum())
    if self_loops:
        warnings.append(f"dropped {self_loops} self-loop edges")
        e = e[e.person_a != e.person_b]
    e["is_inferred"] = e.is_inferred.map(lambda v: str(v).lower() in ("true", "1", "t", "yes"))
    e["weight"] = pd.to_numeric(e.weight, errors="coerce")
    bad = int(e.weight.isna().sum() + (e.weight < 0).sum())
    if bad:
        warnings.append(f"dropped {bad} edges with missing or negative weight")
        e = e[e.weight.notna() & (e.weight >= 0)]
    for c in ("factors", "evidence_refs"):
        if c not in e:
            e[c] = None
    if mode == "observed_only":
        e = e[~e.is_inferred]
    return p, e.reset_index(drop=True)


def _inferred_contribution(f: dict, same_dept: bool, w: dict) -> dict:
    """Per-factor contributions for one inferred edge (before scaling). Keys are human-readable."""
    fw = w["inferred_factors"]
    out = {}
    days = min(_num(f, "private_days"), fw["private_day"].get("cap", 5))
    meetings = _num(f, "private_meetings")
    if days:
        pts = days * fw["private_day"]["weight"]
        out[f"private meeting days ({int(days)})"] = pts
        g = _num(f, "group_gatherings") / meetings if meetings else 0.0
        if g > 0:   # group routines: discount the meeting-day points
            out["group gatherings discount"] = round(-pts * g * fw["group_gathering_share"]["weight"], 3)
    if _num(f, "home_visits") > 0:
        out["home visit"] = fw["home_visit"]["weight"]
    after = _num(f, "after_hours_private") / meetings if meetings else 0.0
    if after > 0:
        out["after-hours share"] = round(after * fw["after_hours_share"]["weight"], 3)
    if days >= 2 and _num(f, "chance_p_value", 1.0) <= 0.1:
        out["more than chance"] = fw["beats_chance"]["weight"]
    pub = _num(f, "public_place_events")
    if pub > 0:
        out["seen together in public"] = round(math.log1p(pub) * fw["public_events_log"]["weight"], 3)
    if _num(f, "both_live_here_events") > 0:
        out["live at same place"] = fw["co_resident"]["weight"]
    if same_dept and out:
        out["same department (routine)"] = fw["same_department"]["weight"]
    if days and after == 0 and _num(f, "home_visits") == 0:
        subtotal = sum(out.values())
        if subtotal > 0:
            out["daytime-only discount"] = round(-subtotal * (1 - fw["daytime_only"]["weight"]), 3)
    return out


def _edge_strength(p: pd.DataFrame, e: pd.DataFrame, w: dict, warnings: list) -> pd.DataFrame:
    dept = dict(zip(p.person_id, p.get("department", pd.Series([None] * len(p)))))
    obs_w, obs_def = w.get("observed", {}), w.get("observed_default", {"weight": 0.5})
    rows = []
    for r in e.itertuples(index=False):
        a, b = _pair(r.person_a, r.person_b)
        rtype = str(r.relationship_type)
        refs = _as_list(r.evidence_refs)
        if r.is_inferred:
            f = _as_dict(r.factors)
            sd = dept.get(a) is not None and dept.get(a) == dept.get(b) and not pd.isna(dept.get(a))
            contrib = _inferred_contribution(f, sd, w) if f else {}
            if contrib:
                raw = sum(contrib.values())
                strength = max(0.0, raw) / w.get("inferred_scale", 15.0)
                breakdown = {k: round(v, 3) for k, v in contrib.items()}
            else:
                strength = float(r.weight) * w.get("inferred_type_default", {"weight": 0.5})["weight"]
                breakdown = {f"{rtype} (no factors)": round(strength, 3)}
            for key in ("supporting_colocation_ids", "supporting_private_colocation_ids"):
                refs += _as_list(f.get(key)) if f else []
        else:
            tw = obs_w.get(rtype.upper(), obs_def)["weight"]
            f = _as_dict(r.factors)
            if "direct_email_events" in f:   # email pair: direct emails count, broadcast-only pairs get broadcast weight
                direct, total = _num(f, "direct_email_events"), _num(f, "email_events")
                bw = w.get("broadcast_email_weight", {"weight": 0.0})["weight"]
                strength = tw * math.log1p(direct) + bw * math.log1p(max(total - direct, 0))
                breakdown = {f"{rtype}: direct emails ({int(direct)})": round(tw * math.log1p(direct), 3)}
                if total - direct > 0:
                    breakdown[f"{rtype}: broadcast emails ({int(total - direct)})"] = round(bw * math.log1p(total - direct), 3)
            else:
                strength = tw * float(r.weight)
                breakdown = {rtype: round(strength, 3)}
        rows.append((a, b, rtype, bool(r.is_inferred), strength, breakdown, sorted(set(refs))))
    s = pd.DataFrame(rows, columns=["a", "b", "type", "is_inferred", "strength", "breakdown", "refs"])
    zero = int((s.strength <= 0).sum()) if len(s) else 0
    if zero:
        warnings.append(f"{zero} edges have zero strength after weighting (kept for evidence, ignored in the graph)")
    return s


def _graph(p: pd.DataFrame, s: pd.DataFrame, w: dict) -> tuple[nx.Graph, dict]:
    g_cfg = w.get("graph", {})
    pair = s[s.strength > 0].groupby(["a", "b"]).agg(strength=("strength", "sum")).reset_index()
    G = nx.Graph()
    G.add_nodes_from(p.person_id)
    for r in pair.itertuples(index=False):
        G.add_edge(r.a, r.b, strength=float(r.strength))
    tot = dict(G.degree(weight="strength"))
    for a, b, d in G.edges(data=True):
        if g_cfg.get("association_strength", True):
            # association strength: rare, exclusive ties count more than one of many mass contacts
            d["w"] = d["strength"] / math.sqrt(tot[a] * tot[b]) if tot[a] and tot[b] else 0.0
        else:
            d["w"] = d["strength"]
        d["dist"] = 1.0 / d["w"] if d["w"] > 0 else float("inf")
    deg = np.array([G.degree(n) for n in G]) if len(G) else np.array([0])
    cut = deg.mean() + g_cfg.get("hub_sigma", 3.0) * deg.std()
    hubs = {n for n in G if G.degree(n) > cut and G.degree(n) >= g_cfg.get("hub_min_degree", 3)}
    return G, {"hubs": hubs, "hub_cutoff": float(cut)}


def _centrality(G: nx.Graph, w: dict) -> pd.DataFrame:
    g_cfg = w.get("graph", {})
    n = G.number_of_nodes()
    if G.number_of_edges() == 0:
        z = {v: 0.0 for v in G}
        return pd.DataFrame({"person_id": list(G), "degree": 0, "weighted_degree": 0.0, "betweenness": 0.0,
                             "pagerank": [1.0 / n if n else 0.0] * n})
    pr = nx.pagerank(G, weight="w", alpha=0.85, max_iter=1000, tol=1e-10)
    if n <= g_cfg.get("betweenness_exact_max_nodes", 2000):
        bt = nx.betweenness_centrality(G, weight="dist", normalized=True)
    else:
        bt = nx.betweenness_centrality(G, k=min(g_cfg.get("betweenness_sample_k", 500), n), weight="dist",
                                       normalized=True, seed=g_cfg.get("seed", 42))
    wd = dict(G.degree(weight="w"))
    return pd.DataFrame({"person_id": list(G), "degree": [G.degree(v) for v in G],
                         "weighted_degree": [round(wd[v], 6) for v in G],
                         "betweenness": [round(bt[v], 6) for v in G], "pagerank": [round(pr[v], 6) for v in G]})


def _communities(G: nx.Graph, w: dict) -> dict:
    g_cfg = w.get("graph", {})
    if G.number_of_edges() == 0:
        comms = [{v} for v in G]
    else:
        try:  # Leiden if available, else seeded Louvain
            import igraph as ig  # type: ignore
            import leidenalg  # type: ignore
            nodes = list(G)
            idx = {v: i for i, v in enumerate(nodes)}
            gi = ig.Graph(n=len(nodes), edges=[(idx[a], idx[b]) for a, b in G.edges()])
            part = leidenalg.find_partition(gi, leidenalg.RBConfigurationVertexPartition,
                                            weights=[G[a][b]["w"] for a, b in G.edges()],
                                            resolution_parameter=g_cfg.get("community_resolution", 1.0),
                                            seed=g_cfg.get("seed", 42))
            comms = [{nodes[i] for i in c} for c in part]
        except ImportError:
            comms = list(nx.community.louvain_communities(G, weight="w", resolution=g_cfg.get("community_resolution", 1.0),
                                                          seed=g_cfg.get("seed", 42)))
    comms = sorted(comms, key=lambda c: (-len(c), sorted(c)[0]))
    return {v: f"C{i:02d}" for i, c in enumerate(comms) for v in c}


def _link_prediction(G: nx.Graph, s: pd.DataFrame, mode: str, w: dict) -> pd.DataFrame:
    lp = w.get("link_prediction", {})
    k = lp.get("max_per_method", 50)
    comm_types = {t.upper() for t in w.get("communication_types", [])}
    rows = []
    # method 1: inferred tie with no recorded communication between the pair (the "meet but never communicate" lead)
    if mode == "observed_plus_inferred" and len(s):
        communicated = {(r.a, r.b) for r in s.itertuples() if not r.is_inferred and r.type.upper() in comm_types and r.strength > 0}
        inf = s[s.is_inferred & (s.strength > 0)]
        inf = inf[[(a, b) not in communicated for a, b in zip(inf.a, inf.b)]]
        agg = inf.groupby(["a", "b"]).agg(score=("strength", "sum"), breakdown=("breakdown", lambda x: {k_: v for d in x for k_, v in d.items()}),
                                          refs=("refs", lambda x: sorted({r for l in x for r in l}))).reset_index()
        agg = agg.sort_values(["score", "a", "b"], ascending=[False, True, True]).head(k)
        for r in agg.itertuples(index=False):
            rows.append((r.a, r.b, "inferred_without_recorded_communication", round(float(r.score), 6), r.breakdown, r.refs))
    # method 2: Adamic-Adar on the case graph for pairs with no edge at all (shared contacts; weaker signal on Noordin)
    if G.number_of_edges():
        cand = []
        for a, b, sc in nx.adamic_adar_index(G, list(nx.non_edges(G))):   # list: a generator yields nothing in networkx 3.7
            if sc > lp.get("adamic_adar_min_score", 0.0):
                cand.append((*_pair(a, b), sc))
        cand.sort(key=lambda t: (-t[2], t[0], t[1]))
        for a, b, sc in cand[:k]:
            shared = sorted(nx.common_neighbors(G, a, b))
            rows.append((a, b, "adamic_adar_shared_contacts", round(float(sc), 6),
                         {"shared contacts": len(shared), "examples": shared[:5]}, []))
    return pd.DataFrame(rows, columns=LINK_COLUMNS)


# ------------------------------------------------------------------ entry point
def run_case_analysis(persons: pd.DataFrame, edges: pd.DataFrame, mode: str, weights: dict) -> dict:
    stages = {s: {"status": "skipped", "error": None, "rows": None} for s in STAGES}
    warnings: list[str] = []
    out = {"status": "failed", "stages": stages, "warnings": warnings, "mode": mode,
           "weights_version": weights.get("version") if isinstance(weights, dict) else None,
           "person_metrics": pd.DataFrame(columns=METRIC_COLUMNS), "predicted_links": pd.DataFrame(columns=LINK_COLUMNS)}

    def run(name: str, fn: Callable, *args):
        try:
            res = fn(*args)
            stages[name]["status"] = "ok"
            return res, True
        except Exception as exc:  # report, never hide
            stages[name]["status"] = "failed"
            stages[name]["error"] = f"{type(exc).__name__}: {exc}"
            return None, False

    v, ok = run("validate_input", _validate, persons, edges, mode, weights, warnings)
    if not ok:
        return out
    p, e = v
    stages["validate_input"]["rows"] = len(e)
    s, ok = run("edge_strength", _edge_strength, p, e, weights, warnings)
    if not ok:
        return out
    stages["edge_strength"]["rows"] = len(s)
    gres, ok = run("graph", _graph, p, s, weights)
    if not ok:
        return out
    G, ginfo = gres
    stages["graph"]["rows"] = G.number_of_edges()
    if ginfo["hubs"]:
        warnings.append(f"structural hubs flagged for verification (degree > {ginfo['hub_cutoff']:.1f}): {sorted(ginfo['hubs'])}")

    metrics = pd.DataFrame({"person_id": list(p.person_id)})
    c, ok_c = run("centrality", _centrality, G, weights)
    if ok_c:
        metrics = metrics.merge(c, on="person_id", how="left")
        stages["centrality"]["rows"] = len(c)
    comm, ok_m = run("communities", _communities, G, weights)
    if ok_m:
        metrics["community_id"] = metrics.person_id.map(comm)
        stages["communities"]["rows"] = len(set(comm.values()))
    for col in METRIC_COLUMNS:
        if col not in metrics:
            metrics[col] = None
    metrics["hub_flag"] = metrics.person_id.isin(ginfo["hubs"])
    out["person_metrics"] = metrics[METRIC_COLUMNS]

    links, ok_l = run("link_prediction", _link_prediction, G, s, mode, weights)
    if ok_l:
        out["predicted_links"] = links
        stages["link_prediction"]["rows"] = len(links)
    out["status"] = "ok" if all(stages[x]["status"] == "ok" for x in STAGES) else "partial"
    return out


def load_weights(path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
