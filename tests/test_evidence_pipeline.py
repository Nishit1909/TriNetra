"""Regressions against the real case, rebuilt in disposable storage."""
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def frame(path, **kwargs):
    return pd.read_csv(path, low_memory=False, **kwargs)


class EvidencePipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='vvce-evidence-tests-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.case = Path(cls.temp.name) / 'case'
        cls.out = Path(cls.temp.name) / 'derived'
        archive = ROOT / 'datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip'
        expected = json.loads((ROOT / 'datasets/SHA256SUMS.json').read_text())[archive.name]
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                assert (cls.case / member.filename).resolve().is_relative_to(cls.case.resolve())
            z.extractall(cls.case)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/derive_evidence.py'), str(cls.case), str(cls.out)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.stops = frame(cls.out / 'vehicle_stops.csv', parse_dates=['stop_start', 'stop_end'])
        cls.relationships = frame(cls.out / 'colocation_relationships.csv')

    def test_cards_remain_unresolved_without_verified_merchant_locations(self):
        cards = frame(self.out / 'card_owner_inference.csv')
        self.assertFalse((cards.status == 'inferred').any(), 'Timing alone cannot attribute a card at an unverified merchant location')

    def test_stop_bounds_are_spatially_consistent(self):
        required = {'next_gps_event_id', 'boundary_distance_m', 'inference_status'}
        self.assertTrue(required <= set(self.stops.columns), 'Stops need both bounding events and an uncertainty check')
        self.assertTrue(self.stops.boundary_distance_m.le(50).all())
        uncertain = frame(self.out / 'uncertain_vehicle_gaps.csv')
        self.assertGreater(len(uncertain), 0)
        self.assertTrue(uncertain.boundary_distance_m.gt(50).all())
        self.assertFalse(set(uncertain.stop_id) & set(self.stops.stop_id))

    def test_chance_comparison_counts_each_direction_before_averaging(self):
        st = self.stops
        places = frame(self.out / 'places.csv')
        assignments = frame(self.case / 'vehicle_assignments.csv')
        person_vehicle = dict(zip(assignments.person_id, assignments.vehicle_id))
        residents = {r.place_id: {person_vehicle[p] for p in str(r.home_of_assigned_persons).split(';')} for r in places.itertuples() if pd.notna(r.home_of_assigned_persons)}
        candidates = st[st.assigned_person_id.notna() & st.place_id.isin(places.loc[places.place_type.isin(['home', 'other']), 'place_id'])].copy()
        day0 = st.stop_start.dt.normalize().min()
        ndays = (st.stop_end.dt.normalize().max() - day0).days + 1
        trials = []
        for k in range(1, ndays):
            shifted = candidates.copy()
            offset = pd.Timedelta(days=k)
            wrap = pd.to_timedelta(((shifted.stop_start + offset) >= day0 + pd.Timedelta(days=ndays)).astype(int) * ndays, unit='D')
            shifted['stop_start'] = shifted.stop_start + offset - wrap
            shifted['stop_end'] = shifted.stop_end + offset - wrap
            direction_counts = []
            for left, right in [(candidates, shifted), (shifted, candidates)]:
                pairs = left.merge(right, on='place_id', suffixes=('_a', '_b'))
                pairs = pairs[pairs.vehicle_id_a < pairs.vehicle_id_b].copy()
                starts = np.maximum(pairs.stop_start_a.values, pairs.stop_start_b.values)
                ends = np.minimum(pairs.stop_end_a.values, pairs.stop_end_b.values)
                minutes = np.round((ends - starts) / np.timedelta64(1, 'm'), 1)
                pairs['day'] = pd.to_datetime(starts).normalize()
                valid = [not(a in residents.get(p, ()) and b in residents.get(p, ())) for a, b, p in zip(pairs.vehicle_id_a, pairs.vehicle_id_b, pairs.place_id)]
                pairs = pairs[(minutes >= 10) & np.asarray(valid, dtype=bool)]
                direction_counts.append(pairs.groupby(['vehicle_id_a', 'vehicle_id_b']).day.nunique())
            trials.append(direction_counts[0].add(direction_counts[1], fill_value=0) / 2)
        null = pd.concat(trials, axis=1).fillna(0)
        differences = []
        for row in self.relationships.itertuples():
            key = (row.vehicle_id_a, row.vehicle_id_b)
            expected = 1.0 if row.private_days == 0 else round(float(((null.loc[key] >= row.private_days).sum() + 1) / (null.shape[1] + 1)), 3) if key in null.index else round(1 / (null.shape[1] + 1), 3)
            if abs(row.chance_p_value - expected) > .0001:
                differences.append((key, row.chance_p_value, expected))
        self.assertEqual(differences, [], 'Null trial day counts must not be divided after deduplicating both directions')

    def test_every_exported_relationship_has_supporting_events(self):
        rel = self.relationships
        displayed = rel[rel.relationship_type != 'WORKPLACE_ONLY']
        self.assertTrue(displayed.supporting_colocation_ids.fillna('').str.len().gt(0).all())

    def test_overlay_has_nodes_and_stable_evidence_keys(self):
        path = self.out / 'derived_graph_nodes.csv'
        self.assertTrue(path.is_file(), 'Card and loyalty endpoints need nodes for graph rendering')
        nodes = frame(path)
        edges = frame(self.out / 'derived_graph_edges.csv')
        self.assertTrue(set(edges.source_id) | set(edges.target_id) <= set(nodes.node_id))
        self.assertIn('evidence_key', edges.columns)
        self.assertTrue(edges.evidence_key.fillna('').str.len().gt(0).all())

    def test_source_persons_and_communications_are_unchanged(self):
        with zipfile.ZipFile(ROOT / 'datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip') as z:
            for name in ['persons.csv', 'communications.csv', 'location_events.csv']:
                self.assertEqual(hashlib.sha256((self.case / name).read_bytes()).digest(), hashlib.sha256(z.read(name)).digest())
        people = frame(self.case / 'persons.csv')
        self.assertEqual(len(people), 54)
        self.assertTrue(people.person_id.is_unique)
        mentions = frame(self.out / 'document_mentions.csv')
        self.assertTrue(set(mentions.loc[mentions.entity_type == 'PERSON', 'entity_id']) <= set(people.person_id))

    def test_email_evidence_is_not_fabricated_phone_calls(self):
        self.assertFalse((self.case / 'cdr_records.csv').exists())
        comms = frame(self.case / 'communications.csv')
        self.assertEqual(set(comms.communication_type), {'email'})
        quarantine = frame(self.case / 'evidence/unresolved_email_endpoints.csv')
        used = set(';'.join(self.relationships.email_ids.fillna('')).split(';')) - {''}
        self.assertFalse(used & set(quarantine.communication_id))

    def test_validator_rejects_missing_overlay_nodes(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / 'derived'
            shutil.copytree(self.out, target)
            nodes = frame(target / 'derived_graph_nodes.csv')
            nodes.iloc[1:].to_csv(target / 'derived_graph_nodes.csv', index=False)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(self.case), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, 'Validator must reject an overlay with an absent endpoint')
            self.assertIn('FAIL overlay: unique nodes cover every endpoint', result.stdout)

    def test_validator_accepts_the_regenerated_case(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(self.case), str(self.out)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_rejects_support_from_a_different_vehicle_pair(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / 'derived'
            shutil.copytree(self.out, target)
            relationships = frame(target / 'colocation_relationships.csv')
            co = frame(target / 'colocation_events.csv')
            first = relationships.iloc[0]
            unrelated = co[(co.vehicle_id_a != first.vehicle_id_a) | (co.vehicle_id_b != first.vehicle_id_b)].iloc[0]
            relationships.loc[0, 'supporting_colocation_ids'] = unrelated.colocation_id
            relationships.to_csv(target / 'colocation_relationships.csv', index=False)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(self.case), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, 'Existing IDs alone do not establish support for this pair')
            self.assertIn('FAIL leads: supporting events belong to this vehicle pair', result.stdout)

    def test_validator_rejects_fabricated_overlap_times(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / 'derived'
            shutil.copytree(self.out, target)
            co = frame(target / 'colocation_events.csv')
            co.loc[0, 'overlap_start'] = '2099-01-01 00:00:00'
            co.loc[0, 'overlap_end'] = '2099-01-01 00:30:00'
            co.to_csv(target / 'colocation_events.csv', index=False)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(self.case), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, 'Validator must recompute the interval from its supporting stops')
            self.assertIn('FAIL co-location: exact overlap interval and duration recomputed', result.stdout)

    def test_validator_rejects_invalid_private_support(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / 'derived'
            shutil.copytree(self.out, target)
            relationships = frame(target / 'colocation_relationships.csv')
            relationships.loc[0, 'supporting_private_colocation_ids'] = 'CO_DOES_NOT_EXIST'
            relationships.to_csv(target / 'colocation_relationships.csv', index=False)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(self.case), str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FAIL leads: private support matches private-context events', result.stdout)

    def test_validator_preserves_leading_zero_card_suffixes(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / 'derived'
            case = Path(scratch) / 'case'
            shutil.copytree(self.out, target)
            shutil.copytree(self.case, case)
            links = frame(target / 'loyalty_card_links.csv', dtype={'card_last4': str})
            old = links.loc[links.status == 'weak', 'card_last4'].iloc[0]
            tx = frame(case / 'transactions.csv', dtype={'card_last4': str})
            self.assertNotIn('0012', set(tx.card_last4))
            tx.loc[tx.card_last4 == old, 'card_last4'] = '0012'
            tx.to_csv(case / 'transactions.csv', index=False)
            cards = frame(target / 'card_owner_inference.csv', dtype={'card_last4': str})
            cards.loc[cards.card_last4 == old, 'card_last4'] = '0012'
            cards.to_csv(target / 'card_owner_inference.csv', index=False)
            links.loc[links.card_last4 == old, 'card_last4'] = '0012'
            links['link_key'] = links.card_last4 + '|' + links.loyalty_number
            links.to_csv(target / 'loyalty_card_links.csv', index=False)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_derived.py'), str(case), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
