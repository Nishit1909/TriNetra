"""Location evidence for uploaded cases: who was where, when -> places -> meetings -> inferred MET_PRIVATELY links.

Input  locations.csv: person_id, observed_at, latitude, longitude [, place_name, source]
Steps  1. points within PLACE_RADIUS_M (wider for cell towers) are grouped into places
       2. two people at the same place within MEETING_WINDOW_MIN of each other = one meeting
       3. places visited by many people (>= BUSY_SHARE of the case, min BUSY_MIN) are treated as public/workplace
       4. per pair, the same factors as the GAStech layer (private meeting days, after hours, home visits,
          group gatherings, more-than-chance) feed the model's existing inferred-link scoring.
Everything produced here is INFERRED and labelled so; cell-tower points are marked low precision.
"""
import math
from collections import defaultdict

import pandas as pd

PLACE_RADIUS_M = {"gps": 100, "cctv": 100, "witness": 150, "cell_tower": 1000, "other": 150}
MEETING_WINDOW_MIN = 30
BUSY_SHARE, BUSY_MIN = 0.4, 4
AFTER_HOURS = (20, 6)            # 20:00 - 06:00, plus weekends
HOME_WORDS = ("home", "house", "residence", "flat", "apartment")
SOURCES = set(PLACE_RADIUS_M)
SPEC = {"required": ["person_id", "observed_at", "latitude", "longitude"], "optional": ["place_name", "source"]}


def _dist_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def validate(df, ids, err, warnings):
    """Return a clean points DataFrame (or None)."""
    for col in SPEC["optional"]:
        if col not in df.columns:
            df[col] = None
    rows = []
    for i, row in df.iterrows():
        line = i + 2
        if row.person_id not in ids:
            err(f"locations.csv line {line}: person {row.person_id!r} is not in persons.csv.")
            continue
        t = pd.to_datetime(row.observed_at, errors="coerce") if isinstance(row.observed_at, str) else pd.NaT
        if pd.isna(t):
            err(f"locations.csv line {line}: observed_at {row.observed_at!r} is not a date/time.")
            continue
        try:
            lat, lon = float(row.latitude), float(row.longitude)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (TypeError, ValueError):
            err(f"locations.csv line {line}: latitude/longitude must be numbers (lat -90..90, lon -180..180).")
            continue
        src = (row.source or "gps").strip().lower() if isinstance(row.source, str) else "gps"
        if src not in SOURCES:
            warnings.append(f"locations.csv line {line}: unknown source {src!r}, treated as 'other'.")
            src = "other"
        name = row.place_name.strip()[:120] if isinstance(row.place_name, str) and row.place_name.strip() else None
        rows.append({"point_id": f"L{i + 1:07d}", "person_id": row.person_id,
                     "observed_at": (t.tz_convert(None) if t.tzinfo else t).to_pydatetime(),
                     "latitude": lat, "longitude": lon, "place_name": name, "source": src, "source_row": line})
    return pd.DataFrame(rows) if rows else None


def build(points, persons):
    """points -> (places, meetings, inferred, place_of). Pure function; no database."""
    # 1. places: greedy clustering, named places first so labels stick
    places = []                                   # dicts: place_id, lat, lon, label, radius, sources
    place_of = {}
    order = points.sort_values(["place_name", "observed_at"], na_position="last")
    for r in order.itertuples(index=False):
        radius = PLACE_RADIUS_M[r.source]
        best, best_d = None, None
        for pl in places:
            d = _dist_m(r.latitude, r.longitude, pl["latitude"], pl["longitude"])
            if d <= max(radius, pl["radius"]) and (best_d is None or d < best_d):
                best, best_d = pl, d
        if best is None:
            best = {"place_id": f"UP{len(places) + 1:04d}", "latitude": r.latitude, "longitude": r.longitude,
                    "label": r.place_name, "radius": radius, "people": set(), "points": 0, "sources": set()}
            places.append(best)
        if best["label"] is None and r.place_name:
            best["label"] = r.place_name
        best["people"].add(r.person_id)
        best["points"] += 1
        best["sources"].add(r.source)
        place_of[r.point_id] = best["place_id"]
    n_people = max(1, len(persons))
    busy_cut = max(BUSY_MIN, math.ceil(BUSY_SHARE * n_people))
    by_id = {}
    for pl in places:
        label = (pl["label"] or "").lower()
        pl["is_home"] = any(w in label for w in HOME_WORDS)
        pl["is_busy"] = len(pl["people"]) >= busy_cut and not pl["is_home"]
        pl["place_type"] = "home" if pl["is_home"] else ("public_or_workplace" if pl["is_busy"] else "private_or_small")
        pl["low_precision"] = pl["sources"] == {"cell_tower"}
        by_id[pl["place_id"]] = pl

    # 2. meetings: same place, within the window; one meeting per pair per place per hour-slot
    pts = points.assign(place_id=points.point_id.map(place_of)).sort_values("observed_at")
    window = pd.Timedelta(minutes=MEETING_WINDOW_MIN)
    seen, meetings = set(), []
    for pid, grp in pts.groupby("place_id"):
        recs = list(grp.itertuples(index=False))
        for i, a in enumerate(recs):
            present = {a.person_id}
            for b in recs[i + 1:]:
                if b.observed_at - a.observed_at > window:
                    break
                present.add(b.person_id)
            for b in recs[i + 1:]:
                if b.observed_at - a.observed_at > window:
                    break
                if b.person_id == a.person_id:
                    continue
                x, y = sorted((a.person_id, b.person_id))
                key = (x, y, pid, a.observed_at.strftime("%Y%m%d%H"))
                if key in seen:
                    continue
                seen.add(key)
                start, end = min(a.observed_at, b.observed_at), max(a.observed_at, b.observed_at)
                h = start.hour
                after = h >= AFTER_HOURS[0] or h < AFTER_HOURS[1] or start.weekday() >= 5
                pl = by_id[pid]
                low = pl["low_precision"] or "cell_tower" in (a.source, b.source)
                meetings.append({"meeting_id": f"M{len(meetings) + 1:06d}", "person_a": x, "person_b": y, "place_id": pid,
                                 "place_label": pl["label"], "place_type": pl["place_type"], "start_at": start, "end_at": end,
                                 "after_hours": after, "people_present": len(present), "low_precision": low,
                                 "point_a": a.point_id, "point_b": b.point_id})
    meet = pd.DataFrame(meetings)

    # 3. per-pair factors, same names the model's inferred scoring reads
    inferred = []
    if len(meet):
        days_total = max(1, pts.observed_at.dt.date.nunique())
        visit_days = defaultdict(set)              # (person, place) -> days
        for r in pts.itertuples(index=False):
            visit_days[(r.person_id, r.place_id)].add(r.observed_at.date())
        dept = dict(zip(persons.person_id, persons.department))
        for (x, y), g in meet.groupby(["person_a", "person_b"]):
            private = g[g.place_type != "public_or_workplace"]
            pub = g[g.place_type == "public_or_workplace"]
            pdays = private.start_at.dt.date.nunique()
            if pdays == 0:          # only ever together at busy public/work places: routine, not a lead
                continue
            # chance: expected shared private days if both kept their own visit days independently
            expected = sum(len(visit_days[(x, pl)]) * len(visit_days[(y, pl)]) / days_total
                           for pl in set(private.place_id))
            p_value = 1.0
            if pdays:
                lam = max(expected, 1e-9)
                p_value = 1.0 - sum(math.exp(-lam) * lam ** k / math.factorial(k) for k in range(pdays))
            factors = {"private_days": int(pdays), "private_meetings": int(len(private)),
                       "after_hours_private": int(private.after_hours.sum()),
                       "home_visits": int((private.place_type == "home").sum()),
                       "group_gatherings": int((private.people_present >= 3).sum()),
                       "public_place_events": int(len(pub)), "both_live_here_events": 0,
                       "chance_expected_days": round(expected, 2), "chance_p_value": round(max(0.0, p_value), 3),
                       "private_places": int(private.place_id.nunique()),
                       "low_precision_share": round(float(g.low_precision.mean()), 2), "evidence": "uploaded locations"}
            notes = []
            if factors["group_gatherings"] and factors["group_gatherings"] >= factors["private_meetings"] / 2:
                notes.append("often with 3+ people present: could be a social or work group")
            if dept.get(x) and dept.get(x) == dept.get(y):
                notes.append("same department: could be routine work contact")
            if factors["low_precision_share"] >= 0.5:
                notes.append("mostly cell-tower locations: a tower covers a wide area, so they may not have actually met")
            if not factors["after_hours_private"] and not factors["home_visits"]:
                notes.append("daytime only: could be an ordinary routine")
            notes.append("location shows presence, not interaction")
            inferred.append({"person_a": x, "person_b": y,
                             "relationship_type": "MET_PRIVATELY",
                             "factors": factors, "meeting_ids": g.meeting_id.tolist(),
                             "innocent": "; ".join(notes), "same_dept": bool(dept.get(x) and dept.get(x) == dept.get(y))})
    return places, meet, inferred, place_of


def score(inferred, weights):
    """Lead strength 0-100 using the model's own factor weights, so uploads and GAStech are scored alike."""
    from analysis_model.run_case_analysis import _inferred_contribution
    scale = weights.get("inferred_scale", 15.0)
    for row in inferred:
        pts = sum(_inferred_contribution(row["factors"], row["same_dept"], weights).values())
        s = max(0.0, min(100.0, 100.0 * pts / scale)) if scale else 0.0
        row["lead_strength"] = round(s, 1)
        row["lead_level"] = "strong" if s >= 60 else ("medium" if s >= 30 else "weak")   # same vocabulary as the GAStech layer
    return inferred
