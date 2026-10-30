from datetime import date, datetime
from decimal import Decimal
import math
from pathlib import Path
import sys
from uuid import UUID

from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from app.config import settings

# Model team's pure package lives at repository root, beside backend/.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def connect():
    if not settings.supabase_database_url:
        raise HTTPException(503, 'PostgreSQL is not configured.')
    return psycopg.connect(settings.supabase_database_url, row_factory=dict_row, connect_timeout=15)


def require_case(case_id, conn=None):
    if conn is None:
        with connect() as connection:
            return require_case(case_id, connection)
    row = conn.execute('SELECT * FROM inv.cases WHERE case_id=%s', (case_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Case not found.')
    return row


def require_person(case_id, person_id, conn=None):
    if conn is None:
        with connect() as connection:
            return require_person(case_id, person_id, connection)
    require_case(case_id, conn)
    row = conn.execute('SELECT * FROM inv.persons WHERE case_id=%s AND person_id=%s', (case_id, person_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Person not found in this case.')
    return row


def json_safe(value):
    if isinstance(value, dict):
        return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return json_safe(float(value))
    if hasattr(value, 'item'):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
