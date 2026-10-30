"""Initialize local config, or create/check the agreed PostgreSQL and Neo4j schemas."""
import argparse
import os
from pathlib import Path
import re
import sys

from dotenv import load_dotenv
from neo4j import GraphDatabase
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'db/migrations/001_case_scoped_schema.sql'
SQL = MIGRATION.read_text(encoding='utf-8')
REQUIRED_COLUMNS = {name:set(re.findall(r'^    ([a-z]\w*)\s+[A-Z]', body, re.M))
                    for name,body in re.findall(r'CREATE TABLE (\w+) \((.*?)\n\);', SQL, re.S)}
TABLES = set(REQUIRED_COLUMNS)
NEO_CONSTRAINTS = {
    'inv_person_snapshot': "FOR (p:InvPerson) REQUIRE (p.case_id,p.snapshot_id,p.person_id) IS UNIQUE",
    'inv_case_identity': "FOR (c:InvCase) REQUIRE c.case_id IS UNIQUE",
}
EXTENSION_TABLES = {'predicted_link_reviews','case_members','document_mention_reviews', 'app_users', 'access_log', 'security_alerts', 'admin_settings', 'location_points', 'location_meetings', 'money_transfers'}


def init_env(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('x', encoding='utf-8') as stream:
            stream.write(source.read_text(encoding='utf-8'))
    except FileExistsError:
        return 'preserved'
    return 'created'


def ensure_schema(conn, apply=False):
    if apply:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('sih26189.inv.setup'))")
    rows = conn.execute("""SELECT table_name FROM information_schema.tables
        WHERE table_schema='inv' AND table_type='BASE TABLE'""").fetchall()
    existing = {row['table_name'] for row in rows}
    created = False
    if not existing:
        if not apply:
            raise ValueError('inv schema is missing. Run --apply to create it.')
        conn.execute(SQL)
        created = True
    elif TABLES - existing:
        raise ValueError('Incomplete existing inv schema; no changes made. Missing: ' + ', '.join(sorted(TABLES-existing)))
    columns = conn.execute("""SELECT table_name,column_name FROM information_schema.columns
        WHERE table_schema='inv'""").fetchall()
    available = {(row['table_name'],row['column_name']) for row in columns}
    missing = [f'{name}.{column}' for name,cols in REQUIRED_COLUMNS.items()
               for column in cols if (name,column) not in available]
    if missing:
        raise ValueError('Incompatible inv columns: ' + ', '.join(sorted(missing)))
    if conn.execute("SELECT to_regclass('inv.case_graph_edges') AS relation").fetchone()['relation'] is None:
        raise ValueError('inv.case_graph_edges view is missing')
    return 'created' if created else 'verified'


def neo4j_schema(apply=False):
    with GraphDatabase.driver(os.environ['NEO4J_URI'],
            auth=(os.getenv('NEO4J_USERNAME') or 'neo4j',os.environ['NEO4J_PASSWORD'])) as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv('NEO4J_DATABASE') or 'neo4j') as session:
            if apply:
                for name,clause in NEO_CONSTRAINTS.items():
                    session.run(f'CREATE CONSTRAINT {name} IF NOT EXISTS {clause}').consume()
            rows = session.run('SHOW CONSTRAINTS YIELD name RETURN name').data()
            if set(NEO_CONSTRAINTS) - {row['name'] for row in rows}:
                raise ValueError('Neo4j constraints missing; run --apply')


def ensure_extensions(conn, apply=False):
    if apply:
        for path in sorted(MIGRATION.parent.glob('00[2-9]_*.sql')):
            conn.execute(path.read_text(encoding='utf-8'))
    found = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='inv'").fetchall()
    if EXTENSION_TABLES - {row['table_name'] for row in found}:
        raise ValueError('Backend permissions/review migrations missing; run --apply.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--init-env', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    if args.init_env:
        result = init_env(ROOT/'backend/.env.example', ROOT/'backend/.env')
        print(f'backend/.env {result}. Fill in your own connection settings locally.')
        return 0
    load_dotenv(ROOT/'backend/.env', override=False)
    missing = [key for key in ('SUPABASE_DATABASE_URL','NEO4J_URI','NEO4J_PASSWORD') if not os.getenv(key)]
    if missing:
        print('Missing local settings: ' + ', '.join(missing) + '. Edit backend/.env; no database changes made.', file=sys.stderr)
        return 2
    with psycopg.connect(os.environ['SUPABASE_DATABASE_URL'], row_factory=dict_row) as conn:
        state = ensure_schema(conn, apply=args.apply)
        ensure_extensions(conn, apply=args.apply)
    print(f'PostgreSQL inv schema {state}: {len(TABLES)} tables and case_graph_edges view.')
    print('Backend case permissions and review-audit tables verified.')
    neo4j_schema(args.apply)
    print('Neo4j connectivity and case/snapshot constraints verified. Data loading/sync is a separate step.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        print(f'Setup failed ({type(error).__name__}). Check local settings and database reachability. No tables deleted.', file=sys.stderr)
        raise SystemExit(1)
