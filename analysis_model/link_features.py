"""Structural pair features shared by the app (run_case_analysis) and the training/benchmark scripts.

One implementation for both, so the shipped ranker sees exactly the features it was trained and evaluated on.
All features use the UNWEIGHTED graph structure; each is converted to a percentile within the case
(`to_percentiles`) so the learned ranker transfers across networks of different size.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pandas as pd

FEATURES = ["cn", "aa", "ra", "jaccard", "pa", "katz3", "local_path", "ppr", "inv_distance", "same_community",
            "deg_min", "deg_max", "clust_min", "clust_max"]


def ppr_matrix(G: nx.Graph, nodes: list) -> np.ndarray:
    """Symmetrised personalised PageRank (restart 0.15) on unweighted transitions."""
    A = nx.to_numpy_array(G, nodelist=nodes, weight=None)
    deg = A.sum(1)
    P = np.divide(A, deg[:, None], out=np.zeros_like(A), where=deg[:, None] > 0)
    M = 0.15 * np.linalg.inv(np.eye(len(nodes)) - 0.85 * P.T)
    return M + M.T


def pair_features(G: nx.Graph, pairs: list[tuple], seed: int = 42) -> pd.DataFrame:
    nodes = list(G)
    idx = {v: i for i, v in enumerate(nodes)}
    deg = dict(G.degree())
    nbr = {v: set(G[v]) for v in G}
    A = nx.to_numpy_array(G, nodelist=nodes, weight=None)
    A2 = A @ A
    A3 = A2 @ A
    katz = 0.05 * A + 0.05 ** 2 * A2 + 0.05 ** 3 * A3
    lp = A2 + 0.01 * A3
    ppr = ppr_matrix(G, nodes) if G.number_of_edges() else np.zeros_like(A)
    clust = nx.clustering(G)
    comm = {}
    if G.number_of_edges():
        for i, c in enumerate(nx.community.louvain_communities(G, seed=seed)):
            for v in c:
                comm[v] = i
    dist = dict(nx.all_pairs_shortest_path_length(G, cutoff=6))
    rows = []
    for a, b in pairs:
        cn = nbr[a] & nbr[b]
        un = nbr[a] | nbr[b]
        i, j = idx[a], idx[b]
        rows.append((
            len(cn),
            sum(1 / math.log(deg[z]) for z in cn if deg[z] > 1),
            sum(1 / deg[z] for z in cn if deg[z] > 0),
            len(cn) / len(un) if un else 0.0,
            math.log1p(deg[a] * deg[b]),
            katz[i, j], lp[i, j], ppr[i, j],
            1.0 / dist[a][b] if b in dist.get(a, {}) else 0.0,
            float(comm.get(a, -1) == comm.get(b, -2)),
            min(deg[a], deg[b]), max(deg[a], deg[b]),
            min(clust[a], clust[b]), max(clust[a], clust[b]),
        ))
    return pd.DataFrame(rows, columns=FEATURES)


def to_percentiles(f: pd.DataFrame) -> pd.DataFrame:
    return f.rank(pct=True, method="average")
