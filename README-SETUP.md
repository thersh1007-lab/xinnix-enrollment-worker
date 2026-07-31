# XINNIX Enrollment Worker — Setup

A standalone Flask service that runs the XINNIX enrollment engine and all `/xinnix/*` endpoints. Extracted from the shared ATJ webhook so XINNIX can own and host it directly. It only touches the XINNIX GHL location.

## What it does

When a purchase happens, GHL workflow `06.5` calls this worker's `/xinnix/create-program-enrollment`. The worker resolves the student and manager, creates the Enrollment record(s), links contact/program/opportunity, stamps the deal + contact fields, and applies the `xinnix-roster-ready` tag (which fires `08.1`, the notification). It also serves the rep enrollment picker. Full architecture is in `ENROLLMENT-SYSTEM-HANDOFF.md`.

## Files

| File | What |
|---|---|
| `xinnix_worker.py` | The whole service (engine + endpoints + picker UI). |
| `requirements.txt` | flask, requests, gunicorn. |
| `render.yaml` | Render web-service config (build + start command + env var). |

## The one secret it needs

- `XINNIX_GHL_TOKEN` = the GHL **Private Integration Token (PIT)** for the XINNIX location (`Q9bdjGSsuJ4q8xRHgC0Z`). This is the only credential. Set it as an environment variable, never commit it.

## Deploy on Render (recommended)

1. Put this `xinnix-worker/` folder in a git repo (or point Render at a repo subdirectory).
2. Render dashboard -> **New -> Web Service** -> connect the repo.
   - Or use the included `render.yaml` (New -> Blueprint).
3. Settings:
   - **Runtime:** Python
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn xinnix_worker:app --workers 2 --threads 4 --timeout 120`
   - **Health check path:** `/health`
   - **Auto-deploy:** your choice. If off, you deploy manually after each push.
4. **Environment -> add** `XINNIX_GHL_TOKEN` = the PIT.
5. Deploy.

Runs anywhere Python + gunicorn run (Railway, Fly.io, a VM). Only the env var and start command matter.

## Verify it is live

- `GET https://<your-host>/health` -> `{"ok": true, ...}`
- `GET https://<your-host>/xinnix/version` -> the build string
- `GET https://<your-host>/debug-logs` -> recent internal log lines (your best diagnostic; shows exactly what each enrollment run resolved)

## Point GHL at your instance

The enrollment webhook URLs live in workflow **06.5** (id `adfa71c7-627d-4bd1-9a52-ac12f5fcea5a`). Each "Webhook" action currently points at the old shared host `https://atj-webhook.onrender.com/xinnix/create-program-enrollment`. Repoint them to `https://<your-host>/xinnix/create-program-enrollment`. That is the only change needed to move traffic to your instance.

The enrollment picker link becomes `https://<your-host>/xinnix/enrollment-picker` (password `xinnix2026`).

## Endpoints

| Method + Path | Purpose |
|---|---|
| `POST /xinnix/create-program-enrollment` | The enrollment engine (called by 06.5). `dry_run:true` reports the plan without creating anything. |
| `GET  /xinnix/enrollment-picker` | Rep enrollment picker UI. |
| `GET  /xinnix/enroll-grid?opp=<id>` | Picker grid data. |
| `POST /xinnix/enroll-grid` | Apply the picker grid. |
| `POST /xinnix/enroll-grid/add-student` | Picker Add-student (create/find a student for a manager purchase). |
| `GET  /xinnix/opp-search?q=<text>` | Deal search for the picker. |
| `POST /xinnix/proposal-estimate` | Auto-draft an estimate. |
| `POST /xinnix/enrollment-program-link` | Link an enrollment to a program. |
| `GET  /xinnix/version` | Current build string. |
| `GET  /debug-logs` , `GET /health` | Diagnostics. |

## Making changes

- Edit `xinnix_worker.py`, bump `XINNIX_WEBHOOK_VERSION` (near the version endpoint), push, redeploy, and confirm the new string at `/xinnix/version`.
- The engine returns `{"accepted":true,"async":true}` immediately and does the real work in a background thread, so GHL's webhook action never times out. Check `/debug-logs` to see what the worker actually did.
- All the GHL IDs, workflow ids, gotchas, and the danger list (bulk writes that email real customers) are in `ENROLLMENT-SYSTEM-HANDOFF.md`. Read that before changing enrollment behavior.
