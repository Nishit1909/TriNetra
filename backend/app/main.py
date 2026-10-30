"""The live API: scoped evidence, versioned model runs and bounded graphs."""
from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.neo4j import check_connectivity, close_driver
from app.investigation.common import connect
from app.investigation import analysis, cases, evidence, graph, reviews
from app.security import authorize_case, get_principal, validate_runtime_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    validate_runtime_settings()
    yield
    close_driver()


app = FastAPI(title='SIH26189 Investigation API', version='2.0.0', lifespan=lifespan,
    description='Case-scoped source evidence and versioned analysis. Scores are investigative leads, not criminality probabilities.')
app.add_middleware(CORSMiddleware,
    allow_origins=[origin.strip().rstrip('/') for origin in settings.cors_origins.split(',') if origin.strip()],
    allow_credentials=False, allow_methods=['GET','POST','OPTIONS'], allow_headers=['Authorization','Content-Type','Accept'])
for router in (cases.router,evidence.router,analysis.router,graph.router,reviews.router):
    app.include_router(router, dependencies=[Depends(authorize_case)])


@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    return response


@app.exception_handler(Exception)
async def operation_failed(request: Request, error: Exception):
    identity = getattr(request.state,'request_id',None)
    logger.error('Backend request failed request_id=%s error_type=%s',identity,type(error).__name__)
    return JSONResponse(status_code=503, headers={'X-Request-ID':identity or ''}, content={'detail':'Backend operation failed. Inspect server logs using the request ID.','request_id':identity})


@app.get('/health', tags=['health'])
def health():
    return {'status':'ok','api_version':'2.0.0'}


@app.get('/health/database', tags=['health'])
def readiness():
    checks = {}
    try:
        with connect() as conn:
            conn.execute('SELECT 1 FROM inv.cases LIMIT 1')
        checks['postgresql'] = 'ok'
    except Exception:
        checks['postgresql'] = 'unavailable'
    try:
        check_connectivity()
        checks['neo4j'] = 'ok'
    except Exception:
        checks['neo4j'] = 'unavailable'
    code = 200 if all(value=='ok' for value in checks.values()) else 503
    return JSONResponse(status_code=code,content={'status':'ok' if code==200 else 'degraded','databases':checks})


@app.get('/api/auth/me', tags=['authentication'])
def me(principal=Depends(get_principal)):
    return {'user_id':principal.user_id,'is_admin':principal.is_admin,'local':principal.local}


@app.post('/api/ingestion/upload', tags=['legacy'])
def retired_upload(principal=Depends(get_principal)):
    raise HTTPException(410,'Legacy upload is retired. Use the validated case loader; fuzzy identity merging is disabled in the live API.')
