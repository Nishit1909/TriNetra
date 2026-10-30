"""Graph projection utilities.

Every analytics function in this package operates on a **person-to-person
multi-layer graph**.  The backend hands us the raw investigation graph that
lives in Neo4j — a heterogeneous graph with PERSON / VEHICLE / LOCATION nodes
and COMMUNICATES_WITH / VISITED / ASSIGNED_TO relationships.  This module
projects that heterogeneous graph onto persons only, producing one undirected
edge per person pair that is linked through *any* evidence layer:

* ``COMMUNICATES_WITH`` – the two persons communicated directly.
* ``CO_LOCATED``       – the two persons were at the same *rare* location
  (optionally within the same time window, when ``location_events_df`` is
  supplied).  Locations visited by many people (offices, main roads) are
  excluded because co-presence there carries no investigative signal.
* ``SHARED_VEHICLE``   – the two persons were assigned the same vehicle.

Each projected edge carries:

* ``layers``  – sorted list of the evidence layers it appears in,
* ``weight``  – ``len(layers)`` (cross-layer evidence counts more; this is the
  weight used by PageRank / Louvain),
* ``comm_count`` / ``colocation_count`` / ``shared_vehicle_count`` – raw
  supporting counts, kept for explanations.

Expected input conventions (documented for the backend team)
-----------------------------------------------------------
* Node attribute ``node_type`` in ``{"PERSON", "VEHICLE", "LOCATION"}``.  If the
  attribute is missing on every node, the graph is assumed to be person-only
  and is used as-is (its edges are treated as the COMMUNICATES_WITH layer).
* Edge attribute ``relationship_type`` in
  ``{"COMMUNICATES_WITH", "VISITED", "ASSIGNED_TO"}``.  Missing → treated as
  COMMUNICATES_WITH.
* Person node ids are the canonical ``person_id`` values (e.g. ``"P0001"``).
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from typing import Dict, FrozenSet, Iterable, Optional, Set, Tuple

import networkx as nx
import pandas as pd

PERSON = "PERSON"
VEHICLE = "VEHICLE"
LOCATION = "LOCATION"

LAYER_COMM = "COMMUNICATES_WITH"
LAYER_COLOC = "CO_LOCATED"
LAYER_VEHICLE = "SHARED_VEHICLE"
ALL_LAYERS = (LAYER_COMM, LAYER_COLOC, LAYER_VEHICLE)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def node_types(graph: nx.Graph) -> Dict[str, str]:
    """Return ``{node_id: node_type}``, defaulting to PERSON when the attribute is absent."""
    return {n: (d.get("node_type") or PERSON) for n, d in graph.nodes(data=True)}


def is_person_graph(graph: nx.Graph) -> bool:
    """True when every node is a PERSON (or has no ``node_type`` at all)."""
    return all(t == PERSON for t in node_types(graph).values())


def person_ids(graph: nx.Graph) -> list:
    """Sorted list of PERSON node ids in ``graph`` (works for raw or projected graphs)."""
    return sorted(n for n, t in node_types(graph).items() if t == PERSON)


def _relationship(d: dict) -> str:
    return d.get("relationship_type") or d.get("type") or LAYER_COMM


def _pairs(members: Iterable[str]) -> Iterable[Tuple[str, str]]:
    return itertools.combinations(sorted(set(members)), 2)


# --------------------------------------------------------------------------- #
# Co-location layer
# --------------------------------------------------------------------------- #
def colocation_pairs_from_events(
    location_events_df: pd.DataFrame,
    time_window_minutes: int = 15,
    max_location_visitors: int = 5,
    min_cooccurrences: int = 3,
    person_col: str = "person_id",
    location_col: str = "location_id",
    time_col: str = "timestamp",
) -> Dict[Tuple[str, str], float]:
    """Time-windowed co-location at rare locations.

    Two persons are co-located when they have an event at the same location
    within the same ``time_window_minutes`` bucket.  Only locations visited by
    at most ``max_location_visitors`` distinct persons are considered, which
    removes shared offices / commuter roads.  A pair is kept when it has at
    least ``min_cooccurrences`` such events.

    Returns ``{(person_a, person_b): cooccurrence_count}``.
    """
    if location_events_df is None or location_events_df.empty:
        return {}
    df = location_events_df[[person_col, location_col, time_col]].dropna(subset=[person_col])
    if df.empty:
        return {}
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col])
    if df.empty:
        return {}
    n_visitors = df.groupby(location_col)[person_col].nunique()
    rare = n_visitors[n_visitors <= max_location_visitors].index
    df = df[df[location_col].isin(rare)]
    if df.empty:
        return {}
    df["_bin"] = df[time_col].dt.floor(f"{int(time_window_minutes)}min")
    groups = df.groupby([location_col, "_bin"])[person_col].agg(lambda s: frozenset(s))
    counts: Counter = Counter()
    for members in groups:
        if len(members) > 1:
            for a, b in _pairs(members):
                counts[(a, b)] += 1
    return {pair: float(c) for pair, c in counts.items() if c >= min_cooccurrences}


def colocation_pairs_from_graph(
    graph: nx.Graph,
    max_location_visitors: int = 5,
    min_shared_locations: int = 3,
) -> Dict[Tuple[str, str], float]:
    """Graph-only co-location fallback (no timestamps available).

    Uses VISITED edges: two persons are co-located when they both visited the
    same *rare* location (≤ ``max_location_visitors`` distinct person
    visitors).  Kept when they share at least ``min_shared_locations`` such
    locations.  Weaker than the time-windowed version, used only when the
    backend does not supply ``location_events_df``.
    """
    types = node_types(graph)
    visitors: Dict[str, Set[str]] = defaultdict(set)
    for u, v, d in graph.edges(data=True):
        if _relationship(d) != "VISITED":
            continue
        # VISITED edges are person/vehicle -> location; orientation may vary.
        if types.get(u) == PERSON and types.get(v) == LOCATION:
            visitors[v].add(u)
        elif types.get(v) == PERSON and types.get(u) == LOCATION:
            visitors[u].add(v)
    counts: Counter = Counter()
    for members in visitors.values():
        if 1 < len(members) <= max_location_visitors:
            for a, b in _pairs(members):
                counts[(a, b)] += 1
    return {pair: float(c) for pair, c in counts.items() if c >= min_shared_locations}


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
def build_person_graph(
    graph: nx.Graph,
    location_events_df: Optional[pd.DataFrame] = None,
    time_window_minutes: int = 15,
    max_location_visitors: int = 5,
    min_cooccurrences: int = 3,
) -> nx.Graph:
    """Project the heterogeneous investigation graph onto a person-only multi-layer graph.

    Parameters
    ----------
    graph
        Raw graph (PERSON/VEHICLE/LOCATION nodes) **or** an already person-only
        graph.  Person-only graphs are returned as a copy with layer metadata
        filled in.
    location_events_df
        Optional table with ``person_id, location_id, timestamp`` rows.  When
        given, the CO_LOCATED layer is time-windowed (much stronger signal).
        When ``None``, the layer falls back to shared rare VISITED locations.
    time_window_minutes, max_location_visitors, min_cooccurrences
        Co-location parameters, see :func:`colocation_pairs_from_events`.

    Returns
    -------
    nx.Graph
        Undirected person graph.  Every PERSON node from the input is present
        (isolated persons included).  Edge attributes: ``layers``, ``weight``,
        ``comm_count``, ``colocation_count``, ``shared_vehicle_count``.
    """
    types = node_types(graph)
    persons = [n for n, t in types.items() if t == PERSON]
    pg = nx.Graph()
    for p in persons:
        attrs = dict(graph.nodes[p]) if p in graph else {}
        attrs["node_type"] = PERSON
        pg.add_node(p, **attrs)

    comm_counts: Counter = Counter()
    vehicle_members: Dict[str, Set[str]] = defaultdict(set)

    for u, v, d in graph.edges(data=True):
        rel = _relationship(d)
        tu, tv = types.get(u), types.get(v)
        if tu == PERSON and tv == PERSON:
            if rel in (LAYER_COMM, LAYER_COLOC, LAYER_VEHICLE) or rel not in ("VISITED", "ASSIGNED_TO"):
                key = tuple(sorted((u, v)))
                if rel == LAYER_COLOC:
                    _add_layer(pg, key, LAYER_COLOC, float(d.get("weight", 1.0)), "colocation_count")
                elif rel == LAYER_VEHICLE:
                    _add_layer(pg, key, LAYER_VEHICLE, float(d.get("weight", 1.0)), "shared_vehicle_count")
                else:
                    comm_counts[key] += int(d.get("count", 1))
        elif rel == "ASSIGNED_TO":
            if tu == VEHICLE and tv == PERSON:
                vehicle_members[u].add(v)
            elif tv == VEHICLE and tu == PERSON:
                vehicle_members[v].add(u)

    for key, c in comm_counts.items():
        _add_layer(pg, key, LAYER_COMM, float(c), "comm_count")

    for members in vehicle_members.values():
        for a, b in _pairs(members):
            _add_layer(pg, (a, b), LAYER_VEHICLE, 1.0, "shared_vehicle_count")

    if location_events_df is not None and not location_events_df.empty:
        coloc = colocation_pairs_from_events(
            location_events_df,
            time_window_minutes=time_window_minutes,
            max_location_visitors=max_location_visitors,
            min_cooccurrences=min_cooccurrences,
        )
    else:
        coloc = colocation_pairs_from_graph(
            graph, max_location_visitors=max_location_visitors, min_shared_locations=min_cooccurrences
        )
    for (a, b), c in coloc.items():
        if a in pg and b in pg:
            _add_layer(pg, (a, b), LAYER_COLOC, c, "colocation_count")

    for _, _, d in pg.edges(data=True):
        d["layers"] = sorted(d["layers"])
        d["weight"] = float(len(d["layers"]))
    return pg


def _add_layer(pg: nx.Graph, key: Tuple[str, str], layer: str, strength: float, count_attr: str) -> None:
    a, b = key
    if a == b:
        return
    if not pg.has_edge(a, b):
        pg.add_edge(a, b, layers=set(), comm_count=0.0, colocation_count=0.0, shared_vehicle_count=0.0)
    d = pg[a][b]
    if isinstance(d["layers"], list):
        d["layers"] = set(d["layers"])
    d["layers"].add(layer)
    d[count_attr] = d.get(count_attr, 0.0) + strength


def as_person_graph(graph: nx.Graph, location_events_df: Optional[pd.DataFrame] = None, **kwargs) -> nx.Graph:
    """Return ``graph`` if it is already a projected person graph, else project it.

    A graph is considered already-projected when every node is a PERSON and
    every edge carries a ``layers`` attribute.
    """
    if is_person_graph(graph) and all("layers" in d for _, _, d in graph.edges(data=True)):
        return graph
    return build_person_graph(graph, location_events_df=location_events_df, **kwargs)


def layer_counts(person_graph: nx.Graph) -> Dict[str, int]:
    """Number of edges present in each evidence layer."""
    c: Counter = Counter()
    for _, _, d in person_graph.edges(data=True):
        for layer in d.get("layers", []):
            c[layer] += 1
    return dict(c)


def idf_weight(n_visitors: int) -> float:
    """Rarity weight used when ranking co-location evidence in explanations."""
    return 1.0 / math.log(1.0 + max(n_visitors, 1))
