"""Layer 2 — heuristic link prediction (Jaccard coefficient, Adamic-Adar index).

These scores need **no training** and are computed live from the person graph,
so they scale to any case size and are the production default.  The combined
heuristic score (mean of the two max-normalised indices) is what is compared
against the GNN in :mod:`.benchmark`.

Note on ``probability``: heuristic scores are *normalised ranking scores in
[0, 1]*, not calibrated probabilities.  The ``explanation`` dict on every
prediction spells this out so the dashboard never presents it as a
likelihood claim.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

import networkx as nx
import pandas as pd

METHOD_JACCARD = "jaccard"
METHOD_ADAMIC_ADAR = "adamic_adar"
METHOD_HEURISTIC = "heuristic"  # combined score surfaced by default
PREDICTED_RELATIONSHIP_TYPE = "ASSOCIATED_WITH"

Pair = Tuple[str, str]


def candidate_pairs(pg: nx.Graph, nodes: Optional[Iterable[str]] = None) -> List[Pair]:
    """All unordered person pairs that are *not* directly connected in ``pg``."""
    nodes = sorted(nodes) if nodes is not None else sorted(pg.nodes())
    out: List[Pair] = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if not pg.has_edge(a, b):
                out.append((a, b))
    return out


def heuristic_scores(pg: nx.Graph, pairs: Optional[List[Pair]] = None) -> pd.DataFrame:
    """Jaccard, Adamic-Adar, common-neighbour count and a combined score per pair.

    Returns a DataFrame with columns
    ``source_person_id, target_person_id, common_neighbors, jaccard,
    adamic_adar, jaccard_norm, adamic_adar_norm, heuristic_score``
    sorted by ``heuristic_score`` descending.  Pairs with zero common
    neighbours score 0 on every index.
    """
    if pairs is None:
        pairs = candidate_pairs(pg)
    if not pairs:
        return pd.DataFrame(
            columns=[
                "source_person_id", "target_person_id", "common_neighbors", "jaccard",
                "adamic_adar", "jaccard_norm", "adamic_adar_norm", "heuristic_score",
            ]
        )
    # Unweighted simple-graph view for the standard indices.
    simple = nx.Graph()
    simple.add_nodes_from(pg.nodes())
    simple.add_edges_from(pg.edges())

    cn: Dict[Pair, int] = {}
    jac: Dict[Pair, float] = {}
    aa: Dict[Pair, float] = {}
    for a, b in pairs:
        na, nb = set(simple[a]), set(simple[b])
        common = na & nb
        cn[(a, b)] = len(common)
        union = len(na | nb)
        jac[(a, b)] = (len(common) / union) if union else 0.0
        aa[(a, b)] = sum(1.0 / math.log(simple.degree(w)) for w in common if simple.degree(w) > 1)

    df = pd.DataFrame(
        {
            "source_person_id": [a for a, _ in pairs],
            "target_person_id": [b for _, b in pairs],
            "common_neighbors": [cn[p] for p in pairs],
            "jaccard": [jac[p] for p in pairs],
            "adamic_adar": [aa[p] for p in pairs],
        }
    )
    jmax = df["jaccard"].max() or 1.0
    amax = df["adamic_adar"].max() or 1.0
    df["jaccard_norm"] = df["jaccard"] / jmax
    df["adamic_adar_norm"] = df["adamic_adar"] / amax
    df["heuristic_score"] = (df["jaccard_norm"] + df["adamic_adar_norm"]) / 2.0
    return df.sort_values(["heuristic_score", "common_neighbors"], ascending=False).reset_index(drop=True)


def scores_to_predictions(
    scores: pd.DataFrame,
    method: str = METHOD_HEURISTIC,
    top_n: Optional[int] = None,
    min_score: float = 0.0,
) -> List[dict]:
    """Convert a score table into ``predicted_links``-shaped dicts.

    Each dict has ``source_person_id, target_person_id,
    predicted_relationship_type, method, probability, explanation,
    review_status``; ``analysis_run_id`` is added by the backend.
    """
    col = {
        METHOD_HEURISTIC: "heuristic_score",
        METHOD_JACCARD: "jaccard_norm",
        METHOD_ADAMIC_ADAR: "adamic_adar_norm",
        "gnn": "gnn_score",
    }[method]
    df = scores[scores[col] > min_score].sort_values(col, ascending=False)
    if top_n is not None:
        df = df.head(top_n)
    preds = []
    for row in df.itertuples(index=False):
        r = row._asdict()
        explanation = {
            "score_type": "normalised ranking score in [0,1] (not a calibrated probability)"
            if method != "gnn"
            else "GNN sigmoid link score (validated only via hidden-edge recovery)",
            "common_neighbors": int(r.get("common_neighbors", 0)),
            "jaccard": round(float(r.get("jaccard", 0.0)), 6),
            "adamic_adar": round(float(r.get("adamic_adar", 0.0)), 6),
        }
        if "gnn_score" in r and r["gnn_score"] is not None and not pd.isna(r["gnn_score"]):
            explanation["gnn_score"] = round(float(r["gnn_score"]), 6)
        preds.append(
            {
                "source_person_id": r["source_person_id"],
                "target_person_id": r["target_person_id"],
                "predicted_relationship_type": PREDICTED_RELATIONSHIP_TYPE,
                "method": method,
                "probability": round(float(r[col]), 6),
                "explanation": explanation,
                "review_status": "pending",
            }
        )
    return preds
