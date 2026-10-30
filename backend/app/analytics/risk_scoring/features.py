"""Layer 3 — feature engineering (shared schema for training *and* scoring).

Design rules (they are what make the risk model transfer across cases):

* **Ratios / percentiles, never raw counts.**  ``pagerank_percentile`` means
  "rank within *this* graph", so 0.95 means the same thing in a 20-person
  case and a 200,000-node Bitcoin graph.
* **Missing means missing.**  A feature that cannot be computed for a case
  (no timestamps, no transaction→person link, no GNN) is ``NaN``.  XGBoost
  learns a default split direction for missing values, so nothing is ever
  imputed or fabricated.
* **One schema, two producers.**  :func:`structural_feature_table` is used on
  the case person graph *and* on the Elliptic transaction graph, so the
  columns the model is trained on are exactly the columns it scores.

The nine specified features
---------------------------
1. ``pagerank_percentile``
2. ``community_size_percentile`` (+ informational ``community_id``)
3. ``connection_percentile`` – total connections across all evidence layers
4. ``structuring_flag`` – amounts clustering just under reporting thresholds
5. ``odd_hour_ratio`` – share of timestamped events between 23:00 and 04:00
6. ``dormant_reactivation_flag`` – long inactivity gap then a burst
7. ``fan_out_flag`` – many distinct new contacts inside a short window
8. ``cross_layer_ratio`` – share of a person's ties backed by ≥ 2 evidence layers
9. ``lp_agreement_flag`` – person appears in BOTH heuristic and GNN top links

Two extra *generic* structural features are included because they are
computable on any graph (case or Elliptic) and strengthen the transferable
signal: ``clustering_percentile`` and ``avg_neighbor_degree_percentile``.
Set ``include_extra_structural=False`` to drop them.
"""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from ..graph_utils import as_person_graph, layer_counts, person_ids

logger = logging.getLogger(__name__)

SPEC_FEATURES: List[str] = [
    "pagerank_percentile",
    "community_size_percentile",
    "connection_percentile",
    "structuring_flag",
    "odd_hour_ratio",
    "dormant_reactivation_flag",
    "fan_out_flag",
    "cross_layer_ratio",
    "lp_agreement_flag",
]
EXTRA_STRUCTURAL_FEATURES: List[str] = ["clustering_percentile", "avg_neighbor_degree_percentile"]
MODEL_FEATURES: List[str] = SPEC_FEATURES + EXTRA_STRUCTURAL_FEATURES
INFO_COLUMNS: List[str] = ["person_id", "community_id"]

# Domain parameters (documented, overridable through function arguments)
DEFAULT_STRUCTURING_THRESHOLDS: Tuple[float, ...] = (10_000.0, 50_000.0, 100_000.0)
STRUCTURING_BAND = 0.20        # amounts within 20 % *below* a threshold count
STRUCTURING_MIN_EVENTS = 3
ODD_HOUR_START, ODD_HOUR_END = 23, 4   # 23:00 → 04:00
DORMANT_MIN_EVENTS = 5
DORMANT_GAP_SHARE = 0.25       # gap must be ≥ 25 % of the person's active span …
DORMANT_MIN_GAP_HOURS = 48.0   # … and at least 48 h
DORMANT_BURST_HOURS = 24.0
FANOUT_WINDOW_HOURS = 24.0
FANOUT_MIN_CONTACTS = 3
FANOUT_SHARE = 0.5


def _pct(series: pd.Series) -> pd.Series:
    """Percentile rank in (0, 1]; constant columns become 0.5."""
    if series.nunique(dropna=True) <= 1:
        return pd.Series(0.5, index=series.index)
    return series.rank(pct=True, method="average")


# --------------------------------------------------------------------------- #
# Generic structural features — used for the case graph AND for Elliptic
# --------------------------------------------------------------------------- #
def structural_feature_table(
    graph: nx.Graph,
    nodes: Optional[Sequence] = None,
    pagerank: Optional[Dict] = None,
    community_of: Optional[Dict] = None,
    include_extra_structural: bool = True,
    seed: int = 42,
) -> pd.DataFrame:
    """Percentile-based structural features for every node of ``graph``.

    ``pagerank`` / ``community_of`` may be supplied to reuse Layer 1 results;
    otherwise they are computed here.  Returns one row per node with columns
    ``node_id, community_id, pagerank_percentile, community_size_percentile,
    connection_percentile, cross_layer_ratio`` (+ extras).
    """
    nodes = list(nodes) if nodes is not None else sorted(graph.nodes())
    n = len(nodes)
    if n == 0:
        return pd.DataFrame(columns=["node_id", "community_id"] + MODEL_FEATURES)

    if pagerank is None:
        pagerank = nx.pagerank(graph, weight="weight") if graph.number_of_edges() else {v: 1.0 / n for v in nodes}
    if community_of is None:
        if graph.number_of_edges():
            comms = nx.community.louvain_communities(graph, weight="weight", seed=seed)
        else:
            comms = [{v} for v in nodes]
        community_of = {v: f"C{i:02d}" for i, c in enumerate(sorted(comms, key=lambda c: -len(c))) for v in c}
    sizes = pd.Series(community_of).value_counts()

    wdeg = dict(graph.degree(weight="weight"))
    df = pd.DataFrame({"node_id": nodes})
    df["community_id"] = [community_of.get(v) for v in nodes]
    df["pagerank_percentile"] = _pct(pd.Series([pagerank.get(v, 0.0) for v in nodes]))
    df["community_size_percentile"] = _pct(pd.Series([sizes.get(community_of.get(v), 1) for v in nodes]))
    df["connection_percentile"] = _pct(pd.Series([wdeg.get(v, 0.0) for v in nodes]))

    # cross-layer ratio only makes sense if the graph carries ≥ 2 evidence layers
    layers = layer_counts(graph)
    if len([l for l, c in layers.items() if c > 0]) >= 2:
        ratio = {}
        for v in nodes:
            edges = list(graph.edges(v, data=True))
            multi = sum(1 for _, _, d in edges if len(d.get("layers", [])) >= 2)
            ratio[v] = (multi / len(edges)) if edges else 0.0
        df["cross_layer_ratio"] = [ratio[v] for v in nodes]
    else:
        df["cross_layer_ratio"] = np.nan

    if include_extra_structural:
        if graph.number_of_edges():
            cc = nx.clustering(graph)
            ndeg = nx.average_neighbor_degree(graph)
        else:
            cc = {v: 0.0 for v in nodes}
            ndeg = {v: 0.0 for v in nodes}
        df["clustering_percentile"] = _pct(pd.Series([cc.get(v, 0.0) for v in nodes]))
        df["avg_neighbor_degree_percentile"] = _pct(pd.Series([ndeg.get(v, 0.0) for v in nodes]))
    else:
        df["clustering_percentile"] = np.nan
        df["avg_neighbor_degree_percentile"] = np.nan
    return df


# --------------------------------------------------------------------------- #
# Domain / temporal features for a case
# --------------------------------------------------------------------------- #
def _person_event_times(
    persons: Sequence[str],
    cdr_df: Optional[pd.DataFrame],
    location_events_df: Optional[pd.DataFrame],
) -> Dict[str, np.ndarray]:
    """All timestamped events per person (calls made + received, location pings), sorted."""
    frames = []
    if cdr_df is not None and not cdr_df.empty and "call_start_time" in cdr_df:
        t = pd.to_datetime(cdr_df["call_start_time"], errors="coerce")
        for col in ("caller_person_id", "receiver_person_id"):
            if col in cdr_df:
                frames.append(pd.DataFrame({"person_id": cdr_df[col].values, "ts": t.values}))
    if location_events_df is not None and not location_events_df.empty and "timestamp" in location_events_df:
        t = pd.to_datetime(location_events_df["timestamp"], errors="coerce")
        frames.append(pd.DataFrame({"person_id": location_events_df["person_id"].values, "ts": t.values}))
    if not frames:
        return {}
    ev = pd.concat(frames, ignore_index=True).dropna()
    ev = ev[ev["person_id"].isin(set(persons))]
    if ev.empty:
        return {}
    return {p: np.sort(g["ts"].values.astype("datetime64[ns]")) for p, g in ev.groupby("person_id")}


def odd_hour_ratio(times: np.ndarray) -> float:
    if times.size == 0:
        return np.nan
    hours = pd.DatetimeIndex(times).hour
    odd = (hours >= ODD_HOUR_START) | (hours < ODD_HOUR_END)
    return float(odd.mean())


def dormant_reactivation_flag(times: np.ndarray) -> float:
    if times.size < DORMANT_MIN_EVENTS:
        return np.nan
    t = pd.DatetimeIndex(times)
    span_h = (t[-1] - t[0]).total_seconds() / 3600.0
    if span_h <= 0:
        return 0.0
    gaps_h = np.diff(t.values).astype("timedelta64[s]").astype(float) / 3600.0
    i = int(np.argmax(gaps_h))
    gap = gaps_h[i]
    if gap < max(DORMANT_MIN_GAP_HOURS, DORMANT_GAP_SHARE * span_h):
        return 0.0
    restart = t[i + 1]
    burst = int(((t >= restart) & (t < restart + pd.Timedelta(hours=DORMANT_BURST_HOURS))).sum())
    days = max(span_h / 24.0, 1.0)
    typical_daily = times.size / days
    return 1.0 if burst >= max(3, typical_daily) else 0.0


def fan_out_flags(cdr_df: Optional[pd.DataFrame], persons: Sequence[str]) -> Dict[str, float]:
    """Per caller: 1 if ≥ FANOUT_SHARE of all distinct contacts were first reached within FANOUT_WINDOW_HOURS."""
    if cdr_df is None or cdr_df.empty or "call_start_time" not in cdr_df or "caller_person_id" not in cdr_df:
        return {}
    df = cdr_df[["caller_person_id", "receiver_person_id", "call_start_time"]].copy()
    df["call_start_time"] = pd.to_datetime(df["call_start_time"], errors="coerce")
    df = df.dropna()
    df = df[df["caller_person_id"].isin(set(persons))]
    out: Dict[str, float] = {}
    win = pd.Timedelta(hours=FANOUT_WINDOW_HOURS)
    for caller, g in df.groupby("caller_person_id"):
        first = g.sort_values("call_start_time").drop_duplicates("receiver_person_id")
        n_total = len(first)
        if n_total < FANOUT_MIN_CONTACTS:
            out[caller] = 0.0
            continue
        ts = first["call_start_time"].values
        best = 0
        j = 0
        for i in range(n_total):
            while ts[i] - ts[j] > win:
                j += 1
            best = max(best, i - j + 1)
        out[caller] = 1.0 if best / n_total >= FANOUT_SHARE else 0.0
    return out


def structuring_flags(
    transactions_df: Optional[pd.DataFrame],
    persons: Sequence[str],
    thresholds: Iterable[float] = DEFAULT_STRUCTURING_THRESHOLDS,
) -> Dict[str, float]:
    """Per person with linked transactions: 1 if ≥ STRUCTURING_MIN_EVENTS amounts sit just below a threshold.

    Requires a non-null ``person_id`` column — the current dataset has none,
    so every person gets NaN (never fabricated).
    """
    if transactions_df is None or transactions_df.empty or "person_id" not in transactions_df or "amount" not in transactions_df:
        return {}
    df = transactions_df[["person_id", "amount"]].dropna()
    df = df[df["person_id"].isin(set(persons))]
    if df.empty:
        return {}
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    out: Dict[str, float] = {}
    for p, g in df.groupby("person_id"):
        a = g["amount"].dropna().values
        flag = 0.0
        for th in thresholds:
            if ((a >= th * (1 - STRUCTURING_BAND)) & (a < th)).sum() >= STRUCTURING_MIN_EVENTS:
                flag = 1.0
                break
        out[p] = flag
    return out


