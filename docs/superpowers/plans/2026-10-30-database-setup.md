# Shared database setup implementation plan

**Goal:** Make the agreed inv schema and Neo4j person graph reproducibly installable without deleting existing tables or exposing credentials.

**Architecture:** Retain the shared 21-table SQL migration and current three-case loader. Add an environment initializer and repeatable schema setup/check command. Preserve populated schemas; reject incomplete layouts. Keep PostgreSQL source evidence and Neo4j versioned case projections separate. Cloud execution requires local credentials, which are not currently configured.

**Tech stack:** Python3.12, psycopg, python-dotenv, Neo4j Python driver, pytest.

- [x] Add regression tests for safe env initialization and fresh/existing/partial schema setup.
- [x] Implement db/setup_database.py and document the three-case load command.
- [x] Verify schema setup, all three case loads, isolation and Neo4j dry-run against disposable local PostgreSQL. Final relevant suite:33 passed.
- [x] Package SQL, loaders, helpers, env template and instructions without credentials. Artifact: E:/SIH/SIH26189_DATABASE_READY.zip.
- [x] Applied to connected Supabase and Neo4j after local credentials were configured. Verified all three PostgreSQL cases and active Neo4j snapshots; evidence: db/CLOUD_VERIFICATION.json. Shared backend integration remains incomplete.
