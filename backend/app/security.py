"""Supabase-verified identity plus server-owned case access, never user metadata roles."""
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from app.config import settings
from app.investigation.common import connect, require_case

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: str
    is_admin: bool = False
    local: bool = False


def validate_runtime_settings():
    if settings.app_env.lower() == 'production' and not settings.auth_enabled:
        raise RuntimeError('Production requires AUTH_ENABLED=true.')
    if settings.auth_enabled and (not settings.supabase_url.startswith('https://') or not settings.supabase_publishable_key):
        raise RuntimeError('Authentication requires SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY.')


def verify_supabase_token(token):
    if not settings.supabase_url or not settings.supabase_publishable_key:
        raise HTTPException(503, 'Supabase Auth is not configured.')
    try:
        response = httpx.get(settings.supabase_url.rstrip('/')+'/auth/v1/user',
            headers={'Authorization':'Bearer '+token,'apikey':settings.supabase_publishable_key}, timeout=10)
    except httpx.RequestError as error:
        raise HTTPException(503, 'Identity provider is unavailable.') from error
    if response.status_code >= 500:
        raise HTTPException(503, 'Identity provider is unavailable.')
    if response.status_code != 200:
        raise HTTPException(401, 'Invalid or expired access token.', headers={'WWW-Authenticate':'Bearer'})
    try:
        identity = str(UUID(response.json()['id']))
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(401, 'Invalid identity response.') from error
    return identity


def get_principal(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not settings.auth_enabled:
        if settings.app_env.lower() == 'production':
            raise HTTPException(503, 'Production requires authentication.')
        if request.client is None or request.client.host not in {'127.0.0.1','::1','localhost','testclient'}:
            raise HTTPException(403, 'Unauthenticated development access is restricted to localhost.')
        principal = Principal('local', is_admin=True, local=True)
    else:
        if credentials is None or credentials.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Access token required.', headers={'WWW-Authenticate':'Bearer'})
        identity = verify_supabase_token(credentials.credentials)
        admins = {v.strip() for v in settings.admin_user_ids.split(',') if v.strip()}
        principal = Principal(identity, is_admin=identity in admins)
    request.state.principal = principal
    return principal


def authorize_case(request: Request, principal: Principal = Depends(get_principal)):
    case_id = request.path_params.get('case_id')
    if case_id is None:
        return principal
    with connect() as conn:
        require_case(case_id, conn)
        if principal.is_admin:
            return principal
        member = conn.execute('SELECT access_level FROM inv.case_members WHERE case_id=%s AND user_id=%s',
            (case_id, UUID(principal.user_id))).fetchone()
    if member is None:
        raise HTTPException(403, 'You do not have access to this case.')
    if request.method not in {'GET','HEAD','OPTIONS'} and member['access_level'] != 'editor':
        raise HTTPException(403, 'This case requires editor access.')
    return principal
