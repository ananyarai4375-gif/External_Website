# CineVerse public demo deployment

The current project is a vanilla HTML/CSS/JavaScript frontend with a Python HTTP backend. Keep the backend on Render (the checked-in Blueprint config targets Render); Vercel serves the built static frontend. PostgreSQL shares active sessions and simulated VM state between backend instances. The VM cards/scaling/self-healing values are intentionally simulated and do not provision real cloud VMs.

## Files

- `index.html`, `app.js`, `styles.css`: booking site; `runtime-config.js` gets generated for Vercel builds.
- `admin.html`, `admin.js`: live simulated operations dashboard at `/admin.html`.
- `server.py`: API, health check, CORS, session/capacity handling, and simulated autoscaler.
- `package.json`, `scripts/build.mjs`, `vercel.json`: frontend build and local `npm run dev` command.
- `requirements.txt`, `render.yaml`: Render backend and PostgreSQL Blueprint.
- `.env.example`, `.gitignore`: variable reference and local-secret protection.
- `test_server.py`: backend regression tests.

## Environment variables

Copy `.env.example` locally to `.env` for local development; `python-dotenv` loads it when installed. The `.env` file is ignored by Git and never served. Configure the corresponding values in each hosting provider:

| Variable | Where | Example / purpose |
| --- | --- | --- |
| `DATABASE_URL` | Render backend only | Render PostgreSQL internal connection string; secret. |
| `CORS_ORIGINS` | Render backend | Comma-separated exact origins, e.g. `https://my-movie-demo.vercel.app`. No paths/trailing slash. |
| `MAX_ACTIVE_USERS` | Render backend | Hard ceiling for active demo visitors, default `50`. |
| `VM_CAPACITY` | Render backend | Simulated visitor slots per VM, default `10`. |
| `MAX_SIMULATED_VMS` | Render backend | Maximum simulated VMs, default `5`. |
| `SESSION_TIMEOUT_SECONDS` | Render backend | Abandoned tab cleanup, default `60`; heartbeat runs every 10 seconds. |
| `SCALE_DOWN_AFTER_SECONDS` | Render backend | Delay before simulated scale-down, default `120`. |
| `PORT`, `HOST` | Render backend | Render supplies `PORT`; host defaults to `0.0.0.0`. |
| `VITE_API_BASE_URL` | Vercel build environment | Public backend origin only, e.g. `https://cineverse-backend.onrender.com`. It is compiled into public JS and must never contain credentials. |

The first simulated VM admits visitors up to its configured capacity, adds a simulated VM near 80% utilization, and keeps accepting up to `MAX_ACTIVE_USERS` and `VM_CAPACITY × VM_COUNT` (whichever is lower). Above that, page entry and booking get HTTP 503 and show the full-page busy overlay. For a strict 10-user demo, set `MAX_ACTIVE_USERS=10` (one VM at capacity); for visible scale-up activity, set `MAX_ACTIVE_USERS=30`, `VM_CAPACITY=10` and `MAX_SIMULATED_VMS=3`.

## GitHub

1. Create a private or public empty GitHub repository.
2. In this project directory, initialize Git if needed, commit the project, and push the default branch. `.gitignore` excludes `.env`, virtual environments, dependencies and build output. Confirm no real credentials are committed before pushing.
3. Do not commit a real `.env`; only `.env.example` belongs in Git.

## Render backend and PostgreSQL

1. In Render, choose **New → Blueprint** and select the GitHub repository containing `render.yaml`.
2. Review the Blueprint and create the `cineverse-backend` web service and `cineverse-postgres` database. Render supplies `DATABASE_URL` through the Blueprint reference.
3. The service uses `pip install -r requirements.txt`, starts with `python server.py`, and has health check `/health`.
4. Wait for deployment to be healthy. Verify `https://<render-service>.onrender.com/health` returns `{"status":"healthy"}`.
5. If creating resources manually instead, create a PostgreSQL database, copy its **internal** connection string into the backend's secret `DATABASE_URL`, then add `CORS_ORIGINS`, `MAX_ACTIVE_USERS`, `VM_CAPACITY`, and `MAX_SIMULATED_VMS` to the backend environment and redeploy.
6. Free service/database availability, quotas and sleep/retention behavior depend on the current Render plan. Choose a plan whose database retention and service uptime meet your demo needs. A Render service can restart; PostgreSQL is what preserves shared sessions/VM state across processes.

## Vercel frontend and API connection

1. In Vercel, **Add New → Project**, import the same GitHub repository, and keep the project root at the repository root.
2. Vercel reads `vercel.json`: build command `npm run build`, output directory `dist`.
3. In Vercel project **Settings → Environment Variables**, set `VITE_API_BASE_URL` to the Render HTTPS origin without a trailing slash. Set it for Preview and Production as appropriate.
4. Deploy. The build script writes `dist/runtime-config.js`; frontend calls `${VITE_API_BASE_URL}/api/...` and does not contain a backend secret.
5. Copy the final Vercel origin into Render `CORS_ORIGINS`, e.g. `https://my-movie-demo.vercel.app` (include any separate preview origin only if needed), then redeploy the backend. CORS allows the session header used for per-tab tracking.
6. Redeploy the frontend after changing its environment variable. CORS and frontend URL settings are separate: Vercel knows where the API is; Render allows the Vercel origin.

## Local development

Install Python 3.10+ and Node.js/npm, then run `npm run dev` from the project root. It starts the backend and serves the website on `http://localhost:8000`; frontend API URL defaults to same-origin. `npm run build` can be run locally to verify the production static output. Backend tests: `python -m unittest test_server.py -v`.

## Friends and demo checks

Share `https://<your-vercel-project>.vercel.app`. Friends can select movie, theatre, date, showtime and seats; booking requests go to the shared Render backend. Keep the `/admin.html` dashboard open to watch active users, simulated VM health/CPU/memory, capacity, scale events and self-healing status update every three seconds.

To test busy behavior without creating many real devices, set a small `MAX_ACTIVE_USERS` value on Render and open separate private/incognito browser profiles/devices (each profile is a distinct tab session). The 11th visitor is busy when the limit is 10. For visible simulated VM additions, choose the larger example capacity above, since a single VM at capacity does not need to scale further. Closing tabs releases sessions; abandoned sessions expire after the configured heartbeat timeout.

This is a demo booking API: successful requests return a booking accepted response; they do not charge a card or persist ticket orders. Simulated VM scaling changes dashboard state only. Render/Railway must be configured separately if you want the hosting provider to autoscale real backend instances.