import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
import os

import pytest

spec = importlib.util.spec_from_file_location('setup_database', Path(__file__).parents[1] / 'db/setup_database.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def test_init_env_never_overwrites_existing_secret_file(tmp_path):
    source = tmp_path / '.env.example'
    target = tmp_path / '.env'
    source.write_text('NEO4J_PASSWORD=\n')
    assert setup.init_env(source, target) == 'created'
    target.write_text('NEO4J_PASSWORD=local-only\n')
    assert setup.init_env(source, target) == 'preserved'
    assert target.read_text() == 'NEO4J_PASSWORD=local-only\n'


def test_incomplete_existing_schema_is_rejected_without_migration(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [{'table_name':'cases'}]
    with pytest.raises(ValueError, match='Incomplete'):
        setup.ensure_schema(conn, apply=True)
    queries = [c.args[0] for c in conn.execute.call_args_list]
    assert not any('CREATE TABLE' in q or 'DROP ' in q for q in queries)


def test_fresh_schema_check_does_not_create_tables():
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []
    with pytest.raises(ValueError, match='missing'):
        setup.ensure_schema(conn, apply=False)
    assert not any('CREATE TABLE' in c.args[0] for c in conn.execute.call_args_list)


def test_migration_declares_the_expected_case_scoped_tables():
    assert len(setup.TABLES) == 21
    assert {'cases','persons','relationships','inferred_relationships','analysis_runs','predicted_links'} <= setup.TABLES


def test_existing_schema_check_does_not_write(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.fetchall.side_effect = [
        [{'table_name':name} for name in sorted(setup.TABLES)],
        [{'table_name':name,'column_name':column} for name, columns in setup.REQUIRED_COLUMNS.items() for column in columns],
    ]
    conn.execute.return_value.fetchone.return_value = {'relation':'inv.case_graph_edges'}
    assert setup.ensure_schema(conn, apply=False) == 'verified'
    queries = [c.args[0] for c in conn.execute.call_args_list]
    assert not any(q.startswith(('CREATE','INSERT','UPDATE','DELETE','DROP')) for q in queries)


def test_fresh_and_repeatable_setup_against_disposable_postgres():
    dsn = os.getenv('INV_TEST_DSN')
    if not dsn:
        pytest.skip('Disposable PostgreSQL DSN required')
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute('DROP SCHEMA IF EXISTS inv CASCADE')
        assert setup.ensure_schema(conn, apply=True) == 'created'
        assert setup.ensure_schema(conn, apply=True) == 'verified'
        assert setup.ensure_schema(conn, apply=False) == 'verified'
        conn.execute("INSERT INTO inv.cases(case_id,name,source,is_synthetic,role) VALUES ('TEST','Test','test',true,'investigation')")
        assert setup.ensure_schema(conn, apply=True) == 'verified'
        assert conn.execute("SELECT count(*) AS n FROM inv.cases WHERE case_id='TEST'").fetchone()['n'] == 1
        conn.rollback()
