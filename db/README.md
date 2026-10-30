# Case-scoped database (`inv` schema)

A new Postgres schema `inv` that holds every case separately. It does **not** touch the existing `public.*` tables the current backend uses, so nothing breaks until the backend is switched over.

## Load it

```bash
unzip datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip -d /tmp/case
python db/load_case.py --dsn "$DATABASE_URL" --case-dir /tmp/case \
    --derived-dir derived --caviar-dir cases/caviar --migrate     # first time (creates schema inv)
python db/load_case.py ... --replace                              # reload a case (deletes only that case's rows)
```

Use a disposable or test database first. Loading takes about 20 s (685k GPS rows).

## Tables

| Group | Tables |
|---|---|
| Cases | `cases` |
| Observed records | `persons`, `vehicles`, `vehicle_assignments`, `locations`, `location_events` (GPS, `person_id` always NULL), `communication_events` (emails with timestamps, subject, source row, broadcast flag), `unresolved_communication_endpoints` (quarantined, never analysed), `transactions`, `loyalty_events` (date only), `documents` (full text), `relationships` (observed links: GAStech email pairs, Caviar intercepts) |
| Inferred records | `vehicle_stops` (incl. uncertain GPS gaps, flagged), `places`, `colocation_events`, `inferred_relationships` (lead strength, factors, innocent explanations, supporting ids), `loyalty_card_links`, `document_mentions` (all `proposed_needs_review`) |
| Analysis | `analysis_runs` (mode `observed_only` / `observed_plus_inferred`, weights version), `person_metrics`, `predicted_links` (with review status) |
| View | `case_graph_edges`: observed + inferred edges; **always filter by `case_id`** |

## How isolation is enforced
- Every primary key starts with `case_id`, and every foreign key includes it, so a row can only point at rows of its own case. The database rejects anything else.
- Analysis results reference `(case_id, analysis_run_id)`, so a run's results can't point at another case's people.
- Deleting a case removes only that case's rows (cascade).
- `tests/test_db_case_isolation.py` checks all of this with two cases sharing the same IDs: `INV_TEST_DSN=postgresql://... pytest tests/test_db_case_isolation.py` (7 tests).

## Loaded counts (validated case + derived layer from PR #2)

| Case | Rows |
|---|---|
| CASE_VAST_GASTECH | 54 persons, 40 vehicles, 35 assignments, 33,708 locations, 685,169 GPS events, 8,097 email events, 111 quarantined endpoints, 1,490 purchases, 1,392 loyalty events, 884 documents, 1,262 email pairs, 3,068 stops (incl. 93 uncertain gaps), 73 places, 13,357 co-location events, 561 inferred pair relationships, 55 loyalty links, 3,002 mentions |
| CASE_CAVIAR | 62 persons, 88 intercept relationships |

## Still to do in the backend (not in this change)
- Point queries at `inv.*` and filter every query and endpoint by `case_id`.
- Write analysis results into `inv.analysis_runs` / `person_metrics` / `predicted_links`.
- The old importer's unsafe name auto-merge must stay off for new data.
