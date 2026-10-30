"""Check that every derived row points at real rows of the validated case and follows the layer's rules.
Usage: python scripts/validate_derived.py <extracted_case_dir> derived
"""
import json, sys
from pathlib import Path
import pandas as pd
import numpy as np

CASE, D = Path(sys.argv[1]), Path(sys.argv[2])
checks = []
def check(n, ok, detail=""):
    checks.append(dict(check=n, passed=bool(ok), detail=detail))
    print(("PASS " if ok else "FAIL ") + n + (f"  [{detail}]" if detail else ""))

R = lambda p, **k: pd.read_csv(p, low_memory=False, **k)
people = R(CASE / "persons.csv")
persons = set(people.person_id)
check("persons: source IDs present and unique", people.person_id.notna().all() and people.person_id.is_unique)
assign = R(CASE / "vehicle_assignments.csv"); vp = dict(zip(assign.vehicle_id, assign.person_id))
check("persons: assignments reference known source identities", assign.person_id.isin(persons).all() and assign.vehicle_id.is_unique)
gps_rows = R(CASE / "location_events.csv", usecols=["event_id", "vehicle_id", "location_id", "timestamp"])
gps_rows["t"] = pd.to_datetime(gps_rows.timestamp)
gps_rows = gps_rows.sort_values(["vehicle_id", "t"])
gps_rows["next_id"] = gps_rows.groupby("vehicle_id").event_id.shift(-1)
gps_rows["next_t"] = gps_rows.groupby("vehicle_id").t.shift(-1)
gps_index = gps_rows.set_index("event_id")
gps = set(gps_index.index)
tx = R(CASE / "transactions.csv", dtype={"card_last4": str}); txids = set(tx.transaction_id)
loy = set(R(CASE / "loyalty_events.csv").loyalty_event_id)
ce = R(CASE / "evidence" / "communication_events.csv"); ceids = set(ce.communication_id)
quarantined = set(R(CASE / "evidence" / "unresolved_email_endpoints.csv").communication_id)

st = R(D / "vehicle_stops.csv", parse_dates=["stop_start", "stop_end"])
check("stops: both bounding GPS rows exist", st.last_gps_event_id.isin(gps).all() and st.next_gps_event_id.isin(gps).all(), f"{len(st)} stops")
check("stops: end after start", (st.stop_end > st.stop_start).all())
check("stops: person only via verified assignment",
      all(pd.isna(p) or vp.get(v) == p for v, p in zip(st.vehicle_id, st.assigned_person_id)))
check("stops: attribution label present", st.person_attribution.isin(["assigned_driver_assumed", "unassigned_vehicle"]).all())
check("stops: inferred stationary only within 50 m", st.boundary_distance_m.between(0, 50).all() and (st.inference_status == "inferred_stationary").all())
uncertain = R(D / "uncertain_vehicle_gaps.csv", parse_dates=["stop_start", "stop_end"])
check("stops: uncertain gaps excluded from positive evidence", uncertain.boundary_distance_m.gt(50).all() and (uncertain.inference_status == "uncertain_gap").all() and not (set(uncertain.stop_id) & set(st.stop_id)), f"{len(uncertain)} uncertain gaps")
all_gaps = pd.concat([st, uncertain], ignore_index=True)
starts = gps_index.reindex(all_gaps.last_gps_event_id)
ends = gps_index.reindex(all_gaps.next_gps_event_id)
check("stops: endpoints are consecutive source rows for the same vehicle",
      (starts.vehicle_id.values == all_gaps.vehicle_id.values).all() and (ends.vehicle_id.values == all_gaps.vehicle_id.values).all() and (starts.next_id.values == all_gaps.next_gps_event_id.values).all())
