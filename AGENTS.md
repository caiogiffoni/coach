# AGENTS.md — AI Running Coach

This file is a quick-start reference for AI coding agents. The project is a single-user web app that generates weekly running workouts from an athlete's Garmin data and pushes them to Garmin Connect after manual review.

---

## Project overview

- **What it does:** Reads activities, wellness, HRV, RHR, sleep, training load, and race data; builds a weekly running plan inside hard sports-science guardrails; lets the user review, approve, and push the plan to their Garmin Connect calendar. A standalone workout library (`/workouts`) lets the user build running workouts like Garmin Connect's workout builder, save them, and push any saved workout to a chosen date.
- **Scope (v1):** Single user, running only, manual "Generate week" trigger, no editor for generated week-plan workouts (the separate workout library has a builder), no mobile app, no background scheduler.
- **Auth model:** First-run registration opens only while the `users` table is empty, then closes permanently. One bearer token per session, stored in `localStorage` on the frontend.
- **Language of the codebase and docs:** English.

---

## Repository layout

```
coach/
├── backend/            # FastAPI + SQLite application
│   ├── app/            # Source modules (see below)
│   ├── tests/          # pytest suite
│   ├── pyproject.toml  # uv project + tool config
│   ├── uv.lock         # Locked Python dependencies
│   ├── Dockerfile      # Multi-stage image using uv
│   └── .env.example    # Template for backend secrets
├── frontend/           # Vite + React + TypeScript SPA
│   ├── src/            # Source modules (see below)
│   ├── package.json    # npm scripts + dependencies
│   ├── vite.config.ts  # Dev proxy + build config
│   ├── tsconfig.*.json # TypeScript configs
│   └── .oxlintrc.json  # Oxlint rules
├── temp/               # Prototype/analysis workspace and real Garmin export data
│                       # (ignored by git; contains PLAN.md implementation notes)
├── docker-compose.yml  # Local Docker stack (backend only)
├── Makefile            # Common dev commands
├── README.md           # User-facing run instructions
├── STYLE_GUIDE.md      # Frontend design system
└── PLAN.md             # Implementation plan (ignored by git)
```

---

## Technology stack

### Backend

- **Runtime:** Python 3.12, managed with `uv`.
- **Framework:** FastAPI + Uvicorn.
- **Database:** SQLite via SQLAlchemy 2.0 (declarative ORM, `Mapped` columns); Alembic migrations.
- **Auth:** JWT (HS256) with `bcrypt` password hashing.
- **Validation:** Pydantic v2, Pydantic-Settings for env loading.
- **LLM:** Provider-agnostic client.
  - Default provider is Kimi K2 via the OpenAI-compatible endpoint (`openai` package with custom `base_url`).
  - Optional Claude provider (`anthropic` package) switched by `LLM_PROVIDER=claude`.
  - If no API key is configured, generation falls back to a deterministic rule-based planner.
- **Garmin:** Unofficial `python-garminconnect` (v0.3.x) plus `curl_cffi` for TLS impersonation; token cache persisted on disk. No `garth`.
- **Data ingestion:** GDPR export zip/directory parser, FIT file parser (`fitparse`), and live Garmin Connect pull.

### Frontend

- **Bundler:** Vite 8 with the React plugin.
- **Framework:** React 19, TypeScript ~6.0, React Router 7.
- **Icons:** `lucide-react` (inline SVG, 1.5px stroke, `currentColor`).
- **Linting:** Oxlint (`npm run lint`); no ESLint/Prettier currently configured.
- **Styling:** Plain CSS in `src/styles/`. Design tokens are CSS custom properties in `tokens.css`; `base.css` implements `STYLE_GUIDE.md`. Components reference tokens only, never raw hex.

### Infrastructure

- **Local containerization:** Docker + Docker Compose for the backend; frontend still runs locally with `npm run dev`.
- **CI:** GitHub Actions `.github/workflows/ci.yml` runs backend tests (excluding real-data tests), frontend build/lint, and a Docker image build.

---

## Code organization

### Backend (`backend/app/`)

| Module | Responsibility |
|--------|----------------|
| `main.py` | FastAPI app, router registration, JSON logging setup, lifespan that runs Alembic migrations. |
| `config.py` | `pydantic_settings.BaseSettings`; loads `backend/.env`. |
| `db.py` | SQLAlchemy engine, `SessionLocal`, `get_db()` dependency, `Base`, model registry, `upgrade_database()`. |
| `logging_config.py` | Stdlib JSON log formatter + `configure_logging()`. |
| `models.py` | Shared `User` model. |
| `auth/` | Register/login (closes after first user), JWT security, `/api/auth/*`. |
| `ingestion/` | Import GDPR export, upload `.zip`/`.fit`, sync from Garmin API; stores normalized rows. |
| `profile/` | Athlete profile CRUD, seed from imported data, HR/pace zone calculator (`/api/profile/zones`). |
| `coaching/` | Constraint engine, LLM generator + validator, daily guard, week plan storage, `/api/coaching/*`. |
| `garmin/` | Garmin client wrapper, workout mapper, idempotent push, `/api/garmin/*`. |
| `llm/` | Provider-agnostic client (`kimi`/`claude`) and `get_llm_client` dependency. |
| `workouts/` | Workout library: builder step schemas (`schemas.py`), estimates, Garmin JSON mapper (`garmin_mapper.py`), CRUD/duplicate/push service, `/api/workouts/*`. Tables `library_workouts`, `library_workout_pushes`. |

Models live next to their routers (e.g. `app/profile/models.py`). They are listed in `MODEL_MODULES` in `app/db.py`; `import_all_models()` registers them for Alembic and the tests' `create_all`.

### Frontend (`frontend/src/`)

| File / Folder | Responsibility |
|---------------|----------------|
| `main.tsx` | Entry point; imports `tokens.css` and `base.css`. |
| `App.tsx` | Router: `/login`, `/week`, `/workouts`, `/profile`, `/data`. Protected routes use `RequireAuth`. |
| `api.ts` | Fetch wrapper, Bearer token handling, typed API clients for every backend domain. |
| `types.ts` | TypeScript interfaces mirroring backend Pydantic schemas. |
| `theme.ts` | `useTheme` hook; toggles `data-theme="dark"` on `<html>`. |
| `format.ts` | Date/pace/time formatting and ISO-week helpers. |
| `workout.ts` | Workout display helpers (zone badges, derived distance, step targets). |
| `components/` | `Nav`, `DayCard`, `RequireAuth`. |
| `pages/` | `Week`, `Workouts` (library + builder), `Profile`, `Data`, `Login`. |
| `styles/` | `tokens.css` (design tokens) and `base.css` (component classes). |

---

## Build, run, and test commands

All commands assume the repo root as working directory.

### Install dependencies

```bash
make install
# or manually:
cd backend && uv sync
cd frontend && npm install
```

### Run locally (two terminals)

```bash
# Terminal 1 — backend on port 8003 (Makefile default)
make backend

# Terminal 2 — frontend dev server
make frontend
```

The Vite dev proxy forwards `/api` to `http://localhost:8003` by default (`frontend/vite.config.ts`). If the backend runs on a different port:

```bash
cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev
```

### Run with Docker

```bash
cp backend/.env.example backend/.env
# edit backend/.env to add GARMIN_EMAIL/GARMIN_PASSWORD if you want push/sync
docker compose up --build
```

This exposes the backend on port 8000 and mounts `./backend/data` for the SQLite DB, Garmin tokens, and uploads. Then run the frontend locally with `cd frontend && npm run dev`.

### Test commands

```bash
make test              # backend pytest + frontend build/lint
make test-backend      # backend pytest only
make test-frontend     # frontend build + lint only
make lint-backend      # ruff check
make format-backend    # ruff format + auto-fix
make type-check-backend # mypy
make migrate           # alembic upgrade head
make migration msg=".." # alembic revision --autogenerate
make build             # frontend production build
make docker            # docker compose up --build
make clean             # remove data, node_modules, dist, venv
```

Backend tests run with `pythonpath = ["."]` (configured in `pyproject.toml`).

---

## Development conventions

### Python

- **Formatter/linter:** Ruff (target Python 3.12, line length 88). `E501` is ignored because the formatter handles line length.
- **Selected lint rules:** `E`, `F`, `I`, `W`.
- **Docstrings:** Google convention (`tool.ruff.lint.pydocstyle.convention = "google"`).
- **Type checking:** mypy with `check_untyped_defs = true`, Pydantic plugin, `ignore_missing_imports = true`.
- **Style notes:**
  - Prefer Pydantic models for request/response schemas in routers.
  - Use SQLAlchemy 2.0 style (`Mapped`, `mapped_column`, `select()`).
  - Keep routers thin; business logic lives in sibling modules (e.g. `constraints.py`, `generator.py`).
  - FastAPI dependencies are the primary seam for testing; tests override `get_db`, `get_llm_client`, and `get_garmin_client`.

### TypeScript / React

- **Linting:** Oxlint with `react/rules-of-hooks` as error and `react/only-export-components` as warn.
- **TS config:** `noUnusedLocals`, `noUnusedParameters`, `verbatimModuleSyntax`, `erasableSyntaxOnly`, `noFallthroughCasesInSwitch`.
- **Styling:** Must follow `STYLE_GUIDE.md`.
  - Flat, utility-first aesthetic; no gradients, glows, glassmorphism, emojis, or hero sections.
  - Deep blue is the only accent; semantic colors for status; zone colors are functional and theme-independent.
  - All components must use CSS custom properties from `tokens.css`/`base.css`, never raw hex values.
  - Numbers an athlete compares (paces, HR, distances, dates) use the `.mono` utility.
- **Icons:** Only `lucide-react`. Size 16px or 20px, stroke width 1.5px.

### General

- **Metric units:** minutes per kilometre, kilometres, grams, seconds, milliseconds.
- **Weekdays:** Backend and frontend both use `0 = Monday … 6 = Sunday`.
- **Dates:** ISO-8601 strings over the wire; frontend uses local-date helpers in `format.ts` to avoid timezone drift.
- **Minimal changes:** Make the smallest edit that satisfies the task. Do not refactor unrelated code.
- **No new dependencies without checking:** Confirm the project already uses a package before importing it.
- **Do not commit, push, or rebase** unless explicitly asked.

---

## Testing strategy

- **Backend:** pytest with an in-memory SQLite DB override (`tests/conftest.py`).
  - `client` fixture overrides `get_db` to create/destroy an in-memory DB per test.
  - `no_real_llm` autouse fixture overrides `get_llm_client` with `None`, so tests never call a real LLM.
  - `imported` fixture imports the real Garmin GDPR export from `temp/garmin_info/`. Any test using it is automatically marked `realdata`.
  - Marker: `@pytest.mark.realdata` for tests that need the private `temp/garmin_info/` export.
  - CI runs `pytest -m "not realdata"`.
- **Frontend:** `npm run build` (TypeScript + Vite) and `npm run lint` (Oxlint). There are no unit tests for the frontend yet.
- **End-to-end coverage:** `tests/test_end_to_end.py` exercises the full lifecycle with fake Garmin and LLM clients: register → import → seed → constraints → generate → guard → approve → push → sync.

---

## Security considerations

- **Secrets live in `backend/.env`** and are never committed (`.gitignore` ignores `.env` and `backend/data/`).
- **Critical env vars:**
  - `SECRET_KEY` — JWT signing key; must be ≥32 bytes or Settings validation fails at startup. The built-in dev default logs a warning.
  - `GARMIN_EMAIL` / `GARMIN_PASSWORD` — Garmin credentials; optional until push/sync is used.
  - `LLM_API_KEY` — LLM provider key; optional; missing key triggers deterministic fallback.
- **Auth:** Registration closes once one user exists (`/api/auth/status`). Passwords are bcrypt-hashed.
- **Garmin tokens** are cached on disk at `GARMIN_TOKEN_STORE` (`backend/data/garmin_tokens` locally); nothing Garmin-related is stored in the DB.
- **Uploads:** Temporary files go to `UPLOAD_DIR` (`backend/data/uploads`) and are cleaned up per request.
- **Database:** SQLite file lives in `backend/data/coach.db` (or `/app/data/coach.db` in Docker). Schema migrations are managed by Alembic.
- **Login rate limit:** `app/auth/rate_limit.py` keeps an in-memory, per-IP failure counter (5 per 15 min by default) and returns `429` + `Retry-After`. Inject/override it through the `get_login_rate_limiter` dependency.
- **Tests:** Real external APIs are never called in tests thanks to dependency overrides.

---

## Deployment / CI

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push/PR to `main`:

1. **Backend job:** `uv sync` → `ruff check .` → `ruff format --check .` → `mypy app` → `pytest -m "not realdata"`.
2. **Frontend job:** `npm ci` → `npm run build` → `npm run lint`.
3. **Docker job:** `docker build -t coach-backend:latest backend/`.

There is no production deployment pipeline in this repo. The Docker Compose file is intended for local use.

---

## First-run flow (for local development)

