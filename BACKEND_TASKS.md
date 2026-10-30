# Backend tasks: SIH26189 investigation demo

For the backend owner. The data and the case-scoped database are ready; the backend now needs to serve them. The analytics/model side is being built separately and will plug in through the contract in section 6.

**Goal for the demo, one working flow:** Case → person → relationship → supporting records → clear uncertainty.

Priority: P0 = needed for the demo, P1 = strongly wanted, P2 = if time remains.

---

## 0. What's in this package

| Path | What |
|---|---|
| `backend/` | Current backend (`backend_PoC`), `requirements.txt`, `.env.example`. Copy your real `.env` in; it's git-ignored |
| `db/migrations/001_case_scoped_schema.sql` | New Postgres schema `inv`; every key and foreign key carries `case_id`. Doesn't touch `public.*` |
| `db/load_case.py` | Loads GAStech + derived layer + Caviar into `inv` (~20 s). See `db/README.md` |
| `datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip` | Final validated GAStech case |
| `derived/` | Derived evidence (stops, places, co-location, leads, mentions); corrected version from PR #2 |
| `cases/caviar/`, `cases/noordin/` | Separate example and benchmark cases |
| `tests/test_db_case_isolation.py` | 7 isolation tests (`INV_TEST_DSN=... pytest`) |
| `docs/` | Dataset handoff, derived-evidence method, input records, references |

**Load into Supabase** (from a laptop; use the *direct* or *session* connection string, not the transaction pooler on port 6543):
```bash
pip install -r backend/requirements.txt
python -c "import zipfile; zipfile.ZipFile('datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip').extractall('case')"
python db/load_case.py --dsn "$SUPABASE_DATABASE_URL" --case-dir case --derived-dir derived --caviar-dir cases/caviar --migrate
```
Try a test Supabase project first if possible. Expected counts are in `db/README.md`.

---

## 1. Case scoping everywhere (P0)

The old code reads global `public.*` tables. Switch to `inv.*` and scope **everything** by case:

- [ ] Every endpoint that returns case data takes `case_id` (path parameter: `/api/cases/{case_id}/...`)
- [ ] Every SQL query filters `WHERE case_id = %s`, including joins (join on `case_id` + id)
- [ ] Every graph built for analytics uses one case's rows only
- [ ] Saved results, caches and exports are scoped to their case
- [ ] Unknown `case_id` → 404; IDs from another case → 404, never data
- [ ] Test: two cases with the same `person_id` (e.g. `P0001`) never see each other through the API

## 2. Read endpoints for the investigation flow (P0)

All under `/api/cases/{case_id}`. Return source references so the UI can show proof.

| Endpoint | Returns | Source tables |
|---|---|---|
| `GET /api/cases` | Case list with `role` (investigation / benchmark / centrality_example), `is_synthetic` | `inv.cases` |
| `GET /persons` | People (filters: department, search by name) | `inv.persons` |
| `GET /persons/{person_id}` | Profile: attributes, assigned vehicle, counts of emails / meetings / documents mentioning them | persons, vehicle_assignments, communication_events, inferred_relationships, document_mentions |
| `GET /relationships?kind=observed\|inferred\|all` | Edges with `is_inferred`, type, weight, lead strength | `inv.case_graph_edges` (view) |
| `GET /relationships/{a}/{b}` | **Evidence for one pair**: emails (time, subject, source row), co-location events (place, times, the two stops), factor values, chance check, **possible innocent explanations**, `person_attribution` | communication_events, colocation_events, vehicle_stops, places, inferred_relationships |
| `GET /leads?level=medium,weak` | Ranked leads with breakdown and explanations | `inv.inferred_relationships` |
| `GET /places/{place_id}` | Place type, coordinates, stops there | places, vehicle_stops |
| `GET /documents/{document_id}` | Text + mentions (with character offsets for highlighting) | documents, document_mentions |
| `GET /persons/{person_id}/timeline` | Time-ordered emails + vehicle stops (vehicle-level, labelled) | communication_events, vehicle_stops |

Rules the responses must keep:
- [ ] GPS and stops are **vehicle** evidence. Any person link says `assigned_driver_assumed`
- [ ] Inferred relationships are always flagged `is_inferred: true`, never mixed silently with observed ones
- [ ] Unknown stays unknown: card ownership is unresolved (no person on purchases); quarantined email endpoints are never shown as resolved
- [ ] GAStech has **email headers, not phone records**. Don't label anything as calls/CDR

## 3. Analysis runs (P0)

- [ ] `POST /api/cases/{case_id}/analysis` body `{mode: "observed_only" | "observed_plus_inferred", weights_version: "v1"}`. Creates `inv.analysis_runs` (status `running`), calls the analytics function (section 6), writes `inv.person_metrics` and `inv.predicted_links`, then sets status `completed` / `partial` / `failed` **truthfully** with errors
- [ ] `GET /api/cases/{case_id}/analysis` lists runs; `GET .../analysis/{run_id}` returns its metrics + predicted links
- [ ] Never report a failed stage as success; empty output from a failed stage must not look like "no findings"
- [ ] Run the work off the request thread (background task or worker thread). The old upload route blocked the async loop

