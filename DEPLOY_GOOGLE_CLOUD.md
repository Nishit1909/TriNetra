# Deploying TriNetra (SIH26189) to Google Cloud Run

**Goal:** one public HTTPS link (for example `https://trinetra-xxxx.a.run.app`) that serves the frontend and the API together, using the Supabase and Neo4j instances we already have.

**Branch:** `final`
**Region:** `asia-southeast1` (Singapore). Supabase is also in Singapore, so the database is close.

Never commit passwords. Ask Nishit for the Supabase DB password, the Neo4j password and the SMTP app password. They go into Google **Secret Manager**, not into files.

---

## Part A: Code changes (already done on branch `final`)

These are already in the code:
- `Dockerfile`, `.dockerignore` and `.gcloudignore`
- the backend serves the built frontend, so the app runs as one service
- production mode works with `LOGIN_REQUIRED=true`
- the session cookie is `Secure`
- only `/api` calls are written to the access log

Get the code:
```powershell
git clone https://github.com/Nishit1909/VVCE_P2.git trinetra
cd trinetra
git checkout final
```

## Part B: Google Cloud setup (one time)

### B1. Account and credits
1. Go to https://console.cloud.google.com and sign in.
2. Students: claim credits through **Google Cloud for Education** or the free trial ($300 for 90 days). A billing account must be linked, even with credits.
3. Create a project: top bar → *New Project* → name `sih26189`. Note the **Project ID** (for example `sih26189-123456`).
4. Set a budget alert: *Billing → Budgets & alerts → Create budget*, for example ₹500, with alerts at 50%, 90% and 100%.

### B2. Install the gcloud CLI (Windows)
1. Download and install it from https://cloud.google.com/sdk/docs/install.
2. Open a new PowerShell window and run:
```powershell
gcloud init                 # sign in, then choose project trinetra-xxxx
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud config set run/region asia-southeast1
```

### B3. Enable the APIs
```powershell
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

### B4. Store the secrets
Run these in PowerShell. Each command creates a secret from text you type. **No trailing newline**, which is why they use `-NoNewline`.

```powershell
"postgresql://postgres.vegimprsgllfdpedmofu:<DB_PASSWORD>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres" | Out-File -NoNewline -Encoding ascii db.txt
gcloud secrets create supabase-db-url --data-file=db.txt

"<NEO4J_PASSWORD>" | Out-File -NoNewline -Encoding ascii neo.txt
gcloud secrets create neo4j-password --data-file=neo.txt

"<GMAIL_APP_PASSWORD>" | Out-File -NoNewline -Encoding ascii smtp.txt   # optional, only if using SMTP
gcloud secrets create smtp-password --data-file=smtp.txt

del db.txt, neo.txt, smtp.txt
```

Let Cloud Run read the secrets:
```powershell
$PN = gcloud projects describe <PROJECT_ID> --format="value(projectNumber)"
gcloud projects add-iam-policy-binding <PROJECT_ID> `
  --member="serviceAccount:$PN-compute@developer.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
```

---

## Part C: Deploy

From the repo root, on the `final` branch:

```powershell
gcloud run deploy trinetra `
  --source . `
  --region asia-southeast1 `
  --allow-unauthenticated `
  --memory 1Gi --cpu 1 `
  --timeout 300 `
  --min-instances 0 --max-instances 2 `
  --set-env-vars "APP_ENV=production,LOGIN_REQUIRED=true,AUTH_ENABLED=false,NEO4J_URI=neo4j+s://6f6df57f.databases.neo4j.io,NEO4J_USERNAME=6f6df57f,NEO4J_DATABASE=6f6df57f" `
  --set-secrets "SUPABASE_DATABASE_URL=supabase-db-url:latest,NEO4J_PASSWORD=neo4j-password:latest,SMTP_PASSWORD=smtp-password:latest"
```

- The first time, it asks to create an Artifact Registry repository. Answer **Y**.
- Cloud Build builds the Dockerfile in the cloud, so Docker isn't needed for this step. It takes about 5–8 minutes.
- At the end it prints the **Service URL**.
- `--allow-unauthenticated` only means the page is reachable. The app's own login still protects all the data.
- If you skipped the SMTP secret, remove `SMTP_PASSWORD=...` from `--set-secrets`.
- Leave out `--cpu 1` if it complains. If the analysis runs out of memory, use `--memory 2Gi`.

### To redeploy after changes
Run the same command again. Env vars and secrets are kept, so `gcloud run deploy trinetra --source . --region asia-southeast1` is enough.

---

## Part D: Check that it works

1. Open `<Service URL>/health/database`. Both databases should show `ok`. "degraded" means Neo4j is paused, and the app still works.
2. Open `<Service URL>` and sign in with `demo.admin@trinetra.demo`.
3. Go through every screen: Overview, Network Graph (3D/2D/List, blinking), Leads, Compare, Upload (`samples/upload/monsoon_ledger_case.zip`), and Admin (alerts, access log, sessions).
4. Sign in as the viewer in another browser or an incognito window. The admin should see a "signed in" alert.
5. Logs: `gcloud run services logs read trinetra --region asia-southeast1 --limit 100`, or in the Console under *Cloud Run → trinetra → Logs*.

---

## Part E: Before the demo (important)

- **Change the demo passwords.** The current ones are in the public README. In Admin → Users → reset each password, or sign in as each account and change it.
- **Demo day:** set `--min-instances 1` so there's no cold start:
  `gcloud run services update trinetra --region asia-southeast1 --min-instances 1`
  This costs a little per hour. Set it back to `0` afterwards.
- **Wake the free databases** an hour before: open the Supabase dashboard and console.neo4j.io. Both pause after inactivity.
- **SMTP (optional):** Admin → Settings → SMTP, host `smtp.gmail.com`, port 587, STARTTLS, your Gmail address, then Send test. The password comes from the `smtp-password` secret.
- **After the hackathon:** rotate the Supabase and Neo4j passwords, update the secrets (`gcloud secrets versions add supabase-db-url --data-file=...`) and redeploy. Or delete the service: `gcloud run services delete trinetra --region asia-southeast1`.

---

## Part F: Troubleshooting

| Problem | Fix |
|---|---|
| Deploy fails with `RuntimeError ... AUTH_ENABLED` | `LOGIN_REQUIRED=true` is missing from `--set-env-vars` |
| "Container failed to start and listen on PORT" | The CMD must use `${PORT}`; check the logs for a Python import error |
| `/health/database` shows postgresql unavailable | Wrong secret value (no newline, correct password), or Supabase is paused. Use the **pooler** URL, port 5432 |
| Neo4j unavailable | The instance is paused; resume it in console.neo4j.io. The app falls back to Postgres anyway |
| Login works but you're signed out right away | The cookie isn't being kept: check A2 and that you're using the `https://` URL |
| Page loads but `/api` returns HTML | The URL ends in a typo, or you are on an old branch; `git pull` on `final` |
| Blank page or 404 on refresh | `frontend/dist` isn't in the image; check the Dockerfile `COPY --from=web` line |
| Analysis is slow or times out | Use `--memory 2Gi --timeout 600` |
| `PERMISSION_DENIED` on secrets | Run the IAM binding command in B4 again |
| Build fails at `npm ci` | `frontend/package-lock.json` must be committed |

**Expected cost:** with min-instances set to 0, light demo traffic stays within the Cloud Run free tier. Builds and the registry cost a few rupees. Budget alerts (B1) protect you.
