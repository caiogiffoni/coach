# Chatbot — Single-Day Workout Bot

## Goal

A chat page inside the existing AI Running Coach app where the user types natural-language requests ("me manda um treino leve de quarta", "random Monday", "amanhã") and receives a drafted single-day running workout. After user approval, the workout is pushed to Garmin Connect on the requested date.

## Decisions locked

| # | Decision | Choice |
|---|----------|--------|
| 1 | Project structure | Feature of the existing coach app (not a separate project) |
| 2 | Interface | New frontend page `/chat` (no Kimi Claw, no Telegram for MVP) |
| 3 | Hosting | Same server as the current app (local / Docker / VPS later) |
| 4 | LLM provider | OpenRouter with `moonshotai/kimi-k2` (Claude fallback via `LLM_MODEL`) |
| 5 | Intent parsing | LLM with structured JSON output (not regex) |
| 6 | Workout source | Import all running workouts from `temp/garmin_info/.../workout.json` (712 templates) |
| 7 | Template categories | `light`, `fartlek`, `long`, `tempo`, `other` inferred from workout names |
| 8 | Date semantics | Named weekday → next future occurrence; no date → tomorrow |
| 9 | Conversation state | Stateless backend; chat page keeps `draft_id` in memory |
| 10 | Auth | Existing JWT from the app (no external API key needed) |
| 11 | MVP scope | Single-day only, regenerate allowed, simple numeric tweaks allowed (duration/distance), no stats queries, no multi-day planning |

## Architecture

```
User (browser /chat)
  ↓ types message
Frontend Chat page
  ↓ POST /api/chat/message {text}
Backend
  ├─ LLM intent parser → {category, target_date, raw_text}
  ├─ WorkoutTemplate picker (random from category)
  ├─ PendingWorkout store (draft_id, template, target_date, expires)
  ↓ returns draft preview
User approves
  ↓ POST /api/chat/approve {draft_id}
Backend
  ├─ Converts template to Workout row
  ├─ Reuses Garmin push logic (idempotent, skip-and-warn)
  ↓ PushReport
```

## Data model

### `WorkoutTemplate` (new table)

| Column | Type | Notes |
|--------|------|-------|
| id | int | PK |
| name | str | e.g. "Corrida Contínuo seg 05/12" |
| category | str | `light` / `fartlek` / `long` / `tempo` / `other` |
| day_of_week | int \| null | inferred from name: seg=0 … dom=6 |
| sport | str | `running` |
| duration_min | float | from `estimatedDurationInSecs` |
| steps_json | JSON | Garmin `workoutSteps` simplified to our step schema |
| structure_hash | str | dedupe key (steps + duration) |
| source_garmin_id | str | original `workoutId` |
| created_at | datetime | |

### `PendingWorkout` (new table)

| Column | Type | Notes |
|--------|------|-------|
| id | int | PK |
| user_id | int | FK |
| draft_id | str (uuid) | public handle |
| template_id | int | FK |
| target_date | date | resolved date |
| status | str | `pending` / `approved` / `discarded` / `expired` |
| raw_text | str | original user message |
| parsed_intent | JSON | LLM output |
| created_at | datetime | |
| expires_at | datetime | e.g. 30 minutes |

## Template import

Integrated into the existing `import_export()` ingestion flow. When a GDPR export (dir or zip) is imported, the importer also reads `*_workout.json` files and populates `workout_templates`:

1. Filter `sportType.sportTypeKey == "running"`.
2. Infer effort category from name keywords (case-insensitive) via `infer_category()`:
   - `Contínuo`, `Regenerativo`, `Polimento` → `light`
   - `Fartlek`, `Intervalado` → `fartlek`
   - `Longo` → `long`
   - `Ritmado`, `Progressivo` → `tempo`
   - everything else → `other`
3. Infer day of week from name abbreviations via `infer_day_of_week()`:
   - `seg` → 0, `ter` → 1, `qua` → 2, `qui` → 3, `sex` → 4, `sáb`/`sab` → 5, `dom` → 6
   - no match → `null`
4. Convert Garmin steps to our internal step format (type, duration_min, target_zone/pace/hr when present).
5. Compute `structure_hash` from simplified steps + duration; skip duplicates.
6. Upsert into `workout_templates`.

