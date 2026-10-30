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
    role: str = 'admin'          # viewer | investigator | admin (portal role from inv.app_users)
    label: str = 'local'         # display name/email for the access log
    is_demo: bool = False

    @property
    def can_edit(self):
        return self.role in ('investigator', 'admin')


DEMO_USER_HEADER = 'X-Demo-User'


def _app_user(user_id):
    """Portal role for a user, or None when the security tables or the user don't exist."""
    try:
        with connect() as conn:
            return conn.execute('SELECT * FROM inv.app_users WHERE user_id=%s', (UUID(str(user_id)),)).fetchone()
    except (HTTPException, ValueError):
        raise
    except Exception:
        return None


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
        demo = request.headers.get(DEMO_USER_HEADER)
        if demo:
            # Development-only role switch so the three portal views can be shown without real logins.
            try:
                user = _app_user(demo)
            except ValueError:
                raise HTTPException(401, 'Unknown demo user.')
            if user is None or not user['active']:
                raise HTTPException(401, 'Unknown or inactive demo user.')
            principal = Principal(str(user['user_id']), is_admin=user['role'] == 'admin', local=False,
                                  role=user['role'], label=user['email'], is_demo=user['is_demo'])
        else:
            principal = Principal('local', is_admin=True, local=True)
    else:
        if credentials is None or credentials.scheme.lower() != 'bearer':
            raise HTTPException(401, 'Access token required.', headers={'WWW-Authenticate':'Bearer'})
        identity = verify_supabase_token(credentials.credentials)
        admins = {v.strip() for v in settings.admin_user_ids.split(',') if v.strip()}
        user = _app_user(identity)
        if user is not None and not user['active']:
            raise HTTPException(403, 'This account is disabled.')
        role = 'admin' if identity in admins else (user['role'] if user else 'viewer')
        principal = Principal(identity, is_admin=role == 'admin', role=role,
                              label=user['email'] if user else identity, is_demo=bool(user and user['is_demo']))
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
    if request.method not in {'GET','HEAD','OPTIONS'} and (member['access_level'] != 'editor' or not principal.can_edit):
        raise HTTPException(403, 'This case requires editor access.')
    return principal
