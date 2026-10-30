"""Layer 1 — generic structural analytics (no training, pure graph math).

* :func:`run_centrality_analysis` – degree / betweenness / PageRank per person.
* :func:`run_community_detection` – Louvain community id per person.

Both functions are deterministic (fixed seeds) and recompute directly from
whatever graph they are given, so they behave identically on a 20-person
case and a 20,000-person case.  Betweenness is computed exactly for graphs up
to ``BETWEENNESS_EXACT_MAX_NODES`` nodes and *approximated* (seeded sampling
of ``BETWEENNESS_SAMPLE_K`` pivots) above that, because exact betweenness is
O(n·m) and becomes impractical on very large cases.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx
import pandas as pd

from .graph_utils import as_person_graph, person_ids

BETWEENNESS_EXACT_MAX_NODES = 2_000
BETWEENNESS_SAMPLE_K = 500
RANDOM_SEED = 42

CENTRALITY_COLUMNS = ["person_id", "degree_centrality", "betweenness_centrality", "pagerank", "rank"]
COMMUNITY_COLUMNS = ["person_id", "community_id"]


def run_centrality_analysis(
    graph: nx.Graph,
    location_events_df: Optional[pd.DataFrame] = None,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """Compute degree, betweenness and PageRank centrality for every person.

    Parameters
    ----------
    graph
        Raw investigation graph (PERSON/VEHICLE/LOCATION) or an already
        projected person graph (see :mod:`sih26189_analytics.graph_utils`).
    location_events_df
        Optional ``person_id, location_id, timestamp`` table used to build a
        time-windowed CO_LOCATED layer when ``graph`` is a raw graph.
    seed
        Random seed for the sampled betweenness approximation on large graphs.

    Returns
    -------
    pd.DataFrame
        Columns ``person_id, degree_centrality, betweenness_centrality,
        pagerank, rank`` — one row per person (isolated persons included,
        with zero centrality).  ``rank`` is 1 for the highest PageRank.
        Maps directly onto the ``person_metrics`` table (the backend adds
        ``analysis_run_id``; ``risk_score`` comes from Layer 3).
    """
    pg = as_person_graph(graph, location_events_df=location_events_df)
    ids = person_ids(pg)
    if not ids:
        return pd.DataFrame(columns=CENTRALITY_COLUMNS)

    degree = nx.degree_centrality(pg) if pg.number_of_nodes() > 1 else {n: 0.0 for n in pg}
    n = pg.number_of_nodes()
    if pg.number_of_edges() == 0:
        betweenness = {p: 0.0 for p in ids}
        pagerank = {p: 1.0 / n for p in ids}
    else:
        if n <= BETWEENNESS_EXACT_MAX_NODES:
            betweenness = nx.betweenness_centrality(pg, weight=None, normalized=True)
        else:
            betweenness = nx.betweenness_centrality(
                pg, k=min(BETWEENNESS_SAMPLE_K, n), weight=None, normalized=True, seed=seed
            )
        pagerank = nx.pagerank(pg, weight="weight", alpha=0.85, max_iter=500, tol=1e-08)

    df = pd.DataFrame(
        {
            "person_id": ids,
            "degree_centrality": [float(degree.get(p, 0.0)) for p in ids],
            "betweenness_centrality": [float(betweenness.get(p, 0.0)) for p in ids],
            "pagerank": [float(pagerank.get(p, 0.0)) for p in ids],
        }
    )
    df["rank"] = df["pagerank"].rank(ascending=False, method="first").astype(int)
    return df.sort_values("rank").reset_index(drop=True)[CENTRALITY_COLUMNS]


def run_community_detection(
    graph: nx.Graph,
    location_events_df: Optional[pd.DataFrame] = None,
    seed: int = RANDOM_SEED,
    resolution: float = 1.0,
) -> pd.DataFrame:
    """Assign every person to a Louvain community.

    Parameters
    ----------
    graph
        Raw investigation graph or projected person graph.
    location_events_df
        Optional co-location source (see :func:`run_centrality_analysis`).
    seed
        Louvain is stochastic; the seed makes results reproducible.
    resolution
        Louvain resolution parameter (>1 → more, smaller communities).

    Returns
    -------
    pd.DataFrame
        Columns ``person_id, community_id``.  Community ids are strings of
        the form ``"C00"``, ``"C01"`` … ordered by community size (largest
        first).  Isolated persons each form their own singleton community.
        Maps directly onto the ``community_memberships`` table.
    """
    pg = as_person_graph(graph, location_events_df=location_events_df)
    ids = person_ids(pg)
    if not ids:
        return pd.DataFrame(columns=COMMUNITY_COLUMNS)
    if pg.number_of_edges() == 0:
        communities = [{p} for p in ids]
    else:
        communities = list(
            nx.community.louvain_communities(pg, weight="weight", resolution=resolution, seed=seed)
        )
    communities = sorted(communities, key=lambda c: (-len(c), sorted(c)[0]))
    membership = {}
    for idx, members in enumerate(communities):
        cid = f"C{idx:02d}"
        for p in members:
            membership[p] = cid
    df = pd.DataFrame({"person_id": ids, "community_id": [membership[p] for p in ids]})
    return df[COMMUNITY_COLUMNS]
