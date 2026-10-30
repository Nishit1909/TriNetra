import json
import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.config import settings

logger = logging.getLogger(__name__)


def persist_analytics_results(overview: dict) -> dict:
    parameters = Jsonb(
        {
            "graph": overview["graph"],
            "result_counts": {
                "person_metrics": len(overview["centrality"]),
                "community_memberships": len(overview["communities"]),
                "predicted_links": len(overview["link_predictions"]),
            },
            "risk": {
                "status": overview["risk"]["status"],
                "demo_only": overview["risk"].get("demo_only", True),
            },
            "errors": overview.get("errors", {}),
            "execution_time_seconds": overview.get("execution_time_seconds"),
        }
    )

    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO public.analysis_runs (algorithm, parameters, status)
                    VALUES (%s, %s, %s)
                    RETURNING analysis_run_id
                    """,
                    ("centrality_community_link_prediction", parameters, "running"),
                )
                analysis_run_id = cursor.fetchone()[0]

                person_metrics = _person_metric_rows(analysis_run_id, overview)
                if person_metrics:
                    cursor.executemany(
                        """
                        INSERT INTO public.person_metrics (
                            analysis_run_id, person_id, degree_centrality,
                            betweenness_centrality, pagerank, risk_score, rank
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        person_metrics,
                    )

                community_memberships = [
                    (analysis_run_id, row["person_id"], row.get("community_id"))
                    for row in overview["communities"]
                ]
                if community_memberships:
                    cursor.executemany(
                        """
                        INSERT INTO public.community_memberships
                            (analysis_run_id, person_id, community_id)
                        VALUES (%s, %s, %s)
                        """,
                        community_memberships,
                    )

                predicted_links = [
                    (
                        analysis_run_id,
                        row.get("source_person_id"),
                        row.get("target_person_id"),
                        row.get("predicted_relationship_type"),
                        _float_or_none(row.get("probability")),
                        _explanation(row.get("explanation")),
                        row.get("review_status", "pending"),
                    )
                    for row in overview["link_predictions"]
                ]
                if predicted_links:
                    cursor.executemany(
                        """
                        INSERT INTO public.predicted_links (
                            analysis_run_id, source_person_id, target_person_id,
                            predicted_relationship_type, probability, explanation,
                            review_status
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        predicted_links,
                    )

                cursor.execute(
                    """
                    UPDATE public.analysis_runs
                    SET status = %s
                    WHERE analysis_run_id = %s
                    """,
                    ("completed", analysis_run_id),
                )

    return {
        "analysis_run_id": analysis_run_id,
        "person_metrics": len(person_metrics),
        "community_memberships": len(community_memberships),
        "predicted_links": len(predicted_links),
        "risk_status": overview["risk"]["status"],
    }


def get_latest_analytics_results(limit: int | None = None) -> dict | None:
    with psycopg.connect(settings.supabase_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT analysis_run_id, case_id, algorithm, parameters, status, created_at
                FROM public.analysis_runs
                ORDER BY created_at DESC NULLS LAST, analysis_run_id DESC
                LIMIT 1
                """
            )
            run = cursor.fetchone()
            if run is None:
                return None

            analysis_run_id, case_id, algorithm, parameters, run_status, created_at = run
            result_limit = " LIMIT %s" if limit is not None else ""
            metric_query = """
                SELECT person_id, degree_centrality, betweenness_centrality,
                       pagerank, risk_score, rank
                FROM public.person_metrics
                WHERE analysis_run_id = %s
                ORDER BY rank NULLS LAST, person_id
            """ + result_limit
            cursor.execute(metric_query, (analysis_run_id, limit) if limit is not None else (analysis_run_id,))
            person_metrics = [
                dict(zip(("person_id", "degree_centrality", "betweenness_centrality", "pagerank", "risk_score", "rank"), row))
                for row in cursor.fetchall()
            ]

            community_query = """
                SELECT person_id, community_id
                FROM public.community_memberships
                WHERE analysis_run_id = %s
                ORDER BY person_id
            """ + result_limit
            cursor.execute(community_query, (analysis_run_id, limit) if limit is not None else (analysis_run_id,))
            communities = [
                dict(zip(("person_id", "community_id"), row)) for row in cursor.fetchall()
            ]

            links_query = """
                SELECT source_person_id, target_person_id, predicted_relationship_type,
                       probability, explanation, review_status
                FROM public.predicted_links
                WHERE analysis_run_id = %s
                ORDER BY probability DESC NULLS LAST, prediction_id
            """ + result_limit
            cursor.execute(links_query, (analysis_run_id, limit) if limit is not None else (analysis_run_id,))
            links = [
                dict(zip(("source_person_id", "target_person_id", "predicted_relationship_type", "probability", "explanation", "review_status"), row))
                for row in cursor.fetchall()
            ]

    return {
        "analysis_run": {
            "analysis_run_id": analysis_run_id,
            "case_id": case_id,
            "algorithm": algorithm,
            "parameters": parameters,
            "status": run_status,
            "created_at": created_at,
        },
        "person_metrics": person_metrics,
        "community_memberships": communities,
        "predicted_links": links,
        "risk": (parameters or {}).get("risk", {"status": "unavailable", "results": []}),
    }


def _person_metric_rows(analysis_run_id: UUID, overview: dict) -> list[tuple]:
    risk_by_person = {
        row["person_id"]: row.get("risk_score")
        for row in overview["risk"].get("results", [])
    } if overview["risk"]["status"] == "available" else {}
    return [
        (
            analysis_run_id,
            row["person_id"],
            _float_or_none(row.get("degree_centrality")),
            _float_or_none(row.get("betweenness_centrality")),
            _float_or_none(row.get("pagerank")),
            _float_or_none(risk_by_person.get(row["person_id"])),
            row.get("rank"),
        )
        for row in overview["centrality"]
    ]


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _explanation(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))