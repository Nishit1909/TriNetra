"""Load the GAStech case (+ derived layer) and the Caviar case into the case-scoped schema `inv`.

Usage:
  python db/load_case.py --dsn postgresql://... --case-dir <extracted GASTECH case> \
      --derived-dir derived --caviar-dir cases/caviar [--migrate] [--replace]

--migrate  runs db/migrations/001_case_scoped_schema.sql first (fresh database only)
--replace  deletes an existing case (all its rows, via ON DELETE CASCADE) before loading it

Every row is written with its case_id. Nothing outside schema `inv` is touched.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

GASTECH = "CASE_VAST_GASTECH"
CAVIAR = "CASE_CAVIAR"
BROADCAST_RECIPIENTS = 10
HERE = Path(__file__).resolve().parent


def copy_df(cur, table: str, df: pd.DataFrame) -> int:
    """Bulk-load a DataFrame with COPY (NULL for missing values, Postgres array literals for lists)."""
    if df.empty:
        return 0
    out = df.copy()
    for c in out.columns:
        if out[c].map(lambda v: isinstance(v, (list, tuple))).any():
            out[c] = out[c].map(lambda v: "{" + ",".join('"' + str(x).replace('"', '\\"') + '"' for x in v) + "}"
                                if isinstance(v, (list, tuple)) else v)
    buf = io.StringIO()
    out.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cols = ", ".join(out.columns)
    with cur.copy(f"COPY inv.{table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
        cp.write(buf.read())
    return len(out)


def intcol(s: pd.Series) -> pd.Series:
    """'7.0' -> '7' for count columns written as floats; missing stays missing."""
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def ids(s: pd.Series) -> pd.Series:
    return s.fillna("").map(lambda x: [v for v in str(x).split(";") if v])


def load_gastech(cur, case: Path, derived: Path) -> dict:
    n = {}
    cur.execute("""INSERT INTO inv.cases (case_id, name, description, source, is_synthetic, role)
                   VALUES (%s, %s, %s, %s, TRUE, 'investigation')""",
                (GASTECH, "GAStech employees, Abila (Kronos)",
                 "VAST 2021 MC1 + MC2 fictional scenario: emails, vehicle GPS, purchases, documents",
                 "VAST Challenge 2021 MC1/MC2 (validated case + derived layer)"))
    p = pd.read_csv(case / "persons.csv", dtype=str)
    n["persons"] = copy_df(cur, "persons", pd.DataFrame({
        "case_id": GASTECH, "person_id": p.person_id, "display_name": p.display_name, "department": p.department,
        "job_title": p.job_title, "source_entity_id": p.source_entity_id, "identity_basis": p.identity_bridge_type}))
    v = pd.read_csv(case / "vehicles.csv", dtype=str)
    n["vehicles"] = copy_df(cur, "vehicles", pd.DataFrame({
        "case_id": GASTECH, "vehicle_id": v.vehicle_id, "source_car_id": v.car_id, "department": v.department,
        "owner_job_title": v.owner_job_title, "source_dataset": v.source_dataset}))
    a = pd.read_csv(case / "vehicle_assignments.csv", dtype=str)
    n["vehicle_assignments"] = copy_df(cur, "vehicle_assignments", a.assign(case_id=GASTECH)[
        ["case_id", "vehicle_id", "person_id", "relationship", "source_dataset"]])
    loc = pd.read_csv(case / "locations.csv", dtype={"location_id": str, "source_dataset": str})
    n["locations"] = copy_df(cur, "locations", loc.assign(case_id=GASTECH)[
        ["case_id", "location_id", "latitude", "longitude", "source_dataset"]])
    le = pd.read_csv(case / "location_events.csv", dtype=str)
    n["location_events"] = copy_df(cur, "location_events", pd.DataFrame({
        "case_id": GASTECH, "event_id": le.event_id, "vehicle_id": le.vehicle_id,
        "person_id": le.person_id.replace("", np.nan), "location_id": le.location_id,
        "observed_at": le.timestamp, "event_type": le.event_type, "source_dataset": le.source_dataset}))

    ce = pd.read_csv(case / "evidence" / "communication_events.csv", dtype=str)
    rc = ce.groupby("header_sha256").communication_id.transform("size")
    ce = ce[ce.source_person_id.notna() & ce.target_person_id.notna() & (ce.source_person_id != ce.target_person_id)]
    rc = rc.loc[ce.index]
    n["communication_events"] = copy_df(cur, "communication_events", pd.DataFrame({
        "case_id": GASTECH, "communication_id": ce.communication_id, "source_person_id": ce.source_person_id,
        "target_person_id": ce.target_person_id, "communication_type": ce.communication_type,
        "sent_at": ce.timestamp, "time_known": ce.raw_timestamp.str.contains(":"), "timezone": ce.timezone,
        "subject": ce.subject, "sender_address": ce.sender_email, "recipient_address": ce.recipient_email,
        "recipient_count": rc.astype(int), "is_broadcast": rc >= BROADCAST_RECIPIENTS,
        "source_file": ce.source_file, "source_row": ce.source_row, "source_recipient_index": ce.source_recipient_index,
        "header_sha256": ce.header_sha256, "source_dataset": ce.source_dataset}))
    ue = pd.read_csv(case / "evidence" / "unresolved_email_endpoints.csv", dtype=str)
    n["unresolved_communication_endpoints"] = copy_df(cur, "unresolved_communication_endpoints", pd.DataFrame({
        "case_id": GASTECH, "communication_id": ue.communication_id, "source_person_id": ue.source_person_id,
        "target_person_id": ue.target_person_id, "sender_address": ue.sender_email,
        "recipient_address": ue.recipient_email, "sent_at": ue.timestamp, "subject": ue.subject,
        "reason": ue.reason, "source_file": ue.source_file, "source_row": ue.source_row}))

    tx = pd.read_csv(case / "transactions.csv", dtype=str)
    n["transactions"] = copy_df(cur, "transactions", pd.DataFrame({
        "case_id": GASTECH, "transaction_id": tx.transaction_id, "occurred_at": tx.event_time,
        "merchant_location": tx.merchant_location, "amount": tx.amount, "card_last4": tx.card_last4,
        "transaction_type": tx.transaction_type, "source_dataset": tx.source_dataset}))
    ly = pd.read_csv(case / "loyalty_events.csv", dtype=str)
    n["loyalty_events"] = copy_df(cur, "loyalty_events", pd.DataFrame({
        "case_id": GASTECH, "loyalty_event_id": ly.loyalty_event_id, "occurred_on": ly.event_time.str[:10],
        "merchant_location": ly.merchant_location, "amount": ly.amount, "loyalty_number": ly.loyalty_number,
        "source_dataset": ly.source_dataset}))
    man = pd.read_csv(case / "evidence" / "document_manifest.csv", dtype=str)
    n["documents"] = copy_df(cur, "documents", pd.DataFrame({
        "case_id": GASTECH, "document_id": man.document_id, "document_type": man.document_type,
        "source_file": man.source_file, "text_file": man.text_file, "source_sha256": man.source_sha256,
        "text_sha256": man.text_sha256,
        "body": [(case / t).read_text(encoding="utf-8") for t in man.text_file]}))

    # observed email links, aggregated per unordered pair (traceable to communication_events)
    ce["u"] = ce[["source_person_id", "target_person_id"]].min(axis=1)
    ce["v"] = ce[["source_person_id", "target_person_id"]].max(axis=1)
    ce["direct"] = rc < BROADCAST_RECIPIENTS
    pr = ce.groupby(["u", "v"]).agg(events=("communication_id", "size"), direct=("direct", "sum")).reset_index()
    n["relationships"] = copy_df(cur, "relationships", pd.DataFrame({
        "case_id": GASTECH, "person_a": pr.u, "person_b": pr.v, "relationship_type": "EMAILED",
        "weight": np.round(np.log1p(pr.direct + 0.2 * (pr.events - pr.direct)), 4), "evidence_count": pr.events,
        "source_table": "communication_events",
        "source_note": "weight: direct emails count fully, broadcast (>=10 recipients) emails count 0.2"}))

    # ---------------- derived layer
    st = pd.concat([pd.read_csv(derived / "vehicle_stops.csv", dtype=str),
                    pd.read_csv(derived / "uncertain_vehicle_gaps.csv", dtype=str)], ignore_index=True)
    n["vehicle_stops"] = copy_df(cur, "vehicle_stops", pd.DataFrame({
        "case_id": GASTECH, "stop_id": st.stop_id, "vehicle_id": st.vehicle_id,
        "assigned_person_id": st.assigned_person_id, "person_attribution": st.person_attribution,
        "place_id": st.get("place_id"), "latitude": st.lat, "longitude": st.lon,
        "stop_start": st.stop_start, "stop_end": st.stop_end, "duration_min": st.duration_min,
        "last_gps_event_id": st.last_gps_event_id, "next_gps_event_id": st.next_gps_event_id,
        "boundary_distance_m": st.boundary_distance_m, "inference_status": st.inference_status}))
    pl = pd.read_csv(derived / "places.csv", dtype=str)
    n["places"] = copy_df(cur, "places", pd.DataFrame({
        "case_id": GASTECH, "place_id": pl.place_id, "latitude": pl.lat, "longitude": pl.lon, "stops": intcol(pl.stops),
        "vehicles": intcol(pl.vehicles), "place_type": pl.place_type, "home_of_assigned_persons": pl.home_of_assigned_persons}))
    co = pd.read_csv(derived / "colocation_events.csv", dtype=str)
    co["vehicles_present"] = intcol(co.vehicles_present)
    n["colocation_events"] = copy_df(cur, "colocation_events", co.assign(case_id=GASTECH)[
        ["case_id", "colocation_id", "vehicle_id_a", "vehicle_id_b", "person_a", "person_b", "person_attribution",
         "place_id", "place_type", "context", "overlap_start", "overlap_end", "overlap_min", "after_hours",
         "vehicles_present", "group_gathering", "stop_a", "stop_b"]])
    rel = pd.read_csv(derived / "colocation_relationships.csv", dtype=str)
    factor_cols = ["workplace_events", "public_place_events", "both_live_here_events", "private_meetings", "private_days",
                   "after_hours_private", "home_visits", "private_places", "group_gatherings", "lunch_hour_meetings",
                   "chance_expected_days", "chance_p_value", "email_events", "direct_email_events",
                   "meets_privately_never_emails_directly", "vehicle_id_a", "vehicle_id_b"]
    factor_cols = [c for c in factor_cols if c in rel]
    n["inferred_relationships"] = copy_df(cur, "inferred_relationships", pd.DataFrame({
        "case_id": GASTECH, "person_a": rel.person_a, "person_b": rel.person_b,
        "relationship_type": rel.relationship_type, "person_attribution": rel.person_attribution,
        "lead_strength": rel.lead_strength, "lead_level": rel.lead_level,
        "factors": [json.dumps({c: r[c] for c in factor_cols}) for _, r in rel.iterrows()],
        "possible_innocent_explanations": rel.possible_innocent_explanations,
        "supporting_colocation_ids": ids(rel.supporting_colocation_ids), "email_ids": ids(rel.email_ids),
        "relationship_key": rel.get("relationship_key")}))
    lc = pd.read_csv(derived / "loyalty_card_links.csv", dtype=str)
    n["loyalty_card_links"] = copy_df(cur, "loyalty_card_links", pd.DataFrame({
        "case_id": GASTECH, "card_last4": lc.card_last4, "loyalty_number": lc.loyalty_number,
        "matched_purchases": intcol(lc.matched_purchases), "status": lc.status,
        "transaction_ids": ids(lc.transaction_ids), "loyalty_event_ids": ids(lc.loyalty_event_ids)}))
    mn = pd.read_csv(derived / "document_mentions.csv", dtype=str)
    n["document_mentions"] = copy_df(cur, "document_mentions", pd.DataFrame({
        "case_id": GASTECH, "document_id": mn.document_id, "entity_type": mn.entity_type, "entity_id": mn.entity_id,
        "matched_text": mn.matched_text, "start_char": mn.start_char, "end_char": mn.end_char,
        "context": mn.context, "method": mn.method, "review_status": mn.status}))
    return n


def load_caviar(cur, caviar: Path) -> dict:
    cur.execute("""INSERT INTO inv.cases (case_id, name, description, source, is_synthetic, role)
                   VALUES (%s, %s, %s, %s, FALSE, 'centrality_example')""",
                (CAVIAR, "Operation Caviar drug-trafficking network (Montreal)",
                 "Intercepted-communication network, three investigation snapshots",
                 "Morselli (2009) via onadata R package"))
    p = pd.read_csv(caviar / "persons.csv", dtype=str)
    e = pd.read_csv(caviar / "graph_edges.csv", dtype=str)
    return {
        "persons": copy_df(cur, "persons", pd.DataFrame({
            "case_id": CAVIAR, "person_id": p.person_id, "display_name": p.display_name, "department": None,
            "job_title": None, "source_entity_id": p.source_entity_id, "identity_basis": "anonymised_subject"})),
        "relationships": copy_df(cur, "relationships", pd.DataFrame({
            "case_id": CAVIAR, "person_a": e.source_id, "person_b": e.target_id, "relationship_type": e.relationship_type,
            "weight": e.weight, "evidence_count": e.evidence_count, "source_table": "cases/caviar/communication_links.csv",
            "source_note": "phases: " + e.phases.fillna("")})),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--case-dir", type=Path)
    ap.add_argument("--derived-dir", type=Path)
    ap.add_argument("--caviar-dir", type=Path)
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args(argv)
    report = {}
    with psycopg.connect(a.dsn) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                if a.migrate:
                    cur.execute((HERE / "migrations" / "001_case_scoped_schema.sql").read_text())
                if a.case_dir:
                    if a.replace:
                        cur.execute("DELETE FROM inv.cases WHERE case_id = %s", (GASTECH,))
                    report[GASTECH] = load_gastech(cur, a.case_dir, a.derived_dir)
                if a.caviar_dir:
                    if a.replace:
                        cur.execute("DELETE FROM inv.cases WHERE case_id = %s", (CAVIAR,))
                    report[CAVIAR] = load_caviar(cur, a.caviar_dir)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
