# Load Supabase and Neo4j for the SIH demo

Use GPT-6.1 Sol High for backend/schema integration, then Medium for scoped fixes. Original backend defects remain part of the work: case mixing, fuzzy identity merges, dropped provenance, failed imports, incorrect edge weighting and misleading model results. The database load alone does not repair the old API.

These instructions use the shared `inv` schema. Do not run the alternative local `casework` migration as part of this setup. Cloud setup completed30October2026 after local credentials were configured:21 Supabase tables, three loaded cases, and three verified Neo4j projections. See `db/CLOUD_VERIFICATION.json`. The shared backend integration remains unfinished; reloading data is not needed to continue that work.

## 1. Prepare files

This machine's reviewed checkout is `E:\SIH\VVCE_P2_workspace_review`. Your friend's checkout may be `D:\Hackathon\vvce_p2`; substitute the actual repository root. Use a clean workspace checkout, with this setup kit's `db` and `tests` folders copied into it. The new helper scripts are local files, not yet pushed to GitHub.

```powershell
Set-Location 'E:\SIH\VVCE_P2_workspace_review'
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-database.txt
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
notepad backend/.env
```

If `py` is unavailable, use your installed Python 3.12 executable to create the environment. In `.env`, fill these values using your own dashboard credentials:

```dotenv
SUPABASE_DATABASE_URL=postgresql://COPY-THE-CORRECT-CONNECTION-STRING?sslmode=require
NEO4J_URI=neo4j+s://YOUR-INSTANCE.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=YOUR-NEO4J-PASSWORD
NEO4J_DATABASE=neo4j
```

Supabase Dashboard → Connect → copy the Direct or Session pooler connection string. Direct is generally IPv6; choose Session pooler if your laptop network needs IPv4. Both use port5432; avoid transaction pooler port6543 for this loader's COPY workflow. The username and hostname differ between connection modes: copy the complete string instead of guessing. The password is the database password, not the anon/publishable or service-role API key. URL-encode password characters when placing them inside a URI. Keep `.env` out of Git.

Neo4j Aura → choose your instance → Connect → copy the URI and username; use the password saved when creating the instance (or reset it). Use a running instance. PostgreSQL and Neo4j are separate services; neither automatically populates the other.

## 2. Create/check both database schemas, then load all three cases

The latest workspace includes Noordin, its loader and the model function. Use these latest files instead of the older handoff's loader. Initialize the local environment file without overwriting one that already exists:

```powershell
.\.venv\Scripts\python.exe db/setup_database.py --init-env
```

Fill in `backend/.env`, then create the21-table PostgreSQL schema plus the Neo4j constraints:

```powershell
.\.venv\Scripts\python.exe db/setup_database.py --apply
.\.venv\Scripts\python.exe db/setup_database.py --check
```

`--apply` preserves a complete existing `inv` schema and its data. An incomplete/incompatible schema is rejected; it does not drop it. `--check` reads state without creating anything. The checks cover required tables/columns, the graph view, connectivity and expected Neo4j constraint names; they are not a full drift comparison of every historical constraint/type. If Neo4j setup fails after PostgreSQL succeeds, fix the credentials/connectivity and rerun; PostgreSQL creation is already committed.

Extract the already validated source archive, then load GAStech, Caviar and Noordin. The extraction below is for the known repository archive, not arbitrary uploaded ZIPs. Skip extraction when `case/persons.csv` is already present.

```powershell
Expand-Archive -LiteralPath datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip -DestinationPath case
.\.venv\Scripts\python.exe db/load_configured.py --case-dir case --derived-dir derived --caviar-dir cases/caviar --noordin-dir cases/noordin
```

Do not pass `--migrate` to the loader after the setup command created the schema. Loading existing case IDs will fail rather than silently duplicate them. The existing loader has `--replace`, but that deletes and reloads the selected cases, including their saved runs through cascading foreign keys. Do not use `--replace` merely to retry a completed load. For a case already loaded, leave it alone and load only the missing cases using their individual directory flags.

In Supabase SQL Editor, verify:

```sql
SELECT case_id,name FROM inv.cases ORDER BY case_id;
SELECT case_id,count(*) FROM inv.persons GROUP BY case_id;
SELECT case_id,count(*) FROM inv.communication_events GROUP BY case_id;
SELECT case_id,count(*) FROM inv.location_events GROUP BY case_id;
SELECT case_id,count(*) FROM inv.relationships GROUP BY case_id;
SELECT case_id,count(*) FROM inv.inferred_relationships GROUP BY case_id;
```

Expected current dataset: GAStech54 persons,8097 resolved email events,685169 vehicleGPS records,1262 observed email pairs,561 inferred relationship rows (not all are actionable leads). Caviar62 persons,88 relationships. Noordin79 persons,1014 typed relationships. Supabase's Table Editor may need schema `inv` selected. FastAPI connects through SQL; exposing `inv` through Supabase's browser Data API is not needed for this design.

Noordin's COMMUNICATIONS layer remains stored and identified as a benchmark label layer. When running its offline hidden-communication benchmark, remove that layer from every feature graph. Its normal case display may show recorded communications; a displayed case is not the held-out benchmark.

## 3. Project the person graph to Neo4j

Validate the PostgreSQL export first; this reads PostgreSQL but does not connect to Neo4j:

```powershell
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_VAST_GASTECH --dry-run
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_CAVIAR --dry-run
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_NOORDIN --dry-run
```

Then publish each case's graph:

```powershell
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_VAST_GASTECH
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_CAVIAR
.\.venv\Scripts\python.exe db/sync_neo4j.py --case-id CASE_NOORDIN
```

The projection contains persons and observed relations plus inferred leads whose level is `medium` or `weak` and strength is positive. It retains provenance, source table and factor attributes; it does not claim all561 inferred rows are leads. Single-day and not-a-lead categories remain in PostgreSQL. This is an explicit display filter, not a newly validated model threshold. Predictions must be served separately from saved analysis rather than converted into observed facts.

GPS, stops, purchases and document text stay in PostgreSQL. Do not copy685k GPS records into Neo4j merely to show the person network. Use the API's evidence endpoints to retrieve detail when an edge is selected.

Each sync creates a fresh snapshot and atomically changes its case's active pointer when all graph writes succeed. It preserves previous snapshots; it does not delete an existing database. Concurrent source reads use a consistent PostgreSQL snapshot. This is an explicit sync, not live continuous replication. Re-run after changing the source case. Old snapshots consume space; a version-scoped retention procedure is a follow-up if repeated imports become frequent.

In Neo4j Query/Browser:

```cypher
MATCH (c:InvCase)
RETURN c.case_id,c.active_snapshot_id,c.person_count,c.edge_count;
```

```cypher
MATCH (c:InvCase {case_id:'CASE_VAST_GASTECH'})
MATCH (a:InvPerson {case_id:c.case_id,snapshot_id:c.active_snapshot_id})
      -[r:INV_LINK]->
      (b:InvPerson {case_id:c.case_id,snapshot_id:c.active_snapshot_id})
RETURN a,r,b LIMIT 100;
```

Backend graph queries must use the `InvCase` active snapshot and bind both endpoints' case/snapshot. The current old global `MATCH(node)` reader is not compatible with a versioned graph; switching the backend reader remains required before the UI uses this projection. Node property names include `person_id`, `label`, `department`; edges include `relationship_type`, `weight`, `kind`, `is_inferred`, `evidence_table`, `attributes_json`. This helper does not deploy or repair the API by itself.

## 4. Verification limits and references

Helper regression tests: `python -m pytest tests/test_neo4j_sync.py -q` passed7/7. The actual current GAStech + Caviar loader completed against disposable local PostgreSQL with the expected source counts. The Neo4j export dry-run validated54 GAStech people/1262 observed edges/42 inferred edges after the stated filter, and62 Caviar people/88 observed edges. Real cloud credentials were not supplied; live Aura execution and Supabase throughput are not verified. Take completion from returned status/counts, not merely from the absence of a visible error.

- Supabase connections: https://supabase.com/docs/guides/database/connecting-to-postgres
- Neo4j Python driver: https://neo4j.com/docs/python-manual/current/
