"""sih26189_analytics — analytics/ML layer for SIH26189 (criminal network analysis).

A pure, framework-agnostic computational library.  It never talks to a
database: the backend hands in a NetworkX graph and pandas DataFrames and
receives DataFrames / dicts whose columns match the Supabase tables
(``person_metrics``, ``community_memberships``, ``predicted_links``,
``link_prediction_benchmark``, ``risk_model_validation``).  The backend adds
``analysis_run_id`` on insert.

Public API (the functions the backend team calls)
-------------------------------------------------
1. :func:`run_centrality_analysis`          – Layer 1, PageRank / betweenness / degree
2. :func:`run_community_detection`          – Layer 1, Louvain communities
3. :func:`run_link_prediction`              – Layer 2, heuristics + GNN + benchmark
4. :func:`train_risk_model`                 – Layer 3, XGBoost on Elliptic (k-fold CV)
5. :func:`engineer_case_features`           – Layer 3, percentile/ratio feature table
6. :func:`score_case_risk`                  – Layer 3, demo-only risk score per person
7. :func:`run_generalization_stress_test`   – synthetic-shape robustness test
8. :func:`tune_entity_resolution_threshold` – precision/recall curve for name matching

Convenience: :func:`run_full_pipeline` runs 1-3 and 5-6 in one call and
returns every table-shaped output together; :func:`assemble_person_metrics`
merges centrality + risk into ``person_metrics`` rows.

Minimal usage::

    import networkx as nx
    from sih26189_analytics import run_full_pipeline, RiskModel

    graph = ...  # nx.Graph from Neo4j: node_type / relationship_type attributes
    model = RiskModel.load("risk_model_elliptic.joblib")
    out = run_full_pipeline(graph, risk_model=model, cdr_df=cdr, location_events_df=loc)
    out["person_metrics"]              # DataFrame → insert into person_metrics
    out["community_memberships"]       # DataFrame
    out["predicted_links"]             # list[dict]
    out["link_prediction_benchmark"]   # list[dict]
    model.risk_model_validation_row()  # dict → risk_model_validation
"""

from __future__ import annotations

from typing import Dict, Optional

import networkx as nx
import pandas as pd

from .centrality import run_centrality_analysis, run_community_detection
from .entity_resolution import match_score, tune_entity_resolution_threshold
from .graph_utils import as_person_graph, build_person_graph, layer_counts
from .link_prediction import gnn_available, gnn_backend, hidden_edge_recovery, run_link_prediction
from .risk_scoring import (
    MODEL_FEATURES,
    SPEC_FEATURES,
    RiskModel,
    assemble_person_metrics,
    engineer_case_features,
    feature_availability,
    load_elliptic,
    make_synthetic_elliptic_like_table,
    risk_explanations,
    score_case_risk,
    train_risk_model,
)
from .stress_test import run_generalization_stress_test, summarize_stress_report

__version__ = "1.0.0"

__all__ = [
    # 8 contracted functions
    "run_centrality_analysis", "run_community_detection", "run_link_prediction", "train_risk_model",
    "engineer_case_features", "score_case_risk", "run_generalization_stress_test", "tune_entity_resolution_threshold",
    # orchestration / helpers
    "run_full_pipeline", "assemble_person_metrics", "risk_explanations", "feature_availability",
    "build_person_graph", "as_person_graph", "layer_counts", "hidden_edge_recovery",
    "gnn_available", "gnn_backend", "match_score", "summarize_stress_report",
    "RiskModel", "load_elliptic", "make_synthetic_elliptic_like_table", "MODEL_FEATURES", "SPEC_FEATURES",
]


def run_full_pipeline(
    graph: nx.Graph,
    risk_model: Optional[RiskModel] = None,
    cdr_df: Optional[pd.DataFrame] = None,
    location_events_df: Optional[pd.DataFrame] = None,
    transactions_df: Optional[pd.DataFrame] = None,
    k: int = 10,
    include_gnn: bool = True,
    seed: int = 42,
    top_n: int = 50,
) -> Dict:
    """Run Layers 1-3 end to end and return every table-shaped output.

    Parameters
    ----------
    graph
        Raw investigation graph from Neo4j (nodes with ``node_type``, edges
        with ``relationship_type``) or an already projected person graph.
    risk_model
        Trained :class:`RiskModel`.  When ``None``, risk columns are NaN and
        ``person_metrics`` is still returned.
    cdr_df, location_events_df, transactions_df
        Optional evidence tables (see :func:`engineer_case_features`).
    k, include_gnn, seed, top_n
        Link-prediction settings.

    Returns
    -------
    dict
        ``person_metrics`` (DataFrame), ``community_memberships`` (DataFrame),
        ``predicted_links`` (list[dict]), ``link_prediction_benchmark``
        (list[dict]), ``case_features`` (DataFrame), ``risk_explanations``
        (list[dict] or []), ``link_prediction`` (full Layer-2 result),
        ``feature_availability`` (dict), ``meta`` (graph sizes, layers,
        surfaced method, GNN status, warnings).  Add ``analysis_run_id`` to
        each table on insert.
    """
    pg = as_person_graph(graph, location_events_df=location_events_df)
    centrality = run_centrality_analysis(pg, seed=seed)
    communities = run_community_detection(pg, seed=seed)
    lp = run_link_prediction(pg, k=k, include_gnn=include_gnn, seed=seed, top_n=top_n)
    features = engineer_case_features(
        pg, centrality, communities, transactions_df=transactions_df, cdr_df=cdr_df,
        location_events_df=location_events_df, link_prediction_result=lp,
    )
    if risk_model is not None:
        risk = score_case_risk(risk_model, features)
        explanations = risk_explanations(risk_model, features)
    else:
        risk, explanations = None, []
    person_metrics = assemble_person_metrics(centrality, risk)
    return {
        "person_metrics": person_metrics,
        "community_memberships": communities,
        "predicted_links": lp["predicted_links_rows"],
        "link_prediction_benchmark": lp["link_prediction_benchmark_rows"],
        "case_features": features,
        "risk_explanations": explanations,
        "link_prediction": lp,
        "feature_availability": feature_availability(features),
        "meta": {
            "persons": pg.number_of_nodes(),
            "person_edges": pg.number_of_edges(),
            "layers": layer_counts(pg),
            "surfaced_link_method": lp["meta"]["surfaced_method"],
            "gnn_trained": lp["meta"]["gnn_trained"],
            "gnn_backend": lp["meta"]["gnn_backend"],
            "risk_model_version": risk_model.model_version if risk_model else None,
            "risk_scores_are_demo_only": True,
            "warnings": lp["meta"]["warnings"],
        },
    }
