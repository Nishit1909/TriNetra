import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app import security
from app.main import app


@pytest.fixture
def secured_api(monkeypatch):
    dsn = os.getenv('INV_TEST_DSN')
    if not dsn:
        pytest.skip('Dedicated disposable PostgreSQL DSN required')
    root = Path(__file__).parents[2]
    case_a,case_b = 'API_'+uuid4().hex,'API_'+uuid4().hex
    viewer,editor = uuid4(),uuid4()
    with psycopg.connect(dsn) as conn:
        for migration in ('003_case_membership.sql',):
            conn.execute((root/'db/migrations'/migration).read_text())
        for case in (case_a,case_b):
            conn.execute("INSERT INTO inv.cases(case_id,name,source,is_synthetic,role) VALUES (%s,%s,'test',true,'investigation')", (case,case))
            conn.execute("INSERT INTO inv.persons(case_id,person_id,display_name) VALUES (%s,'SAME','Name')", (case,))
        conn.execute("INSERT INTO inv.case_members(case_id,user_id,access_level) VALUES (%s,%s,'viewer'),(%s,%s,'editor')", (case_a,viewer,case_a,editor))
    monkeypatch.setattr(settings,'supabase_database_url',dsn)
    monkeypatch.setattr(settings,'auth_enabled',True)
    monkeypatch.setattr(settings,'supabase_url','https://example.supabase.co')
    monkeypatch.setattr(settings,'supabase_publishable_key','test-public-key')
    monkeypatch.setattr(settings,'admin_user_ids','')
    monkeypatch.setattr(security,'verify_supabase_token',lambda token: str(viewer if token=='viewer' else editor))
    with TestClient(app) as client:
        yield client,case_a,case_b
    with psycopg.connect(dsn) as conn:
        conn.execute('DELETE FROM inv.cases WHERE case_id=ANY(%s)', ([case_a,case_b],))


def test_auth_and_case_permissions_enforced_on_real_router(secured_api):
    client,case_a,case_b = secured_api
    assert client.get('/api/cases').status_code == 401
    headers = {'Authorization':'Bearer viewer'}
    result = client.get('/api/cases',headers=headers)
    assert result.status_code == 200
    assert [case['case_id'] for case in result.json()] == [case_a]
    assert client.get(f'/api/cases/{case_a}/persons/SAME',headers=headers).status_code == 200
    assert client.get(f'/api/cases/{case_b}/persons/SAME',headers=headers).status_code == 403
    assert client.post(f'/api/cases/{case_a}/analysis',headers=headers,json={'mode':'observed_only'}).status_code == 403
    assert client.get('/api/graph',headers=headers).status_code == 404
    assert client.get('/api/analytics/overview',headers=headers).status_code == 404
    retired = client.post('/api/ingestion/upload',headers=headers)
    assert retired.status_code == 410


def test_case_routes_have_bounds_and_request_ids(secured_api):
    client,case_a,_ = secured_api
    headers = {'Authorization':'Bearer editor'}
    response = client.get(f'/api/cases/{case_a}/persons?limit=1000',headers=headers)
    assert response.status_code == 422
    assert response.headers.get('x-request-id')
    assert client.get(f'/api/cases/{case_a}/graph?limit=1000',headers=headers).status_code == 422
    assert client.get('/api/cases/DOES_NOT_EXIST/persons',headers=headers).status_code == 404


def test_cors_preflight_and_health_live():
    client = TestClient(app)
    response = client.options('/api/cases',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'GET'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert client.get('/health').status_code == 200
