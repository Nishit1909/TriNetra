import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

spec = importlib.util.spec_from_file_location('sync_neo4j', Path(__file__).parents[1] / 'db/sync_neo4j.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_rejects_cross_case_and_missing_endpoints():
    persons = [{'case_id':'CASE_A', 'person_id':'p1'}]
    with pytest.raises(ValueError, match='case'):
        sync.validate('CASE_B', persons, [])
    edge = {'case_id':'CASE_A','person_a':'p1','person_b':'p2','weight':1}
    with pytest.raises(ValueError, match='endpoint'):
        sync.validate('CASE_A', persons, [edge])


@pytest.mark.parametrize('weight', [0, -1, float('nan'), float('inf')])
def test_invalid_strength_rejected(weight):
    persons = [{'case_id':'A','person_id':p} for p in ['p1','p2']]
    edge = {'case_id':'A','person_a':'p1','person_b':'p2','weight':weight}
    with pytest.raises(ValueError, match='weight'):
        sync.validate('A', persons, [edge])


def test_projection_scope_and_activation_in_same_transaction():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {'n':1}
    persons = [{'case_id':'A','person_id':'p1','display_name':'One','department':None}]
    edges = [{'case_id':'A','person_a':'p1','person_b':'p1', 'relationship_type':'TEST',
              'weight':1, 'is_inferred':False, 'evidence_table':'relationships'}]
    sync.write_projection(tx, 'A', 'snapshot-1', persons, edges)
    calls = tx.run.call_args_list
    assert all(c.kwargs['case_id'] == 'A' and c.kwargs['snapshot_id'] == 'snapshot-1' for c in calls)
    assert 'MATCH (a:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id' in calls[1].args[0]
    assert 'MATCH (b:InvPerson {case_id:$case_id,snapshot_id:$snapshot_id' in calls[1].args[0]
    assert 'active_snapshot_id' in calls[-1].args[0]
    assert not any('DELETE' in c.args[0] for c in calls)


def test_missing_neo_endpoint_aborts_before_publication():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {'n':0}
    edge = {'case_id':'A','person_a':'p1','person_b':'p2', 'relationship_type':'TEST',
            'weight':1, 'is_inferred':False,'evidence_table':'relationships'}
    with pytest.raises(RuntimeError, match='count'):
        sync.write_projection(tx, 'A', 'snapshot-1', [], [edge])
    assert not any('active_snapshot_id' in c.args[0] for c in tx.run.call_args_list)
