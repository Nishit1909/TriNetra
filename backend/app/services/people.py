import psycopg

from app.config import settings


def list_people() -> list[dict]:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT person_id, case_id, source_domain, source_entity_id,
                       display_name, department, job_title, identity_bridge_type
                FROM public.persons
                ORDER BY person_id
                """
            )
            rows = cursor.fetchall()

    return [_person_row(row) for row in rows]


def get_person(person_id: str) -> dict | None:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT person_id, case_id, source_domain, source_entity_id,
                       display_name, department, job_title, identity_bridge_type
                FROM public.persons
                WHERE person_id = %s
                """,
                (person_id,),
            )
            row = cursor.fetchone()

    return _person_row(row) if row else None


def _person_row(row: tuple) -> dict:
    (
        person_id,
        case_id,
        source_domain,
        source_entity_id,
        display_name,
        department,
        job_title,
        identity_bridge_type,
    ) = row
    return {
        "person_id": person_id,
        "case_id": case_id,
        "source_domain": source_domain,
        "source_entity_id": source_entity_id,
        "display_name": display_name,
        "department": department,
        "job_title": job_title,
        "identity_bridge_type": identity_bridge_type,
    }