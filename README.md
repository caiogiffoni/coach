# coach

AI running coach → Garmin Connect. Generates weekly running workouts from your profile, zones, and fatigue data, and pushes them to your Garmin calendar after manual review. A workout library page (**Workouts**) lets you build your own running workouts (warmup/run/recover/rest/cooldown steps, repeat blocks, time/distance/lap-button ends, HR zone, HR range or pace targets), save them, and push any of them to a chosen date on Garmin.

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

Or use the Makefile targets in two terminals:

```bash
# Terminal 1
make backend

# Terminal 2
make frontend
```

The Vite dev proxy forwards `/api` to `http://localhost:8000`. If port 8000 is already in use, start the backend on another port (e.g. `--port 8001`) and run the frontend with:

```bash
API_PROXY_TARGET=http://localhost:8001 npm run dev
```

Other useful targets:

```bash
make install        # uv sync + npm install
make test           # all tests + frontend build/lint
make test-backend   # backend pytest only
make test-frontend  # frontend build + lint only
make lint-backend     # backend ruff lint
make format-backend   # backend ruff format + auto-fix
make type-check-backend # backend mypy type check
make build            # frontend production build
make docker         # docker compose up --build
make migrate        # apply pending DB migrations (also runs on backend startup)
make migration msg="add foo column"  # autogenerate a migration from model changes
```

### Configuration

- `SECRET_KEY` (JWT signing key) must be at least 32 bytes or the backend refuses to start. Generate one with `openssl rand -hex 32`. Using the built-in dev default logs a warning.
- Failed logins are rate-limited in memory: 5 failures per client IP per 15 minutes returns `429` with a `Retry-After` header (`LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS`).
- Backend logs are structured JSON on stdout (`LOG_LEVEL`, default `INFO`).

### Database migrations

The schema is managed by Alembic (`backend/alembic/`). On startup the backend runs `alembic upgrade head`; a database created before Alembic existed (tables present, no `alembic_version`) is stamped at the baseline revision first. After changing a model:

```bash
make migration msg="describe the change"   # review the generated file in backend/alembic/versions/
make migrate
```

### First-run flow

1. Open the UI and register (registration closes once the first user exists).
2. Go to **Data** and import your Garmin GDPR export directory (`temp/garmin_info/` is the default analysis workspace, or upload the zip through the UI).
3. Go to **Profile** and click **Seed from data**; edit goal, injury history, and preferred days as needed.
4. Go to **Week**, pick run days, add notes, and click **Generate week**.
5. Review the draft, then click **Approve**.
6. Set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in `backend/.env`, restart the backend, and click **Push to Garmin**.

To schedule a one-off session outside the weekly plan, open **Workouts**, build and save a workout, then push it to a date. Pushing the same workout twice to the same date creates two Garmin calendar entries.

Push and auto-sync require real Garmin credentials. The daily guard and workout generator run entirely on local data.

## Run with Docker

The backend can also run in Docker (frontend still runs locally with `npm run dev`):

```bash
cp backend/.env.example backend/.env
# edit backend/.env to add GARMIN_EMAIL/GARMIN_PASSWORD if you want push/sync
docker compose up --build
```

This mounts `./backend/data` as a volume so the SQLite database and Garmin tokens persist across container restarts. The API is exposed on port 8000. Then run the frontend with:

```bash
cd frontend
npm run dev
```

If port 8000 is already in use, change the host mapping in `docker-compose.yml` (e.g. `"8001:8000"`) and set `API_PROXY_TARGET=http://localhost:8001 npm run dev`.

## Tests

```bash
# Backend
cd backend && uv run pytest tests/ -q

# Frontend
cd frontend && npm run build && npm run lint
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs backend lint (`ruff check`, `ruff format --check`), `mypy app`, and the backend tests (excluding the private real-data suite), builds the frontend, and builds the Docker image on every push/PR to `main`.

## Backlog (explicitly out of v1)

- Editing generated week-plan workouts (week plans are regenerate/reject only; build custom sessions in the workout library instead)
- Multi-user support, OAuth, official Garmin Training API migration
- Strength / cross-training workouts, route planning
- Race-day predictor, VDOT charts, analytics dashboards
- Mobile app (v1 web UI is mobile-responsive only)
- Mid-week auto-adjustment beyond the daily guard's veto/swap

### Chatbot — single-day workout bot (planned)

A chat page (`/chat`) where you type natural-language requests like "me manda um treino leve de quarta" or "random Monday", review the drafted workout, tweak it ("faz 50 minutos"), regenerate it, and push it to Garmin on approval.

- **Template library:** imports all running workouts from your Garmin `workout.json` during data import; categorized by effort (`light`, `fartlek`, `long`, `tempo`) and day of week.
- **Intent parsing:** LLM via OpenRouter (`moonshotai/kimi-k2`) with structured output.
- **Flow:** message → draft → tweak/regenerate → approve → push.
- **Auth:** same JWT as the app; no external agent (no Kimi Claw).
- **MVP:** single-day only; Telegram and stats queries come later.

Full details: `CHATBOT_PLAN.md`.
