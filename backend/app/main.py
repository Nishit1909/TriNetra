"""The live API: scoped evidence, versioned model runs and bounded graphs."""
from contextlib import asynccontextmanager
import time
import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import audit
from app.config import settings
from app.db.neo4j import check_connectivity, close_driver
from app.investigation.common import connect
from app.investigation import admin, analysis, cases, evidence, graph, reviews, uploads
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
app.include_router(uploads.router)
app.include_router(admin.router)       # admin portal; admin role only   # creates new cases; checks its own principal (admin only)


@app.middleware('http')
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    started = time.monotonic()
    response = await call_next(request)
    response.headers['X-Request-ID'] = request.state.request_id
    # Access log + alert rules, off the event loop. Failures are logged, never returned to the caller.
    await run_in_threadpool(audit.record_request, request.method, request.url.path, request.url.query,
        response.status_code, getattr(request.state, 'principal', None),
        request.client.host if request.client else None, request.headers.get('user-agent'),
        request.state.request_id, int((time.monotonic() - started) * 1000),
        getattr(request.state, 'audit_action', None))
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
    # PostgreSQL is required; Neo4j is optional (the graph falls back to PostgreSQL), so its outage is
    # reported as 'degraded' with 200 rather than failing readiness.
    code = 200 if checks['postgresql'] == 'ok' else 503
    status = 'ok' if all(v == 'ok' for v in checks.values()) else ('degraded' if code == 200 else 'unavailable')
    return JSONResponse(status_code=code,content={'status':status,'databases':checks,
        'notes':[] if checks['neo4j'] == 'ok' else ['Neo4j unavailable: graphs are served from PostgreSQL.']})


@app.get('/api/auth/me', tags=['authentication'])
def me(principal=Depends(get_principal)):
    """Who is calling, their portal role and which cases they can open (drives which view the UI shows)."""
    cases = []
    try:
        with connect() as conn:
            if principal.is_admin:
                cases = [dict(r, access_level='admin') for r in conn.execute('SELECT case_id,name FROM inv.cases ORDER BY case_id').fetchall()]
            else:
                from uuid import UUID
                cases = conn.execute("""SELECT c.case_id,c.name,m.access_level FROM inv.case_members m JOIN inv.cases c USING (case_id)
                    WHERE m.user_id=%s ORDER BY c.case_id""", (UUID(principal.user_id),)).fetchall()
    except HTTPException:
        raise
    except Exception:
        cases = []
    view = 'admin' if principal.is_admin else ('investigator' if principal.can_edit else 'viewer')
    return {'user_id':principal.user_id,'label':principal.label,'role':principal.role,'view':view,
            'is_admin':principal.is_admin,'can_edit':principal.can_edit,'local':principal.local,'is_demo':principal.is_demo,
            'cases':[{k:(v if k!='access_level' or principal.can_edit or v!='editor' else 'viewer') for k,v in c.items()} for c in cases]}


@app.post('/api/ingestion/upload', tags=['legacy'])
def retired_upload(principal=Depends(get_principal)):
    raise HTTPException(410,'Legacy upload is retired. Use POST /api/case-uploads (validated, creates a new case, no automatic identity merging).')
