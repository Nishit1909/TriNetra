from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.graph import get_graph

router = APIRouter(prefix="/api/graph", tags=["graph"])


class GraphNode(BaseModel):
    id: str
    type: str | None = None
    label: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphCounts(BaseModel):
    nodes: int
    edges: int


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    counts: GraphCounts


NodeType = Literal["PERSON", "VEHICLE", "LOCATION"]


@router.get("", response_model=GraphResponse)
def read_graph(
    limit: Annotated[int | None, Query(gt=0, le=100_000)] = None,
    node_type: NodeType | None = None,
) -> dict:
    try:
        return get_graph(limit=limit, node_type=node_type)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve the graph.",
        ) from error