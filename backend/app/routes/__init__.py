from app.routes.cases import router as cases_router
from app.routes.graph import router as graph_router
from app.routes.analytics import router as analytics_router
from app.routes.ingestion import router as ingestion_router
from app.routes.people import router as people_router

__all__ = ["cases_router", "people_router", "graph_router", "analytics_router", "ingestion_router"]