def engineer_case_features(
    graph: nx.Graph,
    centrality_df: pd.DataFrame,
    community_df: pd.DataFrame,
    transactions_df: Optional[pd.DataFrame] = None,
    cdr_df: Optional[pd.DataFrame] = None,
    location_events_df: Optional[pd.DataFrame] = None,
    link_prediction_result: Optional[dict] = None,
    structuring_thresholds: Iterable[float] = DEFAULT_STRUCTURING_THRESHOLDS,
    include_extra_structural: bool = True,
) -> pd.DataFrame:
    """Build the risk-feature table for every person in a case.

    Parameters
    ----------
    graph
        Raw investigation graph or projected person graph.
    centrality_df, community_df
        Outputs of :func:`run_centrality_analysis` / :func:`run_community_detection`.
    transactions_df
        Optional; needs ``person_id`` + ``amount`` columns for the structuring
        flag.  The current dataset has no person link → feature is NaN.
    cdr_df
        Optional ``caller_person_id, receiver_person_id, call_start_time``.
    location_events_df
        Optional ``person_id, location_id, timestamp`` (also used for the
        time-windowed co-location layer when ``graph`` is raw).
    link_prediction_result
        Optional output of :func:`run_link_prediction` for feature 9.
    structuring_thresholds
        Reporting thresholds used by the structuring flag.
    include_extra_structural
        Whether to add the two extra generic structural features.

    Returns
    -------
    pd.DataFrame
        ``person_id, community_id`` + :data:`MODEL_FEATURES`.  Never raises
        because optional inputs are missing — the corresponding columns are NaN.
    """
    pg = as_person_graph(graph, location_events_df=location_events_df)
    persons = person_ids(pg)
    pr = dict(zip(centrality_df["person_id"], centrality_df["pagerank"])) if centrality_df is not None and len(centrality_df) else None
    com = dict(zip(community_df["person_id"], community_df["community_id"])) if community_df is not None and len(community_df) else None
    df = structural_feature_table(pg, persons, pagerank=pr, community_of=com, include_extra_structural=include_extra_structural)
    df = df.rename(columns={"node_id": "person_id"})

    times = _person_event_times(persons, cdr_df, location_events_df)
    df["odd_hour_ratio"] = [odd_hour_ratio(times[p]) if p in times else np.nan for p in persons]
    df["dormant_reactivation_flag"] = [dormant_reactivation_flag(times[p]) if p in times else np.nan for p in persons]

    fo = fan_out_flags(cdr_df, persons)
    df["fan_out_flag"] = [fo.get(p, np.nan) for p in persons] if fo else np.nan

    st = structuring_flags(transactions_df, persons, structuring_thresholds)
    df["structuring_flag"] = [st.get(p, np.nan) for p in persons] if st else np.nan

    if link_prediction_result and link_prediction_result.get("gnn_predictions"):
        from ..link_prediction.benchmark import persons_in_both_methods

        both = persons_in_both_methods(link_prediction_result)
        df["lp_agreement_flag"] = [1.0 if p in both else 0.0 for p in persons]
    else:
        df["lp_agreement_flag"] = np.nan

    return df[INFO_COLUMNS + MODEL_FEATURES]


def feature_availability(features_df: pd.DataFrame) -> Dict[str, float]:
    """Share of non-missing values per model feature — useful for the dashboard/README."""
    return {c: float(features_df[c].notna().mean()) if c in features_df else 0.0 for c in MODEL_FEATURES}
