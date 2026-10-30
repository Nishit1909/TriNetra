"""Reference adapter: build the function inputs for ONE case from schema `inv`, run, print a summary.

The backend owns the real adapter (saving runs to inv.analysis_runs / person_metrics / predicted_links).
This script shows the exact queries and shapes the function expects.

Usage: python -m analysis_model.example_adapter --dsn postgresql://... --case CASE_VAST_GASTECH --mode observed_plus_inferred
"""
import argparse
import json
from pathlib import Path

import pandas as pd
import psycopg

from .run_case_analysis import load_weights, run_case_analysis

WEIGHTS = Path(__file__).resolve().parent / "weights" / "v1.json"


def load_inputs(conn, case_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    persons = pd.read_sql("SELECT person_id, display_name, department FROM inv.persons WHERE case_id = %(c)s",
                          conn, params={"c": case_id})
    observed = pd.read_sql("""
        WITH mail AS (
            SELECT LEAST(source_person_id, target_person_id) AS a, GREATEST(source_person_id, target_person_id) AS b,
                   count(*) AS email_events, count(*) FILTER (WHERE NOT is_broadcast) AS direct_email_events
            FROM inv.communication_events WHERE case_id = %(c)s GROUP BY 1, 2)
        SELECT r.person_a, r.person_b, r.relationship_type, FALSE AS is_inferred, r.weight,
               CASE WHEN m.a IS NULL THEN NULL
                    ELSE jsonb_build_object('email_events', m.email_events, 'direct_email_events', m.direct_email_events) END AS factors,
               NULL::text[] AS evidence_refs
        FROM inv.relationships r
        LEFT JOIN mail m ON r.relationship_type = 'EMAILED' AND m.a = r.person_a AND m.b = r.person_b
        WHERE r.case_id = %(c)s""", conn, params={"c": case_id})
    inferred = pd.read_sql("""
        SELECT person_a, person_b, relationship_type, TRUE AS is_inferred, lead_strength / 100.0 AS weight,
               factors || jsonb_build_object('supporting_colocation_ids', supporting_colocation_ids) AS factors,
               supporting_colocation_ids AS evidence_refs
        FROM inv.inferred_relationships
        WHERE case_id = %(c)s AND relationship_type <> 'WORKPLACE_ONLY'""", conn, params={"c": case_id})
    return persons, pd.concat([observed, inferred], ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--mode", default="observed_plus_inferred")
    ap.add_argument("--weights", default=str(WEIGHTS))
    ap.add_argument("--exclude-types", default="", help="comma list of relationship types to leave out (e.g. benchmark label layers)")
    a = ap.parse_args()
    with psycopg.connect(a.dsn) as conn:
        persons, edges = load_inputs(conn, a.case)
    if a.exclude_types:
        edges = edges[~edges.relationship_type.isin(a.exclude_types.split(","))]
    res = run_case_analysis(persons, edges, a.mode, load_weights(a.weights))
    names = dict(zip(persons.person_id, persons.display_name))
    pm = res["person_metrics"].assign(name=lambda d: d.person_id.map(names))
    print(json.dumps({"status": res["status"], "stages": res["stages"], "warnings": res["warnings"]}, indent=1, default=str))
    print("\nTop 8 by PageRank\n", pm.sort_values("pagerank", ascending=False).head(8)[["person_id", "name", "pagerank", "betweenness", "degree", "community_id", "hub_flag"]].to_string(index=False))
    print("\nTop 8 by betweenness\n", pm.sort_values("betweenness", ascending=False).head(8)[["person_id", "name", "betweenness", "community_id"]].to_string(index=False))
    print("\nCommunities:", pm.community_id.value_counts().to_dict())
    pl = res["predicted_links"]
    for m, g in pl.groupby("method"):
        print(f"\n{m}: {len(g)} suggestions; top 5")
        for r in g.head(5).itertuples():
            print(f"  {names.get(r.person_a, r.person_a)} - {names.get(r.person_b, r.person_b)}  score={r.score:.3f}  {r.factor_breakdown}  refs={len(r.evidence_refs)}")


if __name__ == "__main__":
    main()
