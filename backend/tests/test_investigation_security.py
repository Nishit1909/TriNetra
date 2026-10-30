from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException


def test_server_rejects_invalid_token(monkeypatch):
    from app import security
    monkeypatch.setattr(security.settings, 'supabase_url', 'https://example.supabase.co')
    monkeypatch.setattr(security.settings, 'supabase_publishable_key', 'public-test')
    response = MagicMock(status_code=401)
    monkeypatch.setattr(security.httpx, 'get', lambda *a, **k: response)
    with pytest.raises(HTTPException) as error:
        security.verify_supabase_token('invalid')
    assert error.value.status_code == 401


def test_verified_identity_is_provider_user_id(monkeypatch):
    from app import security
    identity = str(uuid4())
    monkeypatch.setattr(security.settings, 'supabase_url', 'https://example.supabase.co')
    monkeypatch.setattr(security.settings, 'supabase_publishable_key', 'public-test')
    response = MagicMock(status_code=200)
    response.json.return_value = {'id':identity, 'user_metadata':{'role':'admin'}}
    monkeypatch.setattr(security.httpx, 'get', lambda *a, **k: response)
    assert security.verify_supabase_token('opaque-provider-token') == identity


def test_production_requires_auth(monkeypatch):
    from app import security
    monkeypatch.setattr(security.settings, 'app_env', 'production')
    monkeypatch.setattr(security.settings, 'auth_enabled', False)
    with pytest.raises(RuntimeError, match='AUTH_ENABLED'):
        security.validate_runtime_settings()


def test_network_failure_is_not_invalid_credentials(monkeypatch):
    from app import security
    monkeypatch.setattr(security.settings, 'supabase_url', 'https://example.supabase.co')
    monkeypatch.setattr(security.settings, 'supabase_publishable_key', 'public-test')
    def unavailable(*args, **kwargs):
        raise security.httpx.ConnectError('simulated outage')
    monkeypatch.setattr(security.httpx, 'get', unavailable)
    with pytest.raises(HTTPException) as error:
        security.verify_supabase_token('token')
    assert error.value.status_code == 503


def test_json_normalization_replaces_nonfinite_values():
    from app.investigation.common import json_safe
    import numpy as np
    assert json_safe({'a':np.nan,'b':np.float64(0.5),'c':float('inf')}) == {'a':None,'b':0.5,'c':None}
