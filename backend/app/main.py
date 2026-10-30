from fastapi import FastAPI

from app.config import settings
from app.db.neo4j import check_connectivity as check_neo4j_connectivity
from app.db.supabase import check_connectivity as check_supabase_connectivity
from app.routes.analytics import router as analytics_router
from app.routes.cases import router as cases_router
from app.routes.graph import router as graph_router
from app.routes.ingestion import router as ingestion_router
from app.routes.people import router as people_router

app = FastAPI(title="SIH26189 Backend")
app.include_router(cases_router)
app.include_router(people_router)
app.include_router(graph_router)
app.include_router(analytics_router)
app.include_router(ingestion_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/database")
def database_health() -> dict[str, dict[str, str]]:
    return {
        "supabase": _check_database(
            settings.supabase_database_url,
            check_supabase_connectivity,
        ),
        "neo4j": _check_database(
            settings.neo4j_uri,
            check_neo4j_connectivity,
        ),
    }


def _check_database(
    configured_value: str,
    check_connectivity: callable,
) -> dict[str, str]:
    if not configured_value:
        return {"status": "not_configured"}

    try:
        check_connectivity()
    except Exception:
        return {"status": "error"}

    return {"status": "ok"}
