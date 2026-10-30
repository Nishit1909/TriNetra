"""Derived evidence layer for the validated GAStech case.

Reads the prepared case (GASTECH_MC1_MC2_VALIDATED_CASE.zip, extracted) and writes derived/:
conclusions that point back to the case's own rows. Nothing in the case is modified.

Rules
- GPS is vehicle evidence. Stops and co-location are computed per VEHICLE. A person is attached
  only through the verified assignment table and labelled `assigned_driver_assumed`.
- Email endpoints that the case quarantined (unresolved alias) are not used.
- Leads are scored, compared against chance (day-shifted null model), and listed with possible
  innocent explanations. Nothing is an accusation.

Usage: python scripts/derive_evidence.py <extracted_case_dir> <out_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

CASE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

STOP_GAP_MIN = 5          # A gap proposes a stop; both endpoints must also be nearby.
STOP_MAX_DISPLACEMENT_M = 50
PLACE_RADIUS_M = 50       # fixed-radius place clustering (no chaining)
MIN_OVERLAP_MIN = 10      # parked together >= 10 min
BUSY_PLACE_VEHICLES = 10  # a place visited by >= 10 vehicles is public/busy
BROADCAST = 10            # emails to >= 10 recipients are broadcasts
EARTH_R = 6_371_000
ATTR = "assigned_driver_assumed"

log = []
def note(m):
    print(m); log.append(m)

persons = pd.read_csv(CASE / "persons.csv")
assign = pd.read_csv(CASE / "vehicle_assignments.csv")
veh_person = dict(zip(assign.vehicle_id, assign.person_id))
name = dict(zip(persons.person_id, persons.display_name))
dept = dict(zip(persons.person_id, persons.department))
title = dict(zip(persons.person_id, persons.job_title))
if not persons.person_id.is_unique or persons.person_id.isna().any():
    raise ValueError("Person IDs must be present and unique; display names are not identity keys")
if not assign.person_id.isin(persons.person_id).all() or not assign.vehicle_id.is_unique:
    raise ValueError("Assignments must reference known people and one assigned person per vehicle")

# ------------------------------------------------------------------ stops (vehicle level)
le = pd.read_csv(CASE / "location_events.csv", usecols=["event_id", "vehicle_id", "location_id", "timestamp"])
loc = pd.read_csv(CASE / "locations.csv").set_index("location_id")
le["t"] = pd.to_datetime(le.timestamp)
le = le.sort_values(["vehicle_id", "t"]).reset_index(drop=True)
le["lat"] = le.location_id.map(loc.latitude)
le["lon"] = le.location_id.map(loc.longitude)
nxt = le.groupby("vehicle_id").t.shift(-1)
le["next_gps_event_id"] = le.groupby("vehicle_id").event_id.shift(-1)
le["next_lat"] = le.groupby("vehicle_id").lat.shift(-1)
le["next_lon"] = le.groupby("vehicle_id").lon.shift(-1)
gap = (nxt - le.t).dt.total_seconds() / 60
st = le[gap >= STOP_GAP_MIN].copy()
st["stop_start"], st["stop_end"] = st.t, nxt[gap >= STOP_GAP_MIN]
st["duration_min"] = gap[gap >= STOP_GAP_MIN].round(1)
st = st.reset_index(drop=True)
st["stop_id"] = [f"VS{i:05d}" for i in range(1, len(st) + 1)]
st["assigned_person_id"] = st.vehicle_id.map(veh_person)
st["person_attribution"] = np.where(st.assigned_person_id.notna(), ATTR, "unassigned_vehicle")
la1, lo1, la2, lo2 = np.radians(st[["lat", "lon", "next_lat", "next_lon"]].to_numpy()).T
hav = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
st["boundary_distance_m"] = EARTH_R * 2 * np.arcsin(np.sqrt(np.clip(hav, 0, 1)))
st["inference_status"] = np.where(st.boundary_distance_m <= STOP_MAX_DISPLACEMENT_M,
                                   "inferred_stationary", "uncertain_gap")
uncertain = st[st.inference_status == "uncertain_gap"].copy()
uncertain.rename(columns={"event_id": "last_gps_event_id"})[[
    "stop_id", "vehicle_id", "assigned_person_id", "person_attribution", "lat", "lon", "next_lat", "next_lon",
    "stop_start", "stop_end", "duration_min", "last_gps_event_id", "next_gps_event_id", "boundary_distance_m",
    "inference_status"]].to_csv(OUT / "uncertain_vehicle_gaps.csv", index=False)
st = st[st.inference_status == "inferred_stationary"].reset_index(drop=True)
if st.empty:
    raise ValueError("No spatially consistent stop candidates; no co-location can be inferred")

# ------------------------------------------------------------------ places
xy = np.radians(st[["lat", "lon"]].values)
tree = BallTree(xy, metric="haversine")
nb = tree.query_radius(xy, r=PLACE_RADIUS_M / EARTH_R)
lab = np.full(len(xy), -1)
c = 0
for i in np.argsort([-len(n) for n in nb], kind="stable"):
    if lab[i] == -1:
        m = [j for j in nb[i] if lab[j] == -1]
        lab[m] = c
        c += 1
st["place_id"] = ["PL%04d" % k for k in lab]
places = st.groupby("place_id").agg(lat=("lat", "mean"), lon=("lon", "mean"), stops=("stop_id", "size"),
                                    vehicles=("vehicle_id", "nunique")).reset_index()

wk = st[(st.stop_start.dt.weekday < 5) & st.stop_start.dt.hour.between(7, 10) & (st.duration_min >= 180)]
wc = wk.groupby("place_id").vehicle_id.nunique()
workplaces = set(wc[wc >= max(5, 0.25 * assign.vehicle_id.nunique())].index)
night = st[((st.stop_start.dt.hour >= 17) | (st.stop_start.dt.hour <= 2)) & (st.duration_min >= 360) & st.assigned_person_id.notna()]
nc = night.groupby(["vehicle_id", "place_id"]).size().reset_index(name="nights")
home = nc[(nc.nights >= 2) & ~nc.place_id.isin(workplaces)]
home_vehicles = home.groupby("place_id").vehicle_id.agg(set).to_dict()
home_of_vehicle = home.sort_values("nights", ascending=False).drop_duplicates("vehicle_id").set_index("vehicle_id").place_id.to_dict()
places["place_type"] = [
    "workplace" if p in workplaces else "home" if p in home_vehicles else
    "busy_public" if v >= BUSY_PLACE_VEHICLES else "other" for p, v in zip(places.place_id, places.vehicles)]
places["home_of_assigned_persons"] = places.place_id.map(
    lambda p: ";".join(sorted(veh_person.get(v, v) for v in home_vehicles.get(p, ()))))
places.to_csv(OUT / "places.csv", index=False)
st[["stop_id", "vehicle_id", "assigned_person_id", "person_attribution", "place_id", "lat", "lon",
    "stop_start", "stop_end", "duration_min", "event_id", "next_gps_event_id", "next_lat", "next_lon",
    "boundary_distance_m", "inference_status"]].rename(columns={"event_id": "last_gps_event_id"}) \
    .to_csv(OUT / "vehicle_stops.csv", index=False)
note(f"Stops: {len(st)} inferred stationary intervals; {len(uncertain)} uncertain GPS gaps excluded; "
     f"from {le.vehicle_id.nunique()} vehicles; places {len(places)} "
     f"(workplace {len(workplaces)}, homes {len(home_vehicles)} for {home.vehicle_id.nunique()} vehicles).")

# ------------------------------------------------------------------ co-location (vehicle pairs)
ptype = dict(zip(places.place_id, places.place_type))
pv = st[st.assigned_person_id.notna()][["stop_id", "vehicle_id", "place_id", "stop_start", "stop_end"]]

def overlaps(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    m = a.merge(b, on="place_id", suffixes=("_a", "_b"))
    m = m[m.vehicle_id_a < m.vehicle_id_b]
    s_ = np.maximum(m.stop_start_a.values, m.stop_start_b.values)
    e_ = np.minimum(m.stop_end_a.values, m.stop_end_b.values)
    ov = (e_ - s_) / np.timedelta64(1, "m")
    m = m.assign(overlap_start=s_, overlap_end=e_, overlap_min=np.round(ov, 1))
    return m[m.overlap_min >= MIN_OVERLAP_MIN]

co = overlaps(pv, pv).reset_index(drop=True)
co["place_type"] = co.place_id.map(ptype)
res_a = [v in home_vehicles.get(p, ()) for v, p in zip(co.vehicle_id_a, co.place_id)]
res_b = [v in home_vehicles.get(p, ()) for v, p in zip(co.vehicle_id_b, co.place_id)]
co["a_home_here"], co["b_home_here"] = res_a, res_b
both, one = co.a_home_here & co.b_home_here, co.a_home_here ^ co.b_home_here
co["context"] = np.select([co.place_type == "workplace", both, one, co.place_type == "home", co.place_type == "busy_public"],
                          ["workplace", "both_live_here", "home_visit", "third_party_home", "busy_public_place"], "low_traffic_place")
h = pd.to_datetime(co.overlap_start).dt.hour
co["after_hours"] = (pd.to_datetime(co.overlap_start).dt.weekday >= 5) | (h < 6) | (h >= 20)
co["visitor_vehicle"] = np.where(one & co.a_home_here, co.vehicle_id_b, np.where(one, co.vehicle_id_a, None))
co["person_a"], co["person_b"] = co.vehicle_id_a.map(veh_person), co.vehicle_id_b.map(veh_person)
co["person_attribution"] = ATTR
co.insert(0, "colocation_id", [f"CO{i:05d}" for i in range(1, len(co) + 1)])
co = co.rename(columns={"stop_id_a": "stop_a", "stop_id_b": "stop_b"})
co[["colocation_id", "vehicle_id_a", "vehicle_id_b", "person_a", "person_b", "person_attribution", "place_id", "place_type",
    "context", "visitor_vehicle", "overlap_start", "overlap_end", "overlap_min", "after_hours", "stop_a", "stop_b"]] \
    .to_csv(OUT / "colocation_events.csv", index=False)
note(f"Co-location: {len(co)} events {co.context.value_counts().to_dict()}.")

PRIVATE = ["home_visit", "third_party_home", "low_traffic_place"]

# ------------------------------------------------------------------ chance baseline: shift one side by k days
day0 = st.stop_start.dt.normalize().min()
ndays = (st.stop_end.dt.normalize().max() - day0).days + 1
priv_places = set(places.place_id[places.place_type.isin(["home", "other"])])
pp = pv[pv.place_id.isin(priv_places)].copy()
def private_mask(df):
    hv_a = [v in home_vehicles.get(p, ()) for v, p in zip(df.vehicle_id_a, df.place_id)]
    hv_b = [v in home_vehicles.get(p, ()) for v, p in zip(df.vehicle_id_b, df.place_id)]
    return ~(np.array(hv_a, dtype=bool) & np.array(hv_b, dtype=bool))  # co-residents are not meetings

def private_day_counts(df):
    df = df[private_mask(df)]
    return df.assign(day=pd.to_datetime(df.overlap_start).dt.normalize()) \
        .groupby(["vehicle_id_a", "vehicle_id_b"]).day.nunique()
null_counts = []
for k in range(1, ndays):
    b = pp.copy()
    off = pd.Timedelta(days=k)
    shifted = b.stop_start + off
    wrap = shifted >= day0 + pd.Timedelta(days=ndays)
    back = pd.to_timedelta(wrap.astype(int) * ndays, unit="D")
    b["stop_start"] = b.stop_start + off - back
    b["stop_end"] = b.stop_end + off - back
    # Deduplicate within each direction before averaging, rather than halving a union of days.
    cnt = private_day_counts(overlaps(pp, b)).add(private_day_counts(overlaps(b, pp)), fill_value=0) / 2
    null_counts.append(cnt.rename(k))
null = pd.concat(null_counts, axis=1).fillna(0) if null_counts else pd.DataFrame()

# ------------------------------------------------------------------ email evidence (resolved endpoints only)
ce = pd.read_csv(CASE / "evidence" / "communication_events.csv")
ce["t"] = pd.to_datetime(ce.timestamp, format="ISO8601")
rc = ce.groupby("header_sha256").communication_id.transform("size")
ce["is_broadcast"] = rc >= BROADCAST
ce = ce[ce.source_person_id.notna() & ce.target_person_id.notna() & (ce.source_person_id != ce.target_person_id)]
ce["u"] = ce[["source_person_id", "target_person_id"]].min(axis=1)
ce["v"] = ce[["source_person_id", "target_person_id"]].max(axis=1)
mail = ce.groupby(["u", "v"]).agg(email_events=("communication_id", "size"),
                                  direct_email_events=("is_broadcast", lambda x: int((~x).sum())),
                                  email_ids=("communication_id", lambda x: ";".join(x[:50]))).reset_index() \
    .rename(columns={"u": "person_a", "v": "person_b"})
note(f"Email: {len(ce)} resolved sender-recipient events (quarantined alias rows excluded), {len(mail)} pairs.")

# ------------------------------------------------------------------ pair relationships + lead scoring
pr = co[co.context.isin(PRIVATE)].copy()
pr["day"] = pd.to_datetime(pr.overlap_start).dt.normalize()
# how many vehicles were at that place during this overlap? (>= 3 = a group gathering, e.g. a lunch group)
grp = []
for r in pr.itertuples():
    here = pv[(pv.place_id == r.place_id) & (pv.stop_start < r.overlap_end) & (pv.stop_end > r.overlap_start)]
    grp.append(here.vehicle_id.nunique())
pr["vehicles_present"] = grp
pr["group_gathering"] = pr.vehicles_present >= 3
hh_ = pd.to_datetime(pr.overlap_start).dt.hour
pr["lunch_hours"] = (pd.to_datetime(pr.overlap_start).dt.weekday < 5) & hh_.between(11, 14)
co = co.merge(pr[["colocation_id", "vehicles_present", "group_gathering"]], on="colocation_id", how="left")
co[["colocation_id", "vehicle_id_a", "vehicle_id_b", "person_a", "person_b", "person_attribution", "place_id", "place_type",
    "context", "visitor_vehicle", "overlap_start", "overlap_end", "overlap_min", "after_hours", "vehicles_present",
    "group_gathering", "stop_a", "stop_b"]].to_csv(OUT / "colocation_events.csv", index=False)
rel = co.groupby(["vehicle_id_a", "vehicle_id_b"]).agg(
    person_a=("person_a", "first"), person_b=("person_b", "first"),
    supporting_colocation_ids=("colocation_id", lambda x: ";".join(x)),
    workplace_events=("context", lambda x: int((x == "workplace").sum())),
    public_place_events=("context", lambda x: int((x == "busy_public_place").sum())),
    both_live_here_events=("context", lambda x: int((x == "both_live_here").sum()))).reset_index()
agg = pr.groupby(["vehicle_id_a", "vehicle_id_b"]).agg(
    private_meetings=("colocation_id", "size"), private_days=("day", "nunique"),
    after_hours_private=("after_hours", "sum"), home_visits=("context", lambda x: int((x == "home_visit").sum())),
    private_places=("place_id", "nunique"),
    group_gatherings=("group_gathering", "sum"), lunch_hour_meetings=("lunch_hours", "sum"),
    supporting_private_colocation_ids=("colocation_id", lambda x: ";".join(x))).reset_index()
rel = rel.merge(agg, on=["vehicle_id_a", "vehicle_id_b"], how="left")
for col_ in ["private_meetings", "private_days", "after_hours_private", "home_visits", "private_places", "group_gatherings", "lunch_hour_meetings"]:
    rel[col_] = rel[col_].fillna(0).astype(int)
rel["supporting_private_colocation_ids"] = rel.supporting_private_colocation_ids.fillna("")
rel["relationship_key"] = rel.vehicle_id_a + "|" + rel.vehicle_id_b
key = list(zip(rel.vehicle_id_a, rel.vehicle_id_b))
rel["chance_expected_days"] = [round(float(null.loc[k].mean()), 2) if k in null.index else 0.0 for k in key]
rel["chance_p_value"] = [round(float(((null.loc[k] >= d).sum() + 1) / (null.shape[1] + 1)), 3) if k in null.index
                         else round(1 / (null.shape[1] + 1), 3) for k, d in zip(key, rel.private_days)]
rel.loc[rel.private_days == 0, "chance_p_value"] = 1.0
rel = rel.merge(mail, on=["person_a", "person_b"], how="left")
rel[["email_events", "direct_email_events"]] = rel[["email_events", "direct_email_events"]].fillna(0).astype(int)
rel["email_ids"] = rel.email_ids.fillna("")

def home_distance_m(a, b):
    pa, pb = home_of_vehicle.get(a), home_of_vehicle.get(b)
    if pa is None or pb is None:
        return None
    r1 = places.set_index("place_id").loc[[pa, pb]]
    la1, lo1, la2, lo2 = r1.lat.iloc[0], r1.lon.iloc[0], r1.lat.iloc[1], r1.lon.iloc[1]
    return float(EARTH_R * np.hypot(np.radians(la2 - la1), np.radians(lo2 - lo1) * np.cos(np.radians(la1))))

SECURITY = {"Security"}
EXEC = {"Executive"}
expl, scores, levels = [], [], []
for r in rel.itertuples():
    e = []
    if dept.get(r.person_a) == dept.get(r.person_b):
        e.append(f"same department ({dept.get(r.person_a)})")
    if r.direct_email_events > 0:
        e.append(f"normal work contact: {r.direct_email_events} direct email events")
    d = home_distance_m(r.vehicle_id_a, r.vehicle_id_b)
    if d is not None and d < 300:
        e.append(f"homes {int(d)} m apart (neighbours)")
    if r.home_visits > 0 and ({dept.get(r.person_a), dept.get(r.person_b)} & SECURITY):
        e.append("security staff at a home: could be patrol or protection duty")
    if r.private_days <= 1:
        e.append("single day only: could be coincidence")
    if r.private_meetings and r.group_gatherings / r.private_meetings >= 0.5:
        e.append(f"mostly group gatherings ({r.group_gatherings}/{r.private_meetings} with 3+ cars): likely a social or lunch group")
    if r.private_meetings and r.lunch_hour_meetings / r.private_meetings >= 0.5:
        e.append("mostly weekday lunch hours: likely a regular lunch spot")
    e.append("car assignment does not prove who was driving")
    expl.append("; ".join(e))
    # lead strength 0-100: repetition, timing, home visits, beating chance; minus explained-away context
    s = 0.0
    s += min(r.private_days, 5) / 5 * 35
    s += (r.after_hours_private / r.private_meetings if r.private_meetings else 0) * 15
    s += 15 if r.home_visits > 0 else 0
    s += 25 if r.chance_p_value <= 0.1 and r.private_days >= 2 else (10 if r.chance_p_value <= 0.25 and r.private_days >= 2 else 0)
    s += 10 if r.direct_email_events == 0 and r.private_days >= 2 else 0
    s -= 10 if dept.get(r.person_a) == dept.get(r.person_b) else 0
    s -= 15 if d is not None and d < 300 else 0
    gshare = r.group_gatherings / r.private_meetings if r.private_meetings else 0
    s -= 20 * gshare                     # group routines are weaker evidence of a hidden tie
    if r.after_hours_private == 0 and r.home_visits == 0:
        s = min(s, 45)                   # daytime-only, no home visit: at most a medium lead
    s = max(0.0, min(100.0, s))
    scores.append(round(s, 1))
    if r.private_days < 2:
        levels.append("not_a_lead" if r.private_days == 0 else "weak_single_day")
    else:
        levels.append("strong" if s >= 60 else "medium" if s >= 35 else "weak")
rel["lead_strength"] = scores
rel["lead_level"] = levels
rel["possible_innocent_explanations"] = expl
rel["relationship_type"] = np.select([rel.private_meetings > 0, rel.both_live_here_events > 0, rel.public_place_events > 0],
                                     ["MET_PRIVATELY", "LIVES_AT_SAME_PLACE", "SEEN_TOGETHER_IN_PUBLIC"], "WORKPLACE_ONLY")
rel["meets_privately_never_emails_directly"] = (rel.private_days >= 2) & (rel.direct_email_events == 0)
rel["person_attribution"] = ATTR
rel = rel.sort_values(["lead_strength", "private_days"], ascending=False)
rel.to_csv(OUT / "colocation_relationships.csv", index=False)
old = int(((rel.private_meetings > 0) & (rel.direct_email_events == 0)).sum())
note(f"Leads: 'meet privately, no direct email' was {old} pairs with any private meeting; "
     f"with >= 2 days it is {int(rel.meets_privately_never_emails_directly.sum())}. "
     f"Lead levels {rel.lead_level.value_counts().to_dict()}.")

# ------------------------------------------------------------------ card ownership remains unknown without merchant coordinates
tx = pd.read_csv(CASE / "transactions.csv", dtype={"card_last4": str})
tx["t"] = pd.to_datetime(tx.event_time)
cards = tx.groupby("card_last4").size().rename("card_purchases").reset_index()
for column in ["best_vehicle_id", "best_assigned_person_id", "best_score", "second_vehicle_id", "second_score", "dominance_ratio", "person_attribution"]:
    cards[column] = None
cards["status"] = "unresolved"
cards["reason"] = "merchant_locations_not_verified; purchase timing alone cannot establish card ownership"
cards["method"] = "not_inferred_without_spatial_evidence"
cards.to_csv(OUT / "card_owner_inference.csv", index=False)
pd.DataFrame(columns=["transaction_id", "card_last4", "merchant_location", "vehicle_id", "assigned_person_id", "stop_id",
                      "minutes_from_arrival_or_departure", "share"]).to_csv(OUT / "card_owner_evidence.csv", index=False)
note(f"Cards: 0/{len(cards)} attributed; ownership unresolved without verified merchant locations.")

# ------------------------------------------------------------------ loyalty <-> payment card (no driver assumption)
loy = pd.read_csv(CASE / "loyalty_events.csv", dtype={"loyalty_number": str})
tx["date"] = tx.t.dt.date
loy["date"] = pd.to_datetime(loy.event_time).dt.date
j = tx.merge(loy, on=["date", "merchant_location", "amount"])
lp = j.groupby(["card_last4", "loyalty_number"]).agg(matched_purchases=("transaction_id", "size"),
                                                      transaction_ids=("transaction_id", lambda x: ";".join(x)),
                                                      loyalty_event_ids=("loyalty_event_id", lambda x: ";".join(x))).reset_index()
lp = lp.sort_values("matched_purchases", ascending=False).drop_duplicates("card_last4")
lp["status"] = np.where(lp.matched_purchases >= 3, "linked", "weak")
lp["link_key"] = lp.card_last4.astype(str) + "|" + lp.loyalty_number.astype(str)
lp.to_csv(OUT / "loyalty_card_links.csv", index=False)
note(f"Loyalty: {int((lp.status=='linked').sum())} loyalty cards linked to payment cards (same day, shop, amount >= 3 times).")

# ------------------------------------------------------------------ document mentions (reviewable baseline)
man = pd.read_csv(CASE / "evidence" / "document_manifest.csv")
gaz = []
for pid, n in name.items():
    first, last = n.split(" ", 1)
    gaz += [(n, "PERSON", pid), (f"{last}, {first}", "PERSON", pid)]
for org in ["GAStech", "GASTech", "Protectors of Kronos", "POK", "Abila Police", "Kronos Government", "Tethys"]:
    gaz.append((org, "ORGANIZATION", org.upper().replace(" ", "_")))
pats = [(re.compile(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])"), lab_, ent) for t, lab_, ent in gaz]
ment = []
for d in man.itertuples():
    txt = (CASE / d.text_file).read_text(encoding="utf-8")
    for rx, lab_, ent in pats:
        for mm in rx.finditer(txt):
            ment.append(dict(document_id=d.document_id, text_file=d.text_file, entity_type=lab_, entity_id=ent,
                             matched_text=mm.group(0), start_char=mm.start(), end_char=mm.end(),
                             context=txt[max(0, mm.start() - 80): mm.end() + 80].replace("\n", " "),
                             method="dictionary_exact_name", status="proposed_needs_review"))
ment = pd.DataFrame(ment)
ment.to_csv(OUT / "document_mentions.csv", index=False)
note(f"Mentions: {len(ment)} in {ment.document_id.nunique()} documents ({ment.entity_type.value_counts().to_dict()}).")

# ------------------------------------------------------------------ derived graph edges
edges = pd.concat([
    pd.DataFrame({"source_id": rel.person_a, "target_id": rel.person_b, "relationship_type": rel.relationship_type,
                  "weight": np.round(np.log1p(rel.private_days * 3 + rel.public_place_events + rel.both_live_here_events * 0.5 + 0.1), 3),
                  "lead_strength": rel.lead_strength, "evidence_table": "colocation_relationships.csv", "evidence_key": rel.relationship_key,
                  "person_attribution": ATTR})[lambda d: d.relationship_type != "WORKPLACE_ONLY"],
    pd.DataFrame({"source_id": "CARD_" + lp[lp.status == "linked"].card_last4.astype(str),
                  "target_id": "LOYALTY_" + lp[lp.status == "linked"].loyalty_number.astype(str),
                  "relationship_type": "SAME_CUSTOMER_LIKELY", "weight": 1.0, "lead_strength": np.nan,
                  "evidence_table": "loyalty_card_links.csv", "evidence_key": lp[lp.status == "linked"].link_key,
                  "person_attribution": "none_needed"}),
], ignore_index=True)
edges.insert(0, "is_inferred", True)
edges.to_csv(OUT / "derived_graph_edges.csv", index=False)
nodes = []
for node_id in sorted(set(edges.source_id) | set(edges.target_id)):
    if node_id in name:
        node_type, label = "PERSON", name[node_id]
    elif node_id.startswith("CARD_"):
        node_type, label = "CARD", "Payment card ending " + node_id[5:]
    elif node_id.startswith("LOYALTY_"):
        node_type, label = "LOYALTY_CARD", "Loyalty card " + node_id[8:]
    else:
        raise ValueError(f"Unknown overlay endpoint: {node_id}")
    nodes.append(dict(node_id=node_id, node_type=node_type, label=label))
pd.DataFrame(nodes, columns=["node_id", "node_type", "label"]).to_csv(OUT / "derived_graph_nodes.csv", index=False)
(OUT / "derive_log.json").write_text(json.dumps(log, indent=1))
