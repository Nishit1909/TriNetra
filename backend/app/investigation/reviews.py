from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .common import connect, json_safe
from .analysis import get_run

router = APIRouter(prefix='/api/cases/{case_id}',tags=['reviews'])


class MentionReview(BaseModel):
    status: Literal['confirmed','rejected']
    reason: str = Field(default='',max_length=2000)


@router.post('/document_mentions/{mention_id}/review')
def review_mention(case_id: str, mention_id: int, body: MentionReview, request: Request):
    principal = getattr(request.state,'principal',None)
    if principal is None:
        raise HTTPException(401,'Authentication required.')
    actor = 'local' if principal.local else principal.user_id
    with connect() as conn:
        mention = conn.execute('''UPDATE inv.document_mentions SET review_status=%s
            WHERE case_id=%s AND mention_id=%s RETURNING *''',(body.status,case_id,mention_id)).fetchone()
        if mention is None:
            raise HTTPException(404,'Document mention not found in this case.')
        review = conn.execute('''INSERT INTO inv.document_mention_reviews
            (case_id,mention_id,status,reason,reviewed_by) VALUES (%s,%s,%s,%s,%s) RETURNING *''',
            (case_id,mention_id,body.status,body.reason,actor)).fetchone()
    return json_safe({'mention':mention,'review':review})


@router.get('/document_mentions/{mention_id}/reviews')
def mention_reviews(case_id: str, mention_id: int):
    with connect() as conn:
        exists = conn.execute('SELECT 1 FROM inv.document_mentions WHERE case_id=%s AND mention_id=%s',(case_id,mention_id)).fetchone()
        if exists is None:
            raise HTTPException(404,'Document mention not found in this case.')
        rows = conn.execute('''SELECT * FROM inv.document_mention_reviews WHERE case_id=%s AND mention_id=%s
            ORDER BY reviewed_at,review_id''',(case_id,mention_id)).fetchall()
    return json_safe(rows)


@router.get('/predicted_links/{run_id}/{a}/{b}/reviews')
def prediction_reviews(case_id: str, run_id: UUID, a: str, b: str):
    a,b = sorted((a,b))
    with connect() as conn:
        get_run(conn,case_id,run_id)
        rows = conn.execute('''SELECT * FROM inv.predicted_link_reviews WHERE case_id=%s
            AND analysis_run_id=%s AND person_a=%s AND person_b=%s ORDER BY reviewed_at,review_id''',
            (case_id,run_id,a,b)).fetchall()
    return json_safe(rows)
