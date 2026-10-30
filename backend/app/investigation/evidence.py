"""Case-scoped source records and explicitly labelled derived evidence."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.investigation.common import connect, json_safe, require_case, require_person

router = APIRouter(prefix="/api/cases/{case_id}", tags=["evidence"])


def _page(conn, sql, params, limit, offset):
    total = conn.execute("SELECT count(*) AS total FROM (" + sql + ") rows", params).fetchone()["total"]
    items = conn.execute(sql + " LIMIT %s OFFSET %s", (*params, limit, offset)).fetchall()
    return json_safe({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/persons")
def persons(case_id: str, department: str | None = None, q: str | None = None,
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with connect() as conn:
        require_case(case_id, conn)
        sql = "SELECT * FROM inv.persons WHERE case_id=%s"
        params = [case_id]
        if department is not None:
            sql += " AND department=%s"
            params.append(department)
        if q:
            sql += " AND (display_name ILIKE %s OR person_id ILIKE %s)"
            params.extend(["%" + q + "%", "%" + q + "%"])
        return _page(conn, sql + " ORDER BY display_name,person_id", params, limit, offset)


@router.get("/persons/{person_id}")
def profile(case_id: str, person_id: str):
    with connect() as conn:
        person = dict(require_person(case_id, person_id, conn))
        person["vehicle_assignments"] = conn.execute("""
            SELECT a.*, v.source_car_id,v.department,v.owner_job_title,
                   'assigned_driver_assumed' AS person_attribution
            FROM inv.vehicle_assignments a JOIN inv.vehicles v
              ON v.case_id=a.case_id AND v.vehicle_id=a.vehicle_id
            WHERE a.case_id=%s AND a.person_id=%s ORDER BY a.vehicle_id
        """, (case_id, person_id)).fetchall()
        person["counts"] = conn.execute("""
            SELECT
              (SELECT count(*) FROM inv.communication_events WHERE case_id=%s
                 AND communication_type='email' AND (source_person_id=%s OR target_person_id=%s)) AS emails,
              (SELECT count(*) FROM inv.colocation_events WHERE case_id=%s
                 AND (person_a=%s OR person_b=%s)) AS colocations,
              (SELECT count(DISTINCT document_id) FROM inv.document_mentions WHERE case_id=%s
                 AND upper(entity_type)='PERSON' AND entity_id=%s AND review_status<>'rejected') AS documents
        """, (case_id, person_id, person_id, case_id, person_id, person_id, case_id, person_id)).fetchone()
        return json_safe(person)


@router.get("/relationships")
def relationships(case_id: str, kind: Literal["observed", "inferred", "all"] = "all",
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with connect() as conn:
        require_case(case_id, conn)
        sql = """SELECT e.*, i.lead_strength,i.lead_level
                 FROM inv.case_graph_edges e LEFT JOIN LATERAL (
                    SELECT r.case_id,r.lead_strength,r.lead_level
                    FROM inv.inferred_relationships r WHERE r.case_id=e.case_id
                      AND LEAST(r.person_a,r.person_b)=e.person_a
                      AND GREATEST(r.person_a,r.person_b)=e.person_b
                      AND r.relationship_type=e.relationship_type AND r.lead_strength/100.0=e.weight
                    ORDER BY r.person_a,r.person_b LIMIT 1
                 ) i ON i.case_id=e.case_id AND e.is_inferred
                 WHERE e.case_id=%s"""
        params = [case_id]
        if kind != "all":
            sql += " AND e.is_inferred=%s"
            params.append(kind == "inferred")
        return _page(conn, sql + " ORDER BY e.person_a,e.person_b,e.is_inferred,e.relationship_type", params, limit, offset)


@router.get("/relationships/{a}/{b}")
def pair_evidence(case_id: str, a: str, b: str, limit: int = Query(50, ge=1, le=100),
                  offset: int = Query(0, ge=0)):
    with connect() as conn:
        require_person(case_id, a, conn)
        require_person(case_id, b, conn)
        a, b = sorted((a, b))
        params = (case_id, a, b)
        observed = conn.execute("""SELECT *,false AS is_inferred FROM inv.relationships
            WHERE case_id=%s AND person_a=%s AND person_b=%s ORDER BY relationship_type""", params).fetchall()
        inferred = conn.execute("""SELECT *,true AS is_inferred FROM inv.inferred_relationships
            WHERE case_id=%s AND LEAST(person_a,person_b)=%s AND GREATEST(person_a,person_b)=%s
            ORDER BY person_a,person_b""", params).fetchall()
        emails = _page(conn, """SELECT * FROM inv.communication_events
            WHERE case_id=%s AND LEAST(source_person_id,target_person_id)=%s
              AND GREATEST(source_person_id,target_person_id)=%s AND communication_type='email'
            ORDER BY sent_at NULLS LAST,communication_id""", params, limit, offset)
        colocations = _page(conn, """
            SELECT c.*,to_jsonb(p) AS place,to_jsonb(sa) AS stop_a,to_jsonb(sb) AS stop_b
            FROM inv.colocation_events c
            JOIN inv.places p ON p.case_id=c.case_id AND p.place_id=c.place_id
            JOIN inv.vehicle_stops sa ON sa.case_id=c.case_id AND sa.stop_id=c.stop_a
            JOIN inv.vehicle_stops sb ON sb.case_id=c.case_id AND sb.stop_id=c.stop_b
            WHERE c.case_id=%s AND LEAST(c.person_a,c.person_b)=%s
              AND GREATEST(c.person_a,c.person_b)=%s
            ORDER BY c.overlap_start,c.colocation_id
        """, params, limit, offset)
        return json_safe({"case_id": case_id, "person_a": a, "person_b": b,
                          "observed_relationships": observed, "inferred_relationships": inferred,
                          "emails": emails, "colocation_events": colocations,
                          "uncertainty": {"person_attribution": "assigned_driver_assumed" if inferred or colocations["total"] else None,
                                          "note": "Vehicle assignment does not prove who was driving. Coded ties do not imply available email headers."}})


@router.get("/leads")
def leads(case_id: str, level: str = "medium,weak", limit: int = Query(50, ge=1, le=100),
          offset: int = Query(0, ge=0)):
    levels = [value.strip() for value in level.split(",") if value.strip()]
    if not levels or any(value not in {"strong", "medium", "weak", "weak_single_day", "not_a_lead"} for value in levels):
        raise HTTPException(422, "level must contain strong, medium, weak, weak_single_day, or not_a_lead")
    with connect() as conn:
        require_case(case_id, conn)
        return _page(conn, """SELECT *,true AS is_inferred FROM inv.inferred_relationships
            WHERE case_id=%s AND lead_level=ANY(%s)
            ORDER BY lead_strength DESC,person_a,person_b""", (case_id, levels), limit, offset)


@router.get("/places/{place_id}")
def place(case_id: str, place_id: str, limit: int = Query(50, ge=1, le=100),
          offset: int = Query(0, ge=0)):
    with connect() as conn:
        require_case(case_id, conn)
        row = conn.execute("SELECT * FROM inv.places WHERE case_id=%s AND place_id=%s", (case_id, place_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Place not found")
        row["vehicle_stops"] = _page(conn, """SELECT * FROM inv.vehicle_stops
            WHERE case_id=%s AND place_id=%s ORDER BY stop_start,stop_id""", (case_id, place_id), limit, offset)
        return json_safe(row)


@router.get("/documents/{document_id}")
def document(case_id: str, document_id: str):
    with connect() as conn:
        require_case(case_id, conn)
        row = conn.execute("SELECT * FROM inv.documents WHERE case_id=%s AND document_id=%s", (case_id, document_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Document not found")
        row["mentions"] = conn.execute("""SELECT * FROM inv.document_mentions
            WHERE case_id=%s AND document_id=%s ORDER BY start_char,mention_id""", (case_id, document_id)).fetchall()
        return json_safe(row)


@router.get("/persons/{person_id}/timeline")
def timeline(case_id: str, person_id: str, limit: int = Query(50, ge=1, le=100),
             offset: int = Query(0, ge=0)):
    with connect() as conn:
        require_person(case_id, person_id, conn)
        return _page(conn, """
            SELECT e.sent_at AS event_time,e.communication_id AS event_id,
                   e.communication_type AS event_type,to_jsonb(e) AS evidence
            FROM inv.communication_events e WHERE e.case_id=%s
              AND (e.source_person_id=%s OR e.target_person_id=%s)
            UNION ALL
            SELECT s.stop_start,s.stop_id,'vehicle_stop',
                   to_jsonb(s) || jsonb_build_object('person_attribution','assigned_driver_assumed')
            FROM inv.vehicle_stops s WHERE s.case_id=%s AND s.assigned_person_id=%s
            ORDER BY event_time NULLS LAST,event_type,event_id
        """, (case_id, person_id, person_id, case_id, person_id), limit, offset)


@router.get("/summary")
def summary(case_id: str):
    with connect() as conn:
        case = require_case(case_id, conn)
        counts = {}
        for table in ("persons", "vehicles", "communication_events", "relationships", "inferred_relationships",
                      "colocation_events", "places", "documents", "document_mentions", "transactions"):
            counts[table] = conn.execute("SELECT count(*) AS count FROM inv." + table + " WHERE case_id=%s", (case_id,)).fetchone()["count"]
        latest = conn.execute("""SELECT * FROM inv.analysis_runs WHERE case_id=%s
            ORDER BY started_at DESC,analysis_run_id DESC LIMIT 1""", (case_id,)).fetchone()
        return json_safe({"case": case, "counts": counts, "latest_analysis": latest,
                          "uncertainty": {"vehicle_person_attribution": "assigned_driver_assumed",
                                          "card_ownership": "unknown", "source_timezone": "unknown"}})
