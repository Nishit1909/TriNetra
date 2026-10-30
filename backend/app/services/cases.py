from datetime import datetime
from uuid import UUID

import psycopg

from app.config import settings


def list_cases() -> list[dict]:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT case_id, case_name, description, status, created_at
                FROM public.cases
                ORDER BY created_at NULLS LAST, case_id
                """
            )
            rows = cursor.fetchall()

    return [_case_row(row) for row in rows]


def get_case(case_id: UUID) -> dict | None:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT case_id, case_name, description, status, created_at
                FROM public.cases
                WHERE case_id = %s
                """,
                (case_id,),
            )
            row = cursor.fetchone()

    return _case_row(row) if row else None


def _case_row(row: tuple) -> dict:
    case_id, case_name, description, status, created_at = row
    return {
        "case_id": case_id,
        "case_name": case_name,
        "description": description,
        "status": status,
        "created_at": created_at,
    }