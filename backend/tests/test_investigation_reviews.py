import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_document_reviews_are_scoped_and_append_only(monkeypatch):
    dsn = os.getenv('INV_TEST_DSN')
    if not dsn:
        pytest.skip('Disposable local PostgreSQL required')
    root = Path(__file__).parents[2]
    case,other = 'REVIEW_'+uuid4().hex,'REVIEW_'+uuid4().hex
    with psycopg.connect(dsn) as conn:
        for path in sorted((root/'db/migrations').glob('00[2-9]_*.sql')):
            conn.execute(path.read_text())
        for c in (case,other):
            conn.execute("INSERT INTO inv.cases(case_id,name,source,is_synthetic,role) VALUES (%s,%s,'test',true,'investigation')",(c,c))
            conn.execute("INSERT INTO inv.documents(case_id,document_id,document_type,body) VALUES (%s,'DOC','text','test')",(c,))
        mention = conn.execute("INSERT INTO inv.document_mentions(case_id,document_id,entity_type,entity_id,matched_text,start_char,end_char,method) VALUES (%s,'DOC','PERSON','P','test',0,4,'exact') RETURNING mention_id",(case,)).fetchone()[0]
    monkeypatch.setattr(settings,'supabase_database_url',dsn)
    monkeypatch.setattr(settings,'auth_enabled',False)
    monkeypatch.setattr(settings,'app_env','development')
    with TestClient(app) as client:
        path = f'/api/cases/{case}/document_mentions/{mention}'
        assert client.post(path+'/review',json={'status':'confirmed','reason':'Checked source'}).status_code == 200
        assert client.post(path+'/review',json={'status':'rejected','reason':'Correction'}).status_code == 200
        audit = client.get(path+'/reviews').json()
        assert [row['status'] for row in audit] == ['confirmed','rejected']
        assert all(row['reviewed_by']=='local' for row in audit)
        assert client.post(f'/api/cases/{other}/document_mentions/{mention}/review',json={'status':'confirmed'}).status_code == 404
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute('UPDATE inv.document_mention_reviews SET reason=%s WHERE review_id=%s',('tampered',audit[0]['review_id']))
        conn.rollback()
