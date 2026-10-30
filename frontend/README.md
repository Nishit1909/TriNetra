# SIH26189 Frontend — Dark Liquid Glass Intelligence Command Centre

AI-assisted investigation platform for Smart India Hackathon (Problem SIH26189) enabling police analysts to explore criminal networks, uncover unrecorded links, and inspect the underlying source evidence and innocent explanations behind every lead.

## Stack
- **React 18 + Vite + TypeScript + Tailwind CSS**
- **Custom 60fps HTML5 Canvas Force-Directed Network Graph** (`react-force-graph-2d` compatible)
- **Dark Liquid Glass UI System** (`src/components/glass/`)
- **Typed OpenAPI Client** (`src/api/client.ts` & `src/api/types.ts`)

## Quick Start

```bash
# 1. Start the FastAPI backend (from repository root)
cd backend && python run.py

# 2. Install & start the Vite frontend
cd frontend
npm install
npm run dev
```

The Vite dev server runs at `http://localhost:5173` and proxies `/api` and `/health` to `VITE_API_BASE` (default `http://127.0.0.1:8000`).

## Environment Variables (`.env`)
- `VITE_API_BASE`: Backend URL (default `http://127.0.0.1:8000`)
- `VITE_PUBLIC_API_BASE`: only for a separately hosted frontend; leave empty to use the dev proxy.
- There is **no offline or fallback data**. Every value comes from the backend; if it is unreachable the app shows a "Backend unavailable" banner with a retry, never stand-in results.

## Sign-in

With `LOGIN_REQUIRED=true` on the backend the app opens on a login page. Demo accounts: **Admin** demo.admin@sih26189.demo / Admin@Trace2026 · **Investigator** demo.investigator1@sih26189.demo / Investigator@2026 · **Viewer** demo.viewer@sih26189.demo / Viewer@Trace2026. Sign out from the user menu (top right).

## Demo Role Switcher (`X-Demo-User`, only when login is off)
Use the top-right user menu to switch between the 5 seeded demo accounts:
1. **Demo Admin (Cyber Cell)** (`00000000-0000-4000-a000-000000000001`) — Full access + Admin Portal
2. **Demo Insp. Kavya Rao** (`00000000-0000-4000-a000-000000000002`) — Investigator (Editor on VAST GAStech & Noordin)
3. **Demo SI Arjun Mehta** (`00000000-0000-4000-a000-000000000003`) — Investigator (Editor on Caviar, Viewer on GAStech)
4. **Demo Analyst Neha Iyer** (`00000000-0000-4000-a000-000000000004`) — Viewer (Read-only on GAStech & Caviar)
5. **Kanon Herrero** (`00000000-0000-4000-a000-000000000005`) — Investigator with intentional name match to GAStech employee `P0025` for Conflict-of-Interest verification.


## Network graph

- **3D** (default, WebGL), **2D** and **List** views of the same data. If WebGL is unavailable the app switches to 2D automatically.
- Node tiers come from the analysis run: **key figures** (top 3 by PageRank, plus hubs in the top 10) are crimson and blink; **secondary figures** (next 7) are amber and breathe slowly; **connectors** (top bridging scores) get a cyan ring. Everyone else is tinted by community.
- Edges: observed solid, inferred violet dashed, predicted dotted (crimson = evidence-based, cyan = structural pattern) with moving particles.
- Click a person to inspect them, focus their neighbourhood or open their evidence profile; click a link to open the pair evidence.
- Respects reduced motion (no blinking, no particles).

## Scripts

```sh
npm ci
npm run dev        # http://127.0.0.1:5173, backend on :8000
npm test           # vitest (graph utilities)
npm run build      # type-check + production build
```

Demo identities (`X-Demo-User`) are only sent when the app runs on localhost. Bearer tokens, when used, stay in memory.
