from typing import Any, Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.analytics_persistence import (
    get_latest_analytics_results,
    persist_analytics_results,
)
from app.services.analytics_service import get_analytics_overview

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class RiskOverview(BaseModel):
    status: str
    results: list[dict[str, Any]]
    demo_only: bool = True
    reason: str | None = None


class AnalyticsOverview(BaseModel):
    status: str
    graph: dict[str, int]
    centrality: list[dict[str, Any]]
    communities: list[dict[str, Any]]
    link_predictions: list[dict[str, Any]]
    risk: RiskOverview
    errors: dict[str, str]
    execution_time_seconds: float


class AnalyticsRunResponse(BaseModel):
    status: str
    analysis_run_id: str
    graph: dict[str, int]
    results: dict[str, int]
    risk: dict[str, Any]
    execution_time_seconds: float


class PersistedAnalyticsResponse(BaseModel):
    analysis_run: dict[str, Any]
    person_metrics: list[dict[str, Any]]
    community_memberships: list[dict[str, Any]]
    predicted_links: list[dict[str, Any]]
    risk: dict[str, Any]


@router.get("/overview", response_model=AnalyticsOverview)
def read_analytics_overview(
    limit: Annotated[int | None, Query(gt=0, le=1000)] = None,
    person_id: str | None = None,
) -> dict:
    try:
        result = get_analytics_overview(limit=limit, person_id=person_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to compute analytics overview.",
        ) from error

    if result.get("not_found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person not found.",
        )

    return result


@router.post("/run", response_model=AnalyticsRunResponse)
def run_analytics() -> dict:
    try:
        overview = get_analytics_overview()
        persisted = persist_analytics_results(overview)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to run and persist analytics.",
        ) from error

    return {
        "status": "completed",
        "analysis_run_id": str(persisted["analysis_run_id"]),
        "graph": overview["graph"],
        "results": {
            "person_metrics": persisted["person_metrics"],
            "community_memberships": persisted["community_memberships"],
            "predicted_links": persisted["predicted_links"],
        },
        "risk": {"status": persisted["risk_status"]},
        "execution_time_seconds": overview["execution_time_seconds"],
    }


@router.get("/results", response_model=PersistedAnalyticsResponse | None)
def read_latest_analytics_results(
    limit: Annotated[int | None, Query(gt=0, le=1000)] = None,
) -> dict | None:
    try:
        return get_latest_analytics_results(limit=limit)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve persisted analytics results.",
        ) from error