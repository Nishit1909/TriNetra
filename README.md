# TriNetra · See the hidden network

*Criminal network intelligence platform for SIH26189.*

Case-scoped network analysis for investigators: who matters in a network, how people connect, which links may be hidden, and the records behind every lead. Built for Smart India Hackathon problem SIH26189.

```
React + Vite frontend  ──/api──▶  FastAPI backend  ──▶  Supabase PostgreSQL (schema inv)
   (frontend/)                     (backend/)       ──▶  Neo4j Aura (optional graph store)
                                       │
                                       └──▶  analysis_model/  (network analysis + learned link ranker)
```

**Branch to use: `final`.** It contains everything below, tested together.

---

## 1. What you need

| Tool | Version | Check |
|---|---|---|
| Python | 3.10 – 3.13 | `python --version` |
| Node.js | 20.19+ or 22.12+ | `node --version` |
| Git | any | `git --version` |

You also need the **Supabase** project (database) and the **Neo4j Aura** instance details. Ask the team for the passwords; they are never committed.

---

## 2. Get the code

```powershell
git clone https://github.com/Nishit1909/VVCE_P2.git
cd VVCE_P2
git checkout final
```

Already cloned? `git fetch origin` then `git checkout final` and `git pull`.

---

## 3. Backend

```powershell
cd backend
python -m pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

Open `backend/.env` and fill in:

```ini
SUPABASE_DATABASE_URL=postgresql://postgres.vegimprsgllfdpedmofu:<DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
NEO4J_URI=neo4j+s://6f6df57f.databases.neo4j.io
NEO4J_USERNAME=6f6df57f
NEO4J_PASSWORD=<NEO4J_PASSWORD>
NEO4J_DATABASE=6f6df57f
APP_ENV=development
AUTH_ENABLED=false
LOGIN_REQUIRED=true
```

- Use the **Session pooler** address above (Supabase → Connect → Session pooler). The direct `db.<project>.supabase.co` address needs IPv6, which most networks don't have. Don't use port 6543.
- `LOGIN_REQUIRED=true` turns on the sign-in page. Set it to `false` only for development (then a demo-user switcher appears instead).

Start it:

```powershell
python run.py
```

Check **http://127.0.0.1:8000/health/database** → you want `"postgresql": "ok"` and `"neo4j": "ok"`.
API docs: **http://127.0.0.1:8000/docs**.

> Always use `python -m pip`, not bare `pip`. If you have several Pythons installed, plain `pip` may install into a different one than `python run.py` uses (symptom: `ModuleNotFoundError: No module named 'neo4j'`).

---

## 4. Frontend

In a **second** terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. The dev server proxies `/api` and `/health` to the backend on port 8000, so no CORS setup is needed.

---

## 5. Sign in

| Role | Email | Password | Can |
|---|---|---|---|
| Admin | `demo.admin@trinetra.demo` | `Admin@Trace2026` | Everything, plus the Admin Portal |
| Investigator | `demo.investigator1@trinetra.demo` | `Investigator@2026` | Run analysis, review leads, upload cases (GAStech, Noordin) |
| Viewer | `demo.viewer@trinetra.demo` | `Viewer@Trace2026` | Read-only (GAStech, Caviar) |

Also seeded: `demo.investigator2@…` / `Arjun@Trace2026`, and `demo.coi@…` / `Kanon@Trace2026` (Kanon Herrero shares a name with a GAStech employee, to demonstrate the conflict-of-interest check).

The login page has one-click buttons for the three main accounts.

---

## 6. Demo walkthrough (about 5 minutes)

1. **Sign in as Admin.** Case: *GAStech*. Click **Run analysis** once if the graph says no analysis has been run.
2. **Overview:** counts, latest run and its stage statuses, top figures, top evidence leads, and the uncertainty card (vehicle GPS → person is *assumed*).
3. **Network Graph:**
   - 3D, 2D and List views
   - **red, blinking** = key figures; **amber** = secondary figures; **cyan ring** = connectors (bridge groups)
   - solid = observed, violet dashed = inferred (GPS co-location), dotted = predicted (red = evidence-based, cyan = structural pattern)
   - click a person → inspector → *Open evidence profile* / *Focus on this neighbourhood*; click a link → pair evidence
4. **Leads & Predictions:** *Meets but never communicates* leads (the top GAStech lead is CFO Ingrid Barranco ↔ security officer Hennie Osvaldo). Open one: evidence, innocent explanations, Confirm/Dismiss with a reason (audit trail).
5. **Compare Runs:** what changes when inferred evidence is added.
6. **Upload Case** (investigator or admin): upload `samples/upload/monsoon_ledger_case.zip` or the three CSVs in `samples/upload/monsoon_ledger_csv/` → Validate → Create → *Run Analysis & Open Network Graph*. Try `monsoon_ledger_BROKEN.zip` to see validation reject it with 5 errors.
7. **Admin Portal:**
   - alerts (denied access, conflict of interest, after hours, failed logins), access log, users and case access
   - signed-in sessions (end any session), password resets, conflict check, alert rules, SMTP settings and test e-mail
8. **Sign out → sign in as Viewer:** no Upload or Admin, no Run analysis, and review buttons are disabled.

**Honesty rules the UI keeps:** scores are rankings, never probabilities; "key figure" means network position, not guilt; inferred links are always marked; innocent explanations are shown with every lead.

---

## 7. Repository map

| Path | What |
|---|---|
| `frontend/` | React + Vite + Tailwind app (see `frontend/README.md`) |
| `backend/` | FastAPI service: cases, evidence, analysis runs, graph, uploads, auth, admin (see `backend/README.md`, API in `backend/openapi.json`) |
| `analysis_model/` | `run_case_analysis` (edge strength, centrality, communities, link prediction), weights `v1_2.json`, learned ranker; contract in `analysis_model/FACTORS.md` |
| `db/migrations/` | `001`–`006`: case schema, reviews, membership, security/audit, password login |
| `db/load_case.py` | Loads GAStech + derived evidence + Caviar + Noordin into `inv` |
| `db/seed_demo_security.py` | Creates the demo accounts, passwords and case access |
| `samples/upload/` | Fictional test case for the upload feature (valid + broken) |
| `results/` | Benchmark reports (hidden-link recovery 11.4× random on 24 real covert networks) |
| `docs/` | Dataset handoff, derived evidence method, references, original dataset README |

---

## 8. Setting up a fresh database (only if starting from an empty Supabase project)

```powershell
python -m pip install -r requirements-database.txt
python db/setup_database.py --apply                       # runs migrations 001–006
python db/load_case.py --dsn "<SUPABASE_DATABASE_URL>" --case-dir case --derived-dir derived --caviar-dir cases/caviar --noordin-dir cases/noordin
python db/seed_demo_security.py --dsn "<SUPABASE_DATABASE_URL>"
python db/sync_neo4j.py --case-id CASE_VAST_GASTECH       # optional, repeat per case
```

(Extract `datasets/GASTECH_MC1_MC2_VALIDATED_CASE.zip` into `case/` first.) The team's Supabase project already has all of this.

---

## 9. Tests

```powershell
# backend + model (needs a disposable Postgres for the database tests: set INV_TEST_DSN)
python -m pytest -q analysis_model/tests tests backend/tests/test_investigation_*.py backend/tests/test_auth_login.py
# frontend
cd frontend && npm test && npm run build
```

---

## 10. Deploy to Google Cloud Run

Follow **[DEPLOY_GOOGLE_CLOUD.md](DEPLOY_GOOGLE_CLOUD.md)**. The deploy builds the frontend and the API into one container and gives you one public HTTPS link.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError` when starting the backend | Install with the same Python: `python -m pip install -r requirements.txt` |
| `/health/database` shows `postgresql: unavailable` | Use the Session pooler URL; check the password; open the Supabase dashboard in case the project is paused |
| Graph badge says `Source: postgresql fallback` | Neo4j is paused or the details are wrong. Resume it at console.neo4j.io. The app works either way |
| "Backend unavailable" banner in the app | The backend isn't running on port 8000, or it can't reach the database |
| Sign-in says "Too many failed attempts" | Wait 15 minutes, or have an admin reset the password |
| Graph says "No analysis has been run…" | Click **Run analysis** (top bar) as an investigator or admin |
| `Activate.ps1` blocked (if you use a venv) | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

Free-tier Supabase and Neo4j Aura pause after a few days without use. Open both dashboards on demo day.
