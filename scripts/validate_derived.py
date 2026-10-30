"""Check that every derived row points at real rows of the validated case and follows the layer's rules.
Usage: python scripts/validate_derived.py <extracted_case_dir> derived
"""
import json, sys
from pathlib import Path
import pandas as pd

CASE, D = Path(sys.argv[1]), Path(sys.argv[2])
checks = []
def check(n, ok, detail=""):
    checks.append(dict(check=n, passed=bool(ok), detail=detail))
    print(("PASS " if ok else "FAIL ") + n + (f"  [{detail}]" if detail else ""))

R = lambda p, **k: pd.read_csv(p, low_memory=False, **k)
persons = set(R(CASE / "persons.csv").person_id)
assign = R(CASE / "vehicle_assignments.csv"); vp = dict(zip(assign.vehicle_id, assign.person_id))
gps = set(R(CASE / "location_events.csv", usecols=["event_id"]).event_id)
tx = R(CASE / "transactions.csv"); txids = set(tx.transaction_id)
loy = set(R(CASE / "loyalty_events.csv").loyalty_event_id)
ce = R(CASE / "evidence" / "communication_events.csv"); ceids = set(ce.communication_id)
quarantined = set(R(CASE / "evidence" / "unresolved_email_endpoints.csv").communication_id)

st = R(D / "vehicle_stops.csv", parse_dates=["stop_start", "stop_end"])
check("stops: every stop ends on a real GPS row", st.last_gps_event_id.isin(gps).all(), f"{len(st)} stops")
check("stops: end after start", (st.stop_end > st.stop_start).all())
check("stops: person only via verified assignment",
      all(pd.isna(p) or vp.get(v) == p for v, p in zip(st.vehicle_id, st.assigned_person_id)))
check("stops: attribution label present", st.person_attribution.isin(["assigned_driver_assumed", "unassigned_vehicle"]).all())

co = R(D / "colocation_events.csv", parse_dates=["overlap_start", "overlap_end"])
s = st.set_index("stop_id")
a, b = s.loc[co.stop_a], s.loc[co.stop_b]
check("co-location: both stops exist", co.stop_a.isin(s.index).all() and co.stop_b.isin(s.index).all(), f"{len(co)} events")
check("co-location: stops really overlap >= 10 min",
      ((a.stop_start.values < b.stop_end.values) & (b.stop_start.values < a.stop_end.values)).all() and (co.overlap_min >= 10).all())
check("co-location: same place", (a.place_id.values == b.place_id.values).all())
check("co-location: vehicles match stops", (a.vehicle_id.values == co.vehicle_id_a.values).all() and (b.vehicle_id.values == co.vehicle_id_b.values).all())

rel = R(D / "colocation_relationships.csv")
sup = set(";".join(rel.supporting_colocation_ids.fillna("")).split(";")) - {""}
check("leads: supporting event ids exist", sup <= set(co.colocation_id))
check("leads: persons known", rel.person_a.isin(persons).all() and rel.person_b.isin(persons).all())
used = set(";".join(rel.email_ids.fillna("")).split(";")) - {""}
check("leads: email ids exist in case", used <= ceids)
check("leads: quarantined alias emails never used", not (used & quarantined))
check("leads: strong/medium/weak only with >= 2 days", (rel[rel.lead_level.isin(["strong", "medium", "weak"])].private_days >= 2).all())
check("leads: every pair lists possible innocent explanations", rel.possible_innocent_explanations.fillna("").str.len().gt(0).all())
check("leads: lead strength in 0..100", rel.lead_strength.between(0, 100).all())

cards = R(D / "card_owner_inference.csv"); inf = cards[cards.status == "inferred"]
ev = R(D / "card_owner_evidence.csv")
check("cards: evidence purchases exist", ev.transaction_id.isin(txids).all(), f"{len(inf)} cards inferred")
check("cards: evidence stops exist", ev.stop_id.isin(s.index).all())
check("cards: person = assigned person of vehicle", all(vp[v] == p for v, p in zip(inf.best_vehicle_id, inf.best_assigned_person_id)))
check("cards: inferred only with >= 2x runner-up", (inf.dominance_ratio.fillna(99) >= 2).all())

lp = R(D / "loyalty_card_links.csv")
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

(D / "VALIDATION_REPORT.json").write_text(json.dumps(dict(passed=sum(c["passed"] for c in checks), total=len(checks), checks=checks), indent=1))
print(f"\n{sum(c['passed'] for c in checks)}/{len(checks)} checks passed")
sys.exit(0 if all(c["passed"] for c in checks) else 1)
