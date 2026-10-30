"""Layer 2 — hidden-edge-recovery benchmark and link-prediction orchestration.

Validation protocol (``hidden_edge_recovery``)
---------------------------------------------
1. Randomly hide ``hide_fraction`` (default 20 %) of the real person-graph
   edges (seeded, all nodes kept).
2. Score the *same* candidate pairs on the reduced graph with every method:
   Jaccard, Adamic-Adar, the combined heuristic, and the GNN (trained on the
   reduced graph only — it never sees the hidden edges).
3. **Recall@K (per node)** – for every node that lost at least one edge, take
   its top-K predicted partners and measure the fraction of its hidden
   neighbours recovered; average over those nodes.  This is the number stored
   in ``link_prediction_benchmark.recall_at_k``.
4. **Global recall@N** – with N = number of hidden edges, the fraction of
   hidden edges inside the top-N predictions overall (stricter, reported
   alongside for transparency).

Hidden edges whose endpoints are not even candidate pairs on the reduced
graph count as misses — nothing is silently excluded.

The winner is decided by measured per-node Recall@K: first the best
heuristic *variant* is selected (Jaccard vs Adamic-Adar vs their blend), then
that variant is compared against the GNN.  Ties (or an unavailable GNN) go to
the heuristic, which is the cheaper, training-free default.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np
import pandas as pd

from ..graph_utils import as_person_graph, person_ids
from . import gnn_model
from .heuristics import (
    METHOD_ADAMIC_ADAR,
    METHOD_HEURISTIC,
    METHOD_JACCARD,
    heuristic_scores,
    scores_to_predictions,
)

logger = logging.getLogger(__name__)

METHOD_GNN = "gnn"
BENCHMARK_METHODS = (METHOD_JACCARD, METHOD_ADAMIC_ADAR, METHOD_HEURISTIC, METHOD_GNN)
ALLPAIRS_MAX_NODES = 400  # above this, candidates are restricted to 2-hop pairs

Pair = Tuple[str, str]


# --------------------------------------------------------------------------- #
# Candidate generation
# --------------------------------------------------------------------------- #
def candidate_pairs(pg: nx.Graph, mode: str = "auto") -> Tuple[List[Pair], str]:
    """Non-connected person pairs to score.

    ``mode="all"`` → every non-adjacent pair (O(n²)); ``"two_hop"`` → only pairs
    sharing at least one neighbour; ``"auto"`` → ``all`` for graphs up to
    ``ALLPAIRS_MAX_NODES`` nodes, else ``two_hop``.  Returns ``(pairs, mode_used)``.
    """
    nodes = sorted(pg.nodes())
    if mode == "auto":
        mode = "all" if len(nodes) <= ALLPAIRS_MAX_NODES else "two_hop"
    pairs: List[Pair] = []
    if mode == "all":
        for i, a in enumerate(nodes):
            for b in nodes[i + 1 :]:
                if not pg.has_edge(a, b):
                    pairs.append((a, b))
    else:
        seen = set()
        for a in nodes:
            for w in pg[a]:
                for b in pg[w]:
                    if a < b and not pg.has_edge(a, b) and (a, b) not in seen:
                        seen.add((a, b))
                        pairs.append((a, b))
        pairs.sort()
    return pairs, mode


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #
def _method_score_columns() -> Dict[str, str]:
    return {
        METHOD_JACCARD: "jaccard_norm",
        METHOD_ADAMIC_ADAR: "adamic_adar_norm",
        METHOD_HEURISTIC: "heuristic_score",
        METHOD_GNN: "gnn_score",
    }


def score_all_methods(
    pg: nx.Graph,
    pairs: Sequence[Pair],
    include_gnn: bool = True,
    gnn_epochs: int = gnn_model.DEFAULT_EPOCHS,
    seed: int = 42,
) -> Tuple[pd.DataFrame, Optional[gnn_model.TrainedGNN]]:
    """Score ``pairs`` on ``pg`` with all methods; ``gnn_score`` is NaN if the GNN is unavailable."""
    scores = heuristic_scores(pg, list(pairs))
    trained = None
    scores["gnn_score"] = np.nan
    if include_gnn:
        trained = gnn_model.train_gnn_link_predictor(pg, epochs=gnn_epochs, seed=seed)
        if trained is not None:
            g = gnn_model.gnn_pair_scores(trained, list(zip(scores["source_person_id"], scores["target_person_id"])))
            scores["gnn_score"] = [g.get((a, b), np.nan) for a, b in zip(scores["source_person_id"], scores["target_person_id"])]
    return scores, trained


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _recall_metrics(scores: pd.DataFrame, hidden: Sequence[Pair], k: int, col: str) -> Tuple[float, float]:
    """(per-node Recall@K, global recall@N) for one score column."""
    if not hidden:
        return float("nan"), float("nan")
    hidden_set = set(hidden)
    s = scores.dropna(subset=[col]) if col in scores else scores.iloc[0:0]
    if s.empty:
        return 0.0, 0.0
    # global recall@N
    n = len(hidden)
    top_global = s.nlargest(n, col)
    hit_global = sum((a, b) in hidden_set for a, b in zip(top_global["source_person_id"], top_global["target_person_id"]))
    global_recall = hit_global / n

    # per-node recall@K
    hidden_nb: Dict[str, set] = defaultdict(set)
    for a, b in hidden:
        hidden_nb[a].add(b)
        hidden_nb[b].add(a)
    per_node: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
    for a, b, v in zip(s["source_person_id"], s["target_person_id"], s[col]):
        if a in hidden_nb:
            per_node[a].append((float(v), b))
        if b in hidden_nb:
            per_node[b].append((float(v), a))
    recalls = []
    for node, hid in hidden_nb.items():
        ranked = sorted(per_node.get(node, []), key=lambda t: (-t[0], t[1]))[:k]
        top = {p for _, p in ranked if _ > 0}
        recalls.append(len(hid & top) / len(hid))
    return float(np.mean(recalls)) if recalls else 0.0, float(global_recall)


def hidden_edge_recovery(
    pg: nx.Graph,
    hide_fraction: float = 0.2,
    k: int = 10,
    seed: int = 42,
    n_repeats: int = 1,
    include_gnn: bool = True,
    gnn_epochs: int = gnn_model.DEFAULT_EPOCHS,
    candidate_mode: str = "auto",
) -> dict:
    """Run the hidden-edge-recovery protocol (see module docstring).

    Returns a dict with per-method ``recall_at_k`` (per-node) and
    ``global_recall_at_n`` averaged over ``n_repeats`` seeds, the winner,
    and bookkeeping (number of hidden edges, candidate mode, GNN backend).
    """
    edges = sorted(tuple(sorted(e)) for e in pg.edges())
    if len(edges) < 5:
        return {
            "k": k, "hide_fraction": hide_fraction, "n_repeats": 0, "hidden_edges": 0,
            "per_method": {m: {"recall_at_k": float("nan"), "global_recall_at_n": float("nan")} for m in BENCHMARK_METHODS},
            "heuristic_recall_at_k": float("nan"), "heuristic_variant": METHOD_HEURISTIC,
            "gnn_recall_at_k": float("nan"), "winner": METHOD_HEURISTIC, "gnn_backend": gnn_model.gnn_backend(),
            "warnings": ["Too few edges to run hidden-edge recovery; heuristic surfaced by default."],
        }
    cols = _method_score_columns()
    acc: Dict[str, List[Tuple[float, float]]] = {m: [] for m in BENCHMARK_METHODS}
    warnings: List[str] = []
    n_hidden = max(1, int(round(len(edges) * hide_fraction)))
    mode_used = candidate_mode
    for r in range(n_repeats):
        rng = random.Random(seed + r)
        hidden = rng.sample(edges, n_hidden)
        reduced = pg.copy()
        reduced.remove_edges_from(hidden)
        pairs, mode_used = candidate_pairs(reduced, candidate_mode)
        scores, trained = score_all_methods(reduced, pairs, include_gnn=include_gnn, gnn_epochs=gnn_epochs, seed=seed + r)
        if include_gnn and trained is None:
            warnings.append("GNN unavailable or skipped for this graph; gnn metrics are NaN.")
        elif trained is not None and trained.warnings:
            warnings.extend(trained.warnings)
        for m, col in cols.items():
            if m == METHOD_GNN and (trained is None):
                acc[m].append((float("nan"), float("nan")))
            else:
                acc[m].append(_recall_metrics(scores, hidden, k, col))

    per_method = {}
    for m, vals in acc.items():
        rk = [v[0] for v in vals]
        rn = [v[1] for v in vals]
        per_method[m] = {
            "recall_at_k": float(np.nanmean(rk)) if not all(np.isnan(rk)) else float("nan"),
            "global_recall_at_n": float(np.nanmean(rn)) if not all(np.isnan(rn)) else float("nan"),
        }
    # Best heuristic variant is itself chosen by measurement (jaccard vs adamic_adar vs blend).
    heuristic_variants = {m: per_method[m]["recall_at_k"] for m in (METHOD_JACCARD, METHOD_ADAMIC_ADAR, METHOD_HEURISTIC)}
    best_variant = max(heuristic_variants, key=lambda m: (-1 if np.isnan(heuristic_variants[m]) else heuristic_variants[m]))
    h = heuristic_variants[best_variant]
    g = per_method[METHOD_GNN]["recall_at_k"]
    winner = METHOD_GNN if (not np.isnan(g) and not np.isnan(h) and g > h + 1e-9) else best_variant
    return {
        "k": k, "hide_fraction": hide_fraction, "n_repeats": n_repeats, "hidden_edges": n_hidden,
        "candidate_mode": mode_used, "per_method": per_method,
        "heuristic_recall_at_k": h, "heuristic_variant": best_variant,
        "gnn_recall_at_k": g, "winner": winner,
        "gnn_backend": gnn_model.gnn_backend(), "warnings": sorted(set(warnings)),
    }


# --------------------------------------------------------------------------- #
# Public orchestration
# --------------------------------------------------------------------------- #
def run_link_prediction(
    graph: nx.Graph,
    k: int = 10,
    location_events_df: Optional[pd.DataFrame] = None,
    hide_fraction: float = 0.2,
    seed: int = 42,
    n_repeats: int = 1,
    include_gnn: bool = True,
    gnn_epochs: int = gnn_model.DEFAULT_EPOCHS,
    top_n: int = 50,
) -> dict:
    """Predict hidden person-to-person links and benchmark every method.

    Steps: project ``graph`` to a person graph → run the hidden-edge-recovery
    benchmark → score all non-connected candidate pairs on the *full* graph
    with the heuristics and (if available) the GNN → surface the predictions
    of whichever method won the benchmark.

    Parameters
    ----------
    graph : nx.Graph
        Raw investigation graph or projected person graph.
    k : int
        K for per-node Recall@K in the benchmark.
    location_events_df : pd.DataFrame, optional
        ``person_id, location_id, timestamp`` rows for time-windowed co-location.
    hide_fraction, seed, n_repeats
        Benchmark settings (fraction of edges hidden, seed, repeats to average).
    include_gnn : bool
        Set ``False`` to skip the GNN entirely (heuristics only).
    gnn_epochs : int
        Training epochs for the GraphSAGE model.
    top_n : int
        Number of top predictions returned per method.

    Returns
    -------
    dict with keys
        ``heuristic_predictions`` – top-N predicted_links dicts, method
        ``"heuristic"`` (explanation carries jaccard / adamic_adar / common
        neighbours);
        ``gnn_predictions`` – top-N dicts with method ``"gnn"`` (empty list if
        the GNN was unavailable/skipped);
        ``benchmark`` – ``heuristic_recall_at_k, heuristic_variant,
        gnn_recall_at_k, k, winner`` plus ``per_method`` breakdown and
        ``global_recall_at_n``;
        ``surfaced_predictions`` – the winner's list (what the backend should
        store/display);
        ``predicted_links_rows`` – alias of ``surfaced_predictions`` (already
        shaped for the ``predicted_links`` table, minus ``analysis_run_id``);
        ``link_prediction_benchmark_rows`` – rows for the
        ``link_prediction_benchmark`` table (``method, recall_at_k, k_value``);
        ``scores`` – full candidate score table (DataFrame) for inspection;
        ``meta`` – candidate mode, counts, GNN backend, warnings.
    """
    pg = as_person_graph(graph, location_events_df=location_events_df)
    bench = hidden_edge_recovery(
        pg, hide_fraction=hide_fraction, k=k, seed=seed, n_repeats=n_repeats,
        include_gnn=include_gnn, gnn_epochs=gnn_epochs,
    )
    pairs, mode_used = candidate_pairs(pg, "auto")
    scores, trained = score_all_methods(pg, pairs, include_gnn=include_gnn, gnn_epochs=gnn_epochs, seed=seed)

    variant = bench.get("heuristic_variant", METHOD_HEURISTIC)
    heuristic_preds = scores_to_predictions(scores, variant, top_n=top_n)
    gnn_preds = scores_to_predictions(scores, METHOD_GNN, top_n=top_n) if trained is not None else []
    winner = bench["winner"] if gnn_preds else variant
    surfaced = gnn_preds if winner == METHOD_GNN else heuristic_preds

    bench_rows = [
        {"method": m, "recall_at_k": bench["per_method"][m]["recall_at_k"], "k_value": k}
        for m in BENCHMARK_METHODS
    ]
    warnings = list(bench.get("warnings", []))
    if include_gnn and trained is None:
        warnings.append("GNN not trained on the full graph (unavailable or graph too small); heuristic predictions surfaced.")
    return {
        "heuristic_predictions": heuristic_preds,
        "gnn_predictions": gnn_preds,
        "benchmark": bench,
        "surfaced_predictions": surfaced,
        "predicted_links_rows": surfaced,
        "link_prediction_benchmark_rows": bench_rows,
        "scores": scores,
        "meta": {
            "persons": len(person_ids(pg)),
            "edges": pg.number_of_edges(),
            "candidate_pairs": len(pairs),
            "candidate_mode": mode_used,
            "gnn_backend": gnn_model.gnn_backend(),
            "gnn_trained": trained is not None,
            "surfaced_method": winner,
            "warnings": sorted(set(warnings)),
        },
    }


def persons_in_both_methods(result: dict) -> set:
    """Persons appearing in BOTH the heuristic and GNN top predictions (feature 9)."""
    if not result.get("gnn_predictions"):
        return set()
    h = {p[k] for p in result["heuristic_predictions"] for k in ("source_person_id", "target_person_id")}
    g = {p[k] for p in result["gnn_predictions"] for k in ("source_person_id", "target_person_id")}
    return h & g
