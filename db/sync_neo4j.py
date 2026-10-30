"""Project one inv case into Neo4j; original evidence remains in PostgreSQL.

Run from repo root: python db/sync_neo4j.py --case-id CASE_VAST_GASTECH
Reads backend/.env unless --env-file is supplied. --dry-run never connects Neo4j.
Only medium/weak inferred leads are projected; zero-strength, single-day and
not-a-lead rows stay in Postgres. No analysis predictions are asserted as facts.
"""
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from neo4j import GraphDatabase
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
BATCH = 1000


def validate(case_id, persons, edges):
    if not persons:
        raise ValueError('No persons in requested case')
    if any(row['case_id'] != case_id for row in persons + edges):
        raise ValueError('Cross-case projection rejected')
    ids = {p['person_id'] for p in persons}
    if len(ids) != len(persons):
        raise ValueError('Duplicate person IDs')
    for edge in edges:
        if edge['person_a'] not in ids or edge['person_b'] not in ids:
            raise ValueError('Missing graph endpoint')
        weight = float(edge['weight'])
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError('Invalid edge weight')


def load_case(dsn, case_id):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        case = conn.execute('SELECT * FROM inv.cases WHERE case_id=%s', (case_id,)).fetchone()
        if case is None:
            raise ValueError('Unknown case ID')
        persons = conn.execute('SELECT * FROM inv.persons WHERE case_id=%s ORDER BY person_id', (case_id,)).fetchall()
        # Keep the same accepted lead levels as the default leads endpoint.
        edges = conn.execute('''SELECT case_id,person_a,person_b,relationship_type,weight,
                false AS is_inferred,source_table AS evidence_table,to_jsonb(r) AS attributes
            FROM inv.relationships r WHERE case_id=%s
            UNION ALL
            SELECT case_id,LEAST(person_a,person_b),GREATEST(person_a,person_b),
                relationship_type,lead_strength/100.0,true,'inferred_relationships',to_jsonb(i)
            FROM inv.inferred_relationships i WHERE case_id=%s
                AND relationship_type <> 'WORKPLACE_ONLY' AND lead_level IN ('medium','weak')
                AND lead_strength > 0
            ORDER BY person_a,person_b,relationship_type,is_inferred''', (case_id, case_id)).fetchall()
    validate(case_id, persons, edges)
    return case, persons, edges


def batches(rows):
    for offset in range(0, len(rows), BATCH):
        yield rows[offset:offset+BATCH]


def write_projection(tx, case_id, snapshot_id, persons, edges):
    for batch in batches(persons):
        rows = [{'id':p['person_id'], 'label':p['display_name'], 'department':p.get('department'),
                 'attributes_json':json.dumps(p, default=str, allow_nan=False)} for p in batch]
        tx.run('''UNWIND $rows AS row
            CREATE (:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id,person_id:row.id,
                node_type:'PERSON',label:row.label,department:row.department,attributes_json:row.attributes_json})''',
            case_id=case_id, snapshot_id=snapshot_id, rows=rows).consume()
    for batch in batches(edges):
        rows = []
        for edge in batch:
            kind = 'inferred' if edge['is_inferred'] else 'observed'
            key = json.dumps([edge['person_a'],edge['person_b'],edge['relationship_type'],kind])
            rows.append({'id':hashlib.sha256(key.encode()).hexdigest(), 'a':edge['person_a'],
                'b':edge['person_b'], 'type':edge['relationship_type'], 'weight':float(edge['weight']),
                'kind':kind, 'is_inferred':edge['is_inferred'], 'evidence_table':edge['evidence_table'],
                'attributes_json':json.dumps(edge.get('attributes', {}), default=str, allow_nan=False)})
        record = tx.run('''UNWIND $rows AS row
            MATCH (a:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id,person_id:row.a})
            MATCH (b:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id,person_id:row.b})
            CREATE (a)-[r:INV_LINK {case_id:$case_id,snapshot_id:$snapshot_id,edge_id:row.id,
                relationship_type:row.type,weight:row.weight,kind:row.kind,is_inferred:row.is_inferred,
                evidence_table:row.evidence_table,attributes_json:row.attributes_json}]->(b)
            RETURN count(r) AS n''', case_id=case_id, snapshot_id=snapshot_id, rows=rows).single()
        if record is None or record['n'] != len(batch):
            raise RuntimeError('Neo4j edge count mismatch')
    # New snapshot and active pointer commit in one Neo4j transaction. Older snapshots remain intact.
    tx.run('''MERGE (c:InvCase {case_id:$case_id}) SET c.active_snapshot_id=$snapshot_id,
            c.synced_at=datetime(),c.person_count=$persons,c.edge_count=$edges''',
            case_id=case_id, snapshot_id=snapshot_id, persons=len(persons), edges=len(edges)).consume()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT/'backend/.env')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    load_dotenv(args.env_file, override=False)
    if not os.getenv('SUPABASE_DATABASE_URL'):
        parser.error('SUPABASE_DATABASE_URL is missing')
    case, persons, edges = load_case(os.environ['SUPABASE_DATABASE_URL'], args.case_id)
    report = {'case_id':args.case_id, 'persons':len(persons), 'edges':len(edges),
              'observed':sum(not e['is_inferred'] for e in edges),
              'inferred':sum(e['is_inferred'] for e in edges),
              'inferred_filter':'medium,weak; positive strength; exclude WORKPLACE_ONLY'}
    if args.dry_run:
        print(json.dumps(dict(report, status='validated'), indent=2))
        return 0
    for name in ('NEO4J_URI','NEO4J_PASSWORD'):
        if not os.getenv(name):
            parser.error(name + ' is missing')
    snapshot_id = str(uuid4())
    with GraphDatabase.driver(os.environ['NEO4J_URI'],
            auth=(os.getenv('NEO4J_USERNAME') or 'neo4j',os.environ['NEO4J_PASSWORD'])) as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv('NEO4J_DATABASE') or 'neo4j') as session:
            session.run('''CREATE CONSTRAINT inv_person_snapshot IF NOT EXISTS FOR (p:InvPerson)
                REQUIRE (p.case_id,p.snapshot_id,p.person_id) IS UNIQUE''').consume()
            session.run('''CREATE CONSTRAINT inv_case_identity IF NOT EXISTS FOR (c:InvCase)
                REQUIRE c.case_id IS UNIQUE''').consume()
            # Explicit transaction avoids automatic retry of CREATE after an ambiguous commit.
            with session.begin_transaction() as tx:
                write_projection(tx, args.case_id, snapshot_id, persons, edges)
                tx.commit()
    print(json.dumps(dict(report, status='synced',snapshot_id=snapshot_id), indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # Do not print connection strings/passwords from database exception messages.
        logging.error('Sync failed (%s); check configuration, reachability and schema. No success reported.', type(error).__name__)
        raise SystemExit(1)