1. `make install`.
2. `cp backend/.env.example backend/.env` and set `SECRET_KEY` (and `LLM_API_KEY` if you want LLM generation).
3. Start backend and frontend (`make backend` / `make frontend`).
4. Open the UI, register the single allowed user.
5. Go to **Data** and import a Garmin GDPR export directory (e.g. `temp/garmin_info/`) or upload the zip/FIT files.
6. Go to **Profile**, click **Seed from data**, then edit goal/injuries/preferred days.
7. Go to **Week**, pick run days, add notes, click **Generate week**.
8. Review the draft, click **Approve**.
9. Set `GARMIN_EMAIL` and `GARMIN_PASSWORD` in `backend/.env`, restart the backend, then click **Push to Garmin**.

To schedule a one-off session, go to **Workouts**, build and save a workout, then push it to a date (also needs Garmin credentials).

Push and auto-sync require real Garmin credentials; the daily guard and workout generator run entirely on local data.

---

## Explicitly out of scope (v1)

- Editing generated week-plan workouts (week plans are regenerate/reject only; hand-built workouts live in the workout library).
- Multi-user support, OAuth, official Garmin Training API.
- Strength / cross-training workouts and route planning.
- Race-day predictor, VDOT charts, analytics dashboards.
- Native mobile app (the web UI is mobile-responsive only).
- Mid-week auto-adjustment beyond the daily guard's veto/swap.
- Background scheduler / auto-push / auto-generate.

---

## Code style

- **Functions:** 4–20 lines. Split if longer.
- **Files:** under 500 lines. Split by responsibility.
- **One thing per function, one responsibility per module (SRP).**
- **Names:** specific and unique. Avoid `data`, `handler`, `Manager`.
  Prefer names that return <5 grep hits in the codebase.
- **Types:** explicit. No `any`, no `Dict`, no untyped functions.
- **No code duplication.** Extract shared logic into a function/module.
- **Early returns over nested ifs.** Max 2 levels of indentation.
- **Exception messages must include the offending value and expected shape.**

## Comments

- **Keep your own comments.** Don't strip them on refactor — they carry
  intent and provenance.
- **Write WHY, not WHAT.** Skip `// increment counter` above `i++`.
- **Docstrings on public functions:** intent + one usage example.
- **Reference issue numbers / commit SHAs** when a line exists because
  of a specific bug or upstream constraint.

## Tests

- Tests run with a single command: `<project-specific>`.
- Every new function gets a test. Bug fixes get a regression test.
- Mock external I/O (API, DB, filesystem) with named fake classes,
  not inline stubs.
- Tests must be F.I.R.S.T: fast, independent, repeatable,
  self-validating, timely.

## Dependencies

- Inject dependencies through constructor/parameter, not global/import.
- Wrap third-party libs behind a thin interface owned by this project.

## Structure

- Follow the framework's convention (Rails, Django, Next.js, etc.).
- Prefer small focused modules over god files.
- Predictable paths: controller/model/view, src/lib/test, etc.

## Formatting

- Use the language default formatter (`cargo fmt`, `gofmt`, `prettier`,
  `black`, `rubocop -A`). Don't discuss style beyond that.

## Logging

- Structured JSON when logging for debugging / observability. `app/logging_config.py` installs a stdlib `JsonFormatter` on the root logger at startup; use `logging.getLogger(__name__)` and pass context via `extra={...}` (each key becomes a top-level JSON field).
- Plain text only for user-facing CLI output.

---

## Notes for agents

- **Read before editing:** Router schemas, Pydantic models, and the frontend `types.ts` must stay in sync. If you change one, update the others.
- **Run the checks:** After any code change run `make test` (or at least the relevant backend/frontend checks) before finishing.
- **Database changes:** The schema is managed by Alembic (`backend/alembic/`, `backend/alembic.ini`). The app runs `alembic upgrade head` on startup (FastAPI lifespan → `app.db.upgrade_database`); pre-Alembic DBs made by `create_all` are stamped at the baseline revision first. After adding/changing models or columns, run `make migration msg="..."`, review the generated file, and commit it. New model modules must be added to `MODEL_MODULES` in `app/db.py` so autogenerate and tests see them. `tests/test_migrations.py` fails if models drift from the migrations. Tests still use in-memory `create_all`.
- **LLM fallback:** It is fine to run without an LLM key — the generator falls back to deterministic workouts. This is also the test default.
- **Garmin mocking:** The `GarminClient` protocol in `app/garmin/client.py` is the seam for fakes; tests in `tests/test_end_to_end.py` show the expected interface.
- **`temp/` is a workspace:** It holds prototype scripts and the private Garmin export. It is gitignored; do not treat it as production code.
