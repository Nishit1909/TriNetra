# Shared investigation backend implementation plan

**Goal:** Finish the shared backend around inv and the model team's existing function; expose a compact three-case network UI and evidence flow.

**Approved scope:** User requested all backend work, preservation of original bug fixes, continued PostgreSQL+Neo4j, and a small graph with switching between GAStech/Caviar/Noordin. Existing BACKEND_TASKS.md and analysis_model/FACTORS.md define the endpoints/model. No model training or unrelated dataset work.

**Architecture:** app/investigation contains case-scoped reads, analysis persistence and graph selection. PostgreSQL is source evidence; Neo4j supplies its versioned case graph with explicit availability/fallback status. Analyses always use all person rows. New graph defaults to25 nodes/75 edges and supports focus/search/limits. Observed/inferred/predicted stay separate. Supabase verifies user JWTs; case membership gates deployed API reads/writes. Local development binds localhost and can run without auth. Old global readers, unsafe upload and unrelated risk models are removed from the request path.

**Shared module contract:** app.investigation.common exports connect() (psycopg dict-row context), require_case(case_id,conn=None) -> dict orHTTP404, require_person(case_id,person_id,conn=None) -> dict orHTTP404, json_safe(value) -> JSON-safe nested value (NaN->None). Each domain owns its APIRouter. Parent mounts per-case routers with access dependency. Principal from app.security.get_principal exposes user_id/is_admin/local; case access handled centrally by parent.

- [x] Evidence API: persons, pair evidence, leads, places, documents, timelines and summary. Strict SQL case joins, pagination and uncertainty.
- [x] Analysis API: model adapter, registry of approved weights, running/completed/partial/failed persistence, run history/results/review audit, full-case inputs.
- [x] Graph API: compact deterministic selection, focus expansion, kinds, scores and run metadata. No training or analysis truncation.
- [x] Parent: common DB helpers, case listing, auth verification and membership migration, main routing/CORS/config, safe errors, startup/deployment commands.
- [x] User changed scope to backend only. All frontend work reverted; git diff frontend is empty. No browser/frontend claim.
- [x]72 backend/model tests passed. Live API verified on all three loaded cloud cases, six persisted completed runs, bounded graph and evidence flow; source cases not reimported/deleted.
- [x] Independent review corrected Neo4j projection inconsistency and missing dependency. README, OpenAPI and cloud API verification artifact produced. Valid-session login and public deployment deferred by user; auth code and local permission tests retained.
