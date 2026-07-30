# coach

AI running coach → Garmin Connect. Generates weekly running workouts from your profile, zones, and fatigue data, and pushes them to your Garmin calendar after manual review.

## Tech stack

- Backend: FastAPI + SQLite, Python 3.12 via `uv`
- Frontend: Vite + React + TypeScript, styled per `STYLE_GUIDE.md`
- LLM: provider-agnostic (Kimi K2 default, Claude fallback), with a deterministic fallback when no API key is configured
- Garmin: unofficial `python-garminconnect` client for read/write

## Run locally

Two terminals:

```bash
# Terminal 1 — backend
cd backend
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
```

The Vite dev proxy forwards `/api` to `http://localhost:8000`. If port 8000 is already in use, start the backend on another port (e.g. `--port 8001`) and run the frontend with:

```bash
API_PROXY_TARGET=http://localhost:8001 npm run dev
```

### First-run flow

1. Open the UI and register (registration closes once the first user exists).
2. Go to **Data** and import your Garmin GDPR export directory (`temp/garmin_info/` is the default analysis workspace, or upload the zip through the UI).
3. Go to **Profile** and click **Seed from data**; edit goal, injury history, and preferred days as needed.
4. Go to **Week**, pick run days, add notes, and click **Generate week**.
5. Review the draft, then click **Approve**.
6. Set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in `backend/.env`, restart the backend, and click **Push to Garmin**.

Push and auto-sync require real Garmin credentials. The daily guard and workout generator run entirely on local data.

## Tests

```bash
# Backend
cd backend && uv run pytest tests/ -q

# Frontend
cd frontend && npm run build && npm run lint
```

## Backlog (explicitly out of v1)

- Workout editor UI (v1 is regenerate/reject only)
- Multi-user support, OAuth, official Garmin Training API migration
- Strength / cross-training workouts, route planning
- Race-day predictor, VDOT charts, analytics dashboards
- Mobile app (v1 web UI is mobile-responsive only)
- Mid-week auto-adjustment beyond the daily guard's veto/swap