check("stops: intervals equal the two source timestamps", (starts.t.values == all_gaps.stop_start.values).all() and (ends.t.values == all_gaps.stop_end.values).all())
locations = R(CASE / "locations.csv").set_index("location_id")
start_lat = starts.location_id.map(locations.latitude).to_numpy()
start_lon = starts.location_id.map(locations.longitude).to_numpy()
end_lat = ends.location_id.map(locations.latitude).to_numpy()
end_lon = ends.location_id.map(locations.longitude).to_numpy()
check("stops: positions equal source coordinate bins", np.allclose(all_gaps.lat, start_lat) and np.allclose(all_gaps.lon, start_lon) and np.allclose(all_gaps.next_lat, end_lat) and np.allclose(all_gaps.next_lon, end_lon))
la1, lo1, la2, lo2 = np.radians(np.array([start_lat, start_lon, end_lat, end_lon]))
hav = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
distance = 6371000 * 2 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))
check("stops: displacement recomputed from source", np.allclose(all_gaps.boundary_distance_m, distance, atol=.001))
expected_gaps = gps_rows[(gps_rows.next_t - gps_rows.t).dt.total_seconds() >= 300]
check("stops: every source gap retained once as eligible or uncertain", all_gaps.last_gps_event_id.is_unique and set(all_gaps.last_gps_event_id) == set(expected_gaps.event_id))

co = R(D / "colocation_events.csv", parse_dates=["overlap_start", "overlap_end"])
s = st.set_index("stop_id")
a, b = s.reindex(co.stop_a), s.reindex(co.stop_b)
check("co-location: both stops exist", co.stop_a.isin(s.index).all() and co.stop_b.isin(s.index).all(), f"{len(co)} events")
check("co-location: stops really overlap >= 10 min",
      ((a.stop_start.values < b.stop_end.values) & (b.stop_start.values < a.stop_end.values)).all() and (co.overlap_min >= 10).all())
check("co-location: same place", (a.place_id.values == b.place_id.values).all())
check("co-location: vehicles match stops", (a.vehicle_id.values == co.vehicle_id_a.values).all() and (b.vehicle_id.values == co.vehicle_id_b.values).all())
expected_start = np.maximum(a.stop_start.values, b.stop_start.values)
expected_end = np.minimum(a.stop_end.values, b.stop_end.values)
check("co-location: exact overlap interval and duration recomputed",
      (expected_start == co.overlap_start.values).all() and (expected_end == co.overlap_end.values).all()
      and np.allclose(np.round((expected_end - expected_start) / np.timedelta64(1, "m"), 1), co.overlap_min))
check("co-location: people use assignment assumptions only", all(vp.get(v) == p for v, p in zip(co.vehicle_id_a, co.person_a)) and all(vp.get(v) == p for v, p in zip(co.vehicle_id_b, co.person_b)) and (co.person_attribution == "assigned_driver_assumed").all())

rel = R(D / "colocation_relationships.csv")
sup = set(";".join(rel.supporting_colocation_ids.fillna("")).split(";")) - {""}
check("leads: supporting event ids exist", sup <= set(co.colocation_id))
check("leads: every relationship has supporting events", rel.supporting_colocation_ids.fillna("").str.len().gt(0).all())
co_index = co.set_index("colocation_id")
support_matches = True
private_support_matches = True
for row in rel.itertuples():
    ids = str(row.supporting_colocation_ids).split(";") if pd.notna(row.supporting_colocation_ids) else []
    supporting = co_index.reindex(ids)
    support_matches &= (supporting.vehicle_id_a == row.vehicle_id_a).all() and (supporting.vehicle_id_b == row.vehicle_id_b).all()
    private_ids = set(str(row.supporting_private_colocation_ids).split(";")) if pd.notna(row.supporting_private_colocation_ids) else set()
    expected_private = set(supporting.index[supporting.context.isin(["home_visit", "third_party_home", "low_traffic_place"])])
    private_support_matches &= private_ids == expected_private