## 4. Graph endpoint for the UI (P0)

`GET /api/cases/{case_id}/graph?run_id=...&include=observed,inferred,predicted`
- Nodes: person, label, department, `pagerank`, `betweenness`, `community_id`, `hub_flag` (from the run)
- Edges: `source`, `target`, `kind` (`observed` | `inferred` | `predicted`), `type`, `weight`, `lead_strength`
- The UI draws solid / dashed / dotted lines, thickness = weight, node size = centrality, colour = community

## 5. Review actions (P1)

- [ ] `POST .../predicted_links/{run_id}/{a}/{b}/review` `{status: confirmed|dismissed, reason}` → stores reviewer, time and reason (`inv.predicted_links` review columns)
- [ ] `POST .../document_mentions/{mention_id}/review` `{status: confirmed|rejected}`
- [ ] Every review is kept (audit trail); confirmed/dismissed leads will later become training labels

## 6. Contract with the analytics/model side (P0, agree on this first)

The model work delivers one Python function; the backend only calls it and stores the output:

```python
def run_case_analysis(persons: pd.DataFrame,        # case_id, person_id, department, ...
                      edges: pd.DataFrame,          # person_a, person_b, relationship_type, is_inferred, weight, factors (dict)
                      mode: str,                    # "observed_only" | "observed_plus_inferred"
                      weights: dict) -> dict:
    return {
      "person_metrics":  pd.DataFrame,   # person_id, degree, weighted_degree, betweenness, pagerank, community_id, hub_flag
      "predicted_links": pd.DataFrame,   # person_a, person_b, method, score, factor_breakdown (dict), evidence_refs (list)
      "warnings": [str],
    }
```
- Backend builds `edges` from `inv.case_graph_edges` (+ `inferred_relationships.factors` for inferred rows), filtering out inferred rows when `mode = observed_only`.
- `weights` comes from `analysis_model/weights/v1_2.json`. The version is stored in `analysis_runs.weights_version`.
- **Delivered:** `analysis_model/run_case_analysis.py` also returns `status` (`ok`/`partial`/`failed`) and per-stage `stages` with errors; store both. Method names: `tie_without_recorded_communication`, `hidden_link_ranker` (fallbacks: `network_proximity_ppr`, `network_proximity_adamic_adar`). See `analysis_model/FACTORS.md`.
- **UI rule:** `hidden_link_ranker` scores rank pairs; they are **not probabilities**. Never display "x% chance"; show rank + signals. Surface any `warnings` entry about a ranker fallback.
- Runtime needs only numpy, pandas, networkx (no scikit-learn/joblib for scoring).
- For email pairs, pass `{"email_events", "direct_email_events"}` in `factors` (see `analysis_model/example_adapter.py`) so broadcast-only pairs carry no strength.
- **Retire the old analytics** (`backend/app/analytics/`, including the Bitcoin-trained risk score and the GNN) from the request path, or mark it reference-only, so only one implementation runs.

## 7. Ingestion fixes (P1; only if new uploads are part of the demo)

- [ ] **Disable unsafe fuzzy name auto-merges.** Ties and contradictory phones go to review; new similar names never collapse automatically
- [ ] Persist `evidence/communication_events.csv` (timestamps, subject, source row), not only the 5-column communications file
- [ ] GPS rows with `vehicle_id` and no person → vehicle visits; never refill person IDs
- [ ] Carry `case_id` and the exact ingestion run ID through every stage; record stage-specific status
- [ ] Validate values, keys, references, timestamps and coordinate ranges before writing; cap uncompressed ZIP size

For the demo, preloading via `db/load_case.py` is enough. Don't do a first full cloud import live in front of judges.

## 8. Clean-ups (P1/P2)

- [ ] **Risk score:** remove the Elliptic (Bitcoin-trained) XGBoost score from the main UI, or label it "experimental transaction benchmark, not person risk"
- [ ] **Names:** show `display_name`, never "Network Entity 0XXX"
- [ ] **Neo4j:** optional. Everything needed is in Postgres; keep Neo4j only if you use it for path queries
- [ ] **Security:** keep the demo on localhost or behind a gate; there's no auth on routes yet. Keep secrets in `.env` (git-ignored); the frontend never talks to the database directly
- [ ] One documented start command for backend + frontend; `.env.example` kept up to date

## 9. Acceptance checks before the demo

| Check | Pass when |
|---|---|
| Case isolation | Two cases with the same IDs; neither visible via the other's endpoints |
| Evidence | Clicking any inferred edge returns its co-location events and stops; any email edge returns its email rows |
| Uncertainty | Responses show `assigned_driver_assumed`, `is_inferred`, innocent explanations; purchases show no owner |
| Analysis status | Forcing one stage to fail shows `partial`/`failed` in the API and UI |
| Runs | `observed_only` and `observed_plus_inferred` runs both stored and retrievable |
| Clean start | Fresh checkout + `.env` + documented commands start backend + frontend and load the case |

Questions on data or the derived layer: see `docs/DERIVED_EVIDENCE.md` and `db/README.md`.