The template picker (`app/chat/picker.py`) can then filter by `category`, `day_of_week`, or both:
- "treino leve de segunda" → `category=light AND day_of_week=0`
- "random Monday" → `day_of_week=0` (any category)
- "completely random" → no filter

## Intent parsing

LLM prompt receives the user's message and returns strict JSON:

```json
{
  "action": "request_workout" | "tweak" | "regenerate" | "approve" | "discard" | "other",
  "category": "light" | "fartlek" | "long" | "tempo" | "random" | null,
  "target_date": "YYYY-MM-DD" | null,
  "tweak": {
    "field": "duration_min" | "distance_km" | null,
    "value": number | null
  } | null,
  "confidence": 0.0-1.0
}
```

Action handling:
- `request_workout` → pick a template, create `PendingWorkout`, return draft.
- `tweak` → if a `PendingWorkout` is active, update the requested field (duration or distance) and return the updated draft. Duration tweaks scale step durations proportionally.
- `regenerate` → pick a different template from the same category/day (if any), replace the active draft.
- `approve` / `discard` → convenience intents; the dedicated endpoints are the primary path, but chat text like "aprova" also works.
- `other` or low confidence → reply asking for clarification.

Date resolution rules:
- Explicit date → use it.
- Weekday name → next future occurrence of that weekday.
- "amanhã" / "tomorrow" → tomorrow.
- No date → tomorrow.
- `category: "random"` → pick from all categories.

## API endpoints

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/chat/message` | `{text, draft_id?}` | `{draft_id, workout, message}` |
| POST | `/api/chat/approve` | `{draft_id}` | `PushReport` |
| POST | `/api/chat/discard` | `{draft_id}` | `{status: "discarded"}` |
| GET | `/api/chat/templates` | — | template list (debug/admin) |

The `message` endpoint handles everything in one place: new workout request, tweak, or regenerate. If the parsed intent is `tweak` or `regenerate`, `draft_id` is required; otherwise a new draft is created.

All endpoints require the existing JWT (`get_current_user`).

## Frontend

New page `/chat`:

- Message list (user + bot bubbles, per STYLE_GUIDE).
- Input box + send button.
- Bot reply shows workout card (name, date, duration, steps, zone badges).
- Approve / Discard / Regenerate buttons on the workout card; tweaks are typed in chat ("faz 50 minutos").
- After approve, show `PushReport` (pushed date or skip warning).

## Backend modules

```
app/chat/
├── models.py          # WorkoutTemplate, PendingWorkout
├── intent.py           # LLM structured-output parsing
├── picker.py           # random template selection + fallback
├── router.py           # /api/chat/* endpoints
└── service.py          # message → draft → approve orchestration

app/ingestion/
└── workout_templates.py # infer_category, infer_day_of_week, import from *_workout.json
                           # (called by import_export)
```

## Security

- No external agent (Kimi Claw removed).
- Chat endpoints use the same JWT as the rest of the app.
- LLM sees only the user's message and a fixed system prompt; no Garmin credentials, no database access.
- Garmin credentials remain in `backend/.env`; push happens only after explicit approval.

## Build order

1. **Models + template import** — `WorkoutTemplate`, `PendingWorkout`, `app/ingestion/workout_templates.py` with `infer_category()` / `infer_day_of_week()`, integrated into `import_export()`; tests for categorization, day inference, and dedupe.
2. **Intent parser** — LLM structured output with fake client in tests.
3. **Chat endpoints** — message → draft / tweak / regenerate, approve → push, discard; reuse existing Garmin push.
4. **Frontend chat page** — `/chat` route, message list, workout card, approve/discard.
5. **End-to-end test** — full flow with fake LLM and fake Garmin.
6. **Docs** — update README with `/chat` usage and OpenRouter env vars.

## Out of scope (MVP)

- Telegram / Discord / Slack bots.
- Kimi Claw or any third-party agent interface.
- Multi-day or weekly workout requests.
- Complex workout editing (changing zones, paces, step structure) before approval.
- Stats / history queries ("how many km last week").
- Voice input.
- Structured logging/observability beyond basic request logs.

## Backlog (post-MVP)

- Telegram bot interface.
- "Organize my week" multi-day suggestions.
- Template editor UI.
- Stats chat queries.
- Conversation history persistence.
