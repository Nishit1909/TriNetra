import logging
from pathlib import Path
from time import perf_counter
import xgboost as xgb
import json as _json

import networkx as nx
import pandas as pd

from app.analytics import (
    RiskModel,
    engineer_case_features,
    run_centrality_analysis,
    run_community_detection,
    run_link_prediction,
    score_case_risk,
)
from app.services.graph import get_graph
from app.services.people import get_person

logger = logging.getLogger(__name__)


def get_analytics_overview(limit: int | None = None, person_id: str | None = None) -> dict:
    started = perf_counter()
    errors: dict[str, str] = {}

    if person_id is not None:
        logger.info("Checking requested analytics person: %s", person_id)
        if get_person(person_id) is None:
            return {"not_found": True}

    logger.info("Loading investigation graph from Neo4j")
    graph_data = get_graph()
    graph = _to_networkx_graph(graph_data)
    graph_counts = graph_data["counts"]

    logger.info("Running centrality analysis")
    centrality = _run_stage(
        "centrality", errors, lambda: run_centrality_analysis(graph), pd.DataFrame()
    )

    logger.info("Running community detection")
    communities = _run_stage(
        "community_detection", errors, lambda: run_community_detection(graph), pd.DataFrame()
    )

    logger.info("Running link prediction")
    link_prediction = _run_stage(
        "link_prediction",
        errors,
        lambda: run_link_prediction(graph, include_gnn=True, top_n=limit or 50),
        {},
    )

    risk = _risk_stage(graph, centrality, communities, link_prediction, errors)

    centrality_rows = _records(centrality)
    community_rows = _records(communities)
    link_rows = link_prediction.get("predicted_links_rows", [])

    if person_id is not None:
        centrality_rows = _filter_person(centrality_rows, person_id)
        community_rows = _filter_person(community_rows, person_id)
        link_rows = [
            row
            for row in link_rows
            if person_id in (row.get("source_person_id"), row.get("target_person_id"))
        ]

    if limit is not None:
        centrality_rows = centrality_rows[:limit]
        community_rows = community_rows[:limit]
        link_rows = link_rows[:limit]

    elapsed = round(perf_counter() - started, 3)
    return {
        "status": "ok",
        "graph": graph_counts,
        "centrality": centrality_rows,
        "communities": community_rows,
        "link_predictions": link_rows,
        "risk": risk,
        "errors": errors,
        "execution_time_seconds": elapsed,
    }


def _to_networkx_graph(graph_data: dict) -> nx.Graph:
    graph = nx.Graph()
    for node in graph_data["nodes"]:
        graph.add_node(node["id"], node_type=node.get("type"), name=node.get("label"))
    for edge in graph_data["edges"]:
        graph.add_edge(
            edge["source"],
            edge["target"],
            relationship_type=edge["type"],
        )
    return graph


def _run_stage(name: str, errors: dict[str, str], operation, fallback):
    try:
        return operation()
    except Exception:
        logger.exception("Analytics stage failed: %s", name)
        errors[name] = "stage_failed"
        return fallback


def _risk_stage(
    graph: nx.Graph,
    centrality: pd.DataFrame,
    communities: pd.DataFrame,
    link_prediction: dict,
    errors: dict[str, str],
) -> dict:
    logger.info("Loading persisted risk model")

    booster_path = Path(__file__).parents[2] / "models" / "risk_model_booster.json"
    metadata_path = Path(__file__).parents[2] / "models" / "risk_model_metadata.json"
    try:
        with open(metadata_path) as f:
            meta = _json.load(f)
        xgb_model = xgb.XGBClassifier()
        xgb_model.load_model(str(booster_path))
        model = RiskModel(
            model=xgb_model,
            feature_columns=meta["feature_columns"],
            model_version=meta["model_version"],
            trained_at=meta["trained_at"],
            training_dataset=meta["training_dataset"],
            n_train=meta["n_train"],
            validation=meta["validation"],
            feature_importance=meta["feature_importance"],
            notes=meta["notes"],
        )
        features = engineer_case_features(
            graph,
            centrality,
            communities,
            link_prediction_result=link_prediction,
        )
        results = score_case_risk(model, features)
        return {
            "status": "available",
            "results": _records(results),
            "demo_only": True,
        }
    except Exception:
        logger.exception("Risk model loading or scoring failed")
        errors["risk"] = "persisted_model_unavailable"
        return {
            "status": "unavailable",
            "reason": "persisted_model_unavailable",
            "results": [],
            "demo_only": True,
        }


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _filter_person(rows: list[dict], person_id: str) -> list[dict]:
    return [row for row in rows if row.get("person_id") == person_id]