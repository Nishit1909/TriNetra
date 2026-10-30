# SIH26189 backend

Case-scoped FastAPI service for the existing GAStech, Caviar and Noordin datasets. PostgreSQL `inv` holds source evidence/results; Neo4j holds versioned case projections. The model team's package stays in `analysis_model/` and is imported without modification.

## Start locally

From the repository root, Python3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
```

Copy the example only if a local `.env` does not already exist. Fill `SUPABASE_DATABASE_URL`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`. `backend/.env` is resolved relative to the backend, independently of the launch directory. Secrets are not in Git.

Apply or check the schema, including the permissions/review migrations, from the repository root:

```powershell
.\.venv\Scripts\python.exe db/setup_database.py --apply
.\.venv\Scripts\python.exe db/setup_database.py --check
Set-Location backend
..\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:8000/docs`. Health checks: `/health` (process), `/health/database` (PostgreSQL + Neo4j readiness). Database loading is separate; see `db/CLOUD_DATABASE_SETUP.md`. Existing populated cases do not need reloading for backend integration.

## Layout and responsibilities

| Module | Responsibility |
|---|---|
| `app/main.py` | Application composition, CORS, request IDs, safe errors and health |
| `app/config.py` | Typed environment settings |
| `app/security.py` | Supabase token verification and case viewer/editor access |
| `app/investigation/common.py` | PostgreSQL connection, case/person guards, safe serialization |
| `app/investigation/cases.py` | Accessible case list and metadata |
| `app/investigation/evidence.py` | Profiles, relationships, emails, vehicle co-location, documents, timeline, leads |
| `app/investigation/analysis.py` | Full-case model adapter, output validation, versioned saved runs and prediction review |
| `app/investigation/graph.py` | Compact graph selection, Neo4j reconciliation and explicit fallback |
| `app/investigation/reviews.py` | Document review and immutable review-history reads |
| `analysis_model/` at repo root | Model teammate's pure function, factor definitions and weights |
| `db/migrations/` |21 core tables plus review/audit and membership extensions |

The old global routers, fuzzy-name uploader and financial-risk/GNN request path are not mounted. Legacy upload returns 410 and points to `/api/case-uploads`. Reference modules remain available for comparison; their optional dependencies are in `requirements-reference.txt`. Uploads go through `/api/case-uploads`: validated, size-limited, one transaction, always a new case. `/health/database` returns 200 `degraded` when only Neo4j is down (graphs fall back to PostgreSQL), 503 when PostgreSQL is down.

## Frontend API contract

All data routes use **text case IDs**: `CASE_VAST_GASTECH`, `CASE_CAVIAR`, `CASE_NOORDIN`. Analysis run IDs are UUIDs. Missing case/person/run returns404; unauthorized membership403; missing/invalid token401; unavailable services503. Input bounds are422. Lists of evidence use `{items,total,limit,offset}`; cases and analysis-run lists are arrays.

| Method/path | Purpose |
|---|---|
| `GET /api/cases` | Accessible cases with name, role, synthetic/source fields |
| `GET /api/cases/{case}/summary` | `{case,counts,latest_analysis,uncertainty}` |
| `GET .../persons?q=&department=&limit=50&offset=0` | Search by name or ID |
| `GET .../persons/{person}` | Profile, vehicle assignments, evidence counts |
| `GET .../persons/{person}/timeline` | Paginated emails and explicitly vehicle-attributed stops |
| `GET .../relationships?kind=observed|inferred|all` | Paginated source relationship rows |
| `GET .../relationships/{a}/{b}` | Actual emails, co-location, joined places/stops, factors, innocent explanations |
| `GET .../leads?level=medium,weak` | Ranked inferred rows with explanations |
| `GET .../places/{place}` | Place and bounded stops |
| `GET .../documents/{document}` | Original text and mention offsets |
| `POST .../analysis` | Explicitly compute/save the chosen mode |
| `GET .../analysis?limit=25` | Run history for that case |
| `GET .../analysis/{run}` | `{run,person_metrics,predicted_links,predicted_links_by_method,score_note}`. Links ordered by method (evidence-based first), then score; each has `rank_in_method`, `basis` (`evidence`/`structural_pattern`), `basis_note` |
| `GET .../analysis/{run}/predicted_links?method=&basis=&person_id=&limit=&offset=` | Paged suggestions for one method or basis |
| `GET .../analysis/compare?run_a=&run_b=` | What changes between two runs (rank movers, hub/community changes, links only in one run) |
| `GET .../persons/{person}/explain?run_id=` (or `mode=`, latest run) | Plain reasons for a person's position: ranks, group, hub flag, strongest ties, suggestions |
| `GET /api/case-uploads/template` | Required/optional columns, rules and an example, for the upload screen |
| `POST /api/case-uploads/validate` | Dry run: multipart `file` (ZIP) or `persons`+`relationships`(+`communications`) CSVs → `{valid,errors,warnings,counts}`; writes nothing |
| `POST /api/case-uploads` | Same files + `name` (+`description`,`role`,`is_synthetic`) → creates a **new** case `CASE_UPLOAD_...`; 422 with the report if invalid (nothing saved). Admin only. No automatic identity merging |
| `GET .../graph` | Bounded, case-scoped display graph; does not run analysis. With `run_id`, mode comes from the run. Predicted edges carry `basis` and get their own share of `edge_limit` |
| `POST .../predicted_links/{run}/{a}/{b}/review` | confirmed/dismissed plus reason; verified actor retained |
| `POST .../document_mentions/{id}/review` | confirmed/rejected plus optional reason |
| `GET .../predicted_links/{run}/{a}/{b}/reviews` | Prediction audit history |
| `GET .../document_mentions/{id}/reviews` | Mention audit history |
| `GET /api/auth/me` | Verified identity/local-mode state |

Review audit rows reject SQL UPDATE/DELETE. A case with review history cannot be blindly replaced through cascading deletion. Preserve/export audit data and design an explicit migration if replacement becomes necessary.

## Focused network graph

```text
GET /api/cases/CASE_VAST_GASTECH/graph?mode=observed_only&limit=25&edge_limit=75
GET /api/cases/CASE_VAST_GASTECH/graph?mode=observed_plus_inferred&focus=P0001&include=observed,inferred,predicted
```

Default25 people/75 edges; maximum100 people/300 edges. Nodes rank by saved PageRank when available, otherwise full-case strength. Focus preserves the selected person and prioritizes neighbors. Response gives `counts.total_nodes/total_edges/shown_nodes/shown_edges`, `truncated`, `case_id`, `run_id`, `mode`, `graph_source`, `warnings`.

Kinds are `observed`, `inferred`, `predicted`: frontend draws solid, dashed, dotted. Node metrics include `pagerank`, `betweenness`, `community_id`, `hub_flag`, `degree`; absent saved metrics remain null. Predictions expose method and score as ranking quantities, not probability. Select a saved `run_id` only for the same case and mode; invalid combinations are rejected.

The compact display never truncates model inputs. The graph restores canonical PostgreSQL ties absent from the smaller Neo4j export, and uses the model's existing strength rules to exclude zero-strength broadcast-only email links. A restored projection reports `neo4j_reconciled`; unavailable Neo4j reports `postgresql_fallback` explicitly. User-facing counts therefore remain consistent when Neo4j availability changes.

Switching cases should clear selection and pending graph/evidence requests. Cache keys must include case and mode; saved result requests also include run ID. The backend does not implement frontend components.

## Model integration

```json
{"mode":"observed_plus_inferred","weights_version":"v1.1"}
```

Send this body to `POST /api/cases/{case}/analysis`. Mode is `observed_only` or `observed_plus_inferred`. Current approved weights file is `analysis_model/weights/v1_1.json`; arbitrary client file paths are not accepted.

The backend passes full-case persons and canonical edges, including direct/broadcast email factors and source IDs, to `run_case_analysis`. It validates returned people, pairs, finite scores, supporting refs and stage statuses before one atomic bulk result write. It stores weights/code/input hashes and counts in `analysis_runs.parameters`.

Function status `ok` maps to DB `completed`; `partial` and `failed` remain so. An exception marks only its exact run failed with safe diagnostic metadata. GET does not compute. POST runs in FastAPI's worker thread and returns the persisted result; for this small demo it is synchronous to the caller, not a durable job queue. A killed process can leave a running row that requires explicit recovery.

Current app methods: weighted centrality, structural communities, `tie_without_recorded_communication`, `network_proximity_ppr` (large-case fallback is declared by the model). Logistic regression remains an offline benchmark. No trained Bitcoin model or GNN is used for person risk. Model teammate can update the pure function under the documented contract; a new weights version needs a backend-approved registry entry and regression check. The v1.1 graph adapter also uses that package's `_edge_strength` helper so displayed strengths match analysis; coordinate any refactor of that helper with the backend instead of removing it independently.

Latest verification:72 backend/model tests passed. `CLOUD_API_VERIFICATION.json` records the live API checks against both cloud stores, six completed runs and bounded graphs. This is local API execution against cloud databases, not a deployed public API. Valid-session login/registration remains deferred until the frontend and Auth users are configured.

## Deployment authentication

Local development is localhost-only with `AUTH_ENABLED=false`. For deployment:

```dotenv
APP_ENV=production
AUTH_ENABLED=true
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_OR_LEGACY_ANON_KEY
ADMIN_USER_IDS=YOUR_AUTH_USER_UUID
CORS_ORIGINS=https://YOUR_FRONTEND_HOST
```

The backend validates access tokens through Supabase Auth's `/auth/v1/user`; it does not trust decoded JWT contents or client-supplied roles. Auth-provider outages return503. Production refuses to start with authentication disabled. External binding through `run.py --host 0.0.0.0` requires authentication. Deploy behind HTTPS. Direct bearer validation is supported; cookie/session login UI belongs to the frontend.

An organization/dashboard invite is different from an application Auth user. Have the frontend sign users in through Supabase Auth and send `Authorization: Bearer <access_token>`. For non-admin users, grant case access in Supabase SQL Editor using their Auth user UUID:

```sql
INSERT INTO inv.case_members(case_id,user_id,access_level)
VALUES ('CASE_VAST_GASTECH','REPLACE_WITH_AUTH_USER_UUID','editor')
ON CONFLICT(case_id,user_id) DO UPDATE SET access_level=EXCLUDED.access_level;
```

`viewer` may read; `editor` may run/review. Admin IDs come only from server configuration. Investigated people stay in `inv.persons`; no authentication credentials are stored there. Live sign-in requires a real Auth user/public key; neither is generated or emailed by these setup scripts.

## Verification

Install `pytest` for tests, and use a **disposable** local database:

```powershell
$env:INV_TEST_DSN='postgresql://USER:PASSWORD@127.0.0.1:5432/DISPOSABLE_TEST_DB'
python -m pytest backend/tests/test_investigation_*.py analysis_model/tests -q
```

Do not set this DSN to the cloud investigation database. Tests create local fixtures and some schema tests deliberately drop/rebuild `inv` inside rolled-back transactions. Full reference tests additionally require `backend/requirements-reference.txt`. OpenAPI can be exported from `app.main:app`; `/docs` is the authoritative interactive contract.

## Model version and scores

Analysis uses `analysis_model/weights/v1_2.json` (learned `hidden_link_ranker` + `tie_without_recorded_communication`). Scores rank pairs **within one method**; they are not probabilities and are not comparable across methods. The UI shows rank and `basis`, never "x% chance".

## Security: three views, access log, alerts, e-mail

Migration `db/migrations/005_security_audit.sql` (applied by `db/setup_database.py --apply`). Demo accounts: `python db/seed_demo_security.py --dsn ...` (all `is_demo`; remove with `--remove`).

| Role | Can |
|---|---|
| `viewer` | Read assigned cases only. Any change → 403 |
| `investigator` | Read assigned cases; run analysis, review leads, upload where `case_members.access_level = editor` |
| `admin` | All cases + admin portal |

`GET /api/auth/me` returns `view` (`viewer` / `investigator` / `admin`), `can_edit` and the cases the user can open; the UI picks its screens from this. Locally (`AUTH_ENABLED=false`, localhost only) send `X-Demo-User: <user_id>` to act as a demo user; with auth on, the Supabase user id is looked up in `inv.app_users`.

**Access log:** every API request is recorded in `inv.access_log` (append-only: who, role, action, case, person, status, allowed, IP, time).

**Alert rules** (raise `inv.security_alerts`, one per user/case/window, no spam):

| Rule | Severity | When |
|---|---|---|
| `denied_access` | high | 401/403 on a case or action |
| `conflict_of_interest` | high | the user's name or e-mail matches a subject or communication address in a case they open |
| `bulk_viewing` | high | ≥ N distinct person profiles in M minutes (default 40 in 10) |
| `after_hours` | medium | case access outside working hours / weekends (default 08–20 Asia/Kolkata) |
| `sensitive_action` | low | upload, dismissed lead, export |

Alerts are flags for an administrator to review, not findings about a person.

**Admin portal endpoints** (`/api/admin`, admin only): `GET users`, `POST users`, `POST users/{id}` (role/active), `POST case-members`, `POST case-members/remove`, `GET access-log` (filters user/case/action/allowed/since/until), `GET access-summary?hours=24`, `GET alerts?status=&severity=&rule=`, `POST alerts/{id}/review`, `GET conflicts`, `GET settings`, `POST settings/alert-rules`, `POST settings/smtp`, `POST settings/smtp/test`.

**E-mail:** configure SMTP in the portal (host, port, username, from, recipients, TLS, minimum severity). The password is only read from the `SMTP_PASSWORD` environment variable and is never stored or returned. Each alert records `email_status` (`sent` / `failed` / `disabled` / `below_threshold`).