check("leads: supporting events belong to this vehicle pair", support_matches)
check("leads: private support matches private-context events", private_support_matches)
check("leads: persons known", rel.person_a.isin(persons).all() and rel.person_b.isin(persons).all())
used = set(";".join(rel.email_ids.fillna("")).split(";")) - {""}
check("leads: email ids exist in case", used <= ceids)
check("leads: quarantined alias emails never used", not (used & quarantined))
check("leads: strong/medium/weak only with >= 2 days", (rel[rel.lead_level.isin(["strong", "medium", "weak"])].private_days >= 2).all())
check("leads: every pair lists possible innocent explanations", rel.possible_innocent_explanations.fillna("").str.len().gt(0).all())
check("leads: lead strength in 0..100", rel.lead_strength.between(0, 100).all())

cards = R(D / "card_owner_inference.csv", dtype={"card_last4": str}); inf = cards[cards.status == "inferred"]
ev = R(D / "card_owner_evidence.csv")
check("cards: evidence purchases exist", ev.transaction_id.isin(txids).all(), f"{len(inf)} cards inferred")
check("cards: evidence stops exist", ev.stop_id.isin(s.index).all())
check("cards: person = assigned person of vehicle", all(vp[v] == p for v, p in zip(inf.best_vehicle_id, inf.best_assigned_person_id)))
check("cards: inferred only with >= 2x runner-up", (inf.dominance_ratio.fillna(99) >= 2).all())
check("cards: ownership unresolved without verified merchant mapping", (cards.status == "unresolved").all() and cards.best_vehicle_id.isna().all() and cards.best_assigned_person_id.isna().all() and ev.empty)
check("cards: all source card identifiers retained", set(cards.card_last4) == set(tx.card_last4.astype(str)))

lp = R(D / "loyalty_card_links.csv", dtype={"card_last4": str})
check("loyalty: purchase ids exist", set(";".join(lp.transaction_ids).split(";")) <= txids)
check("loyalty: loyalty ids exist", set(";".join(lp.loyalty_event_ids).split(";")) <= loy)

mn = R(D / "document_mentions.csv")
cache = {}
ok = True
for r in mn.itertuples():
    t = cache.setdefault(r.text_file, (CASE / r.text_file).read_text(encoding="utf-8"))
    ok &= t[r.start_char:r.end_char] == r.matched_text
check("mentions: offsets point at the matched text in the case document", ok, f"{len(mn)} mentions")
check("mentions: all proposed for review", (mn.status == "proposed_needs_review").all())
check("mentions: person proposals reference source identities", mn.loc[mn.entity_type == "PERSON", "entity_id"].isin(persons).all())

nodes = R(D / "derived_graph_nodes.csv")
edges = R(D / "derived_graph_edges.csv")
check("overlay: unique nodes cover every endpoint", nodes.node_id.is_unique and (set(edges.source_id) | set(edges.target_id)) <= set(nodes.node_id))
check("overlay: all edges marked inferred", edges.is_inferred.all())
check("overlay: evidence keys present", edges.evidence_key.notna().all() and edges.evidence_key.str.len().gt(0).all())
relationships = rel.set_index("relationship_key")
loyalty_links = lp.set_index("link_key")
overlay_support = True
for edge in edges.itertuples():
    if edge.evidence_table == "colocation_relationships.csv" and edge.evidence_key in relationships.index:
        record = relationships.loc[edge.evidence_key]
        overlay_support &= edge.source_id == record.person_a and edge.target_id == record.person_b and edge.relationship_type == record.relationship_type
    elif edge.evidence_table == "loyalty_card_links.csv" and edge.evidence_key in loyalty_links.index:
        record = loyalty_links.loc[edge.evidence_key]
        overlay_support &= edge.source_id == "CARD_" + str(record.card_last4) and edge.target_id == "LOYALTY_" + str(record.loyalty_number) and record.status == "linked"
    else:
        overlay_support = False
check("overlay: evidence key resolves to the actual edge", overlay_support)

(D / "VALIDATION_REPORT.json").write_text(json.dumps(dict(passed=sum(c["passed"] for c in checks), total=len(checks), checks=checks), indent=1))
print(f"\n{sum(c['passed'] for c in checks)}/{len(checks)} checks passed")
sys.exit(0 if all(c["passed"] for c in checks) else 1)
