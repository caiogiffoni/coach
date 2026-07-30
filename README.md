# coach

AI running coach → Garmin Connect. Web app that generates weekly running workouts from your profile, zones, and fatigue data, and pushes them to your Garmin calendar.

## Build progress

- [x] 1. Backend skeleton + auth (first-run register, login)
- [x] 2. Ingestion: port utils.py loaders, GDPR zip import
- [ ] 3. Profile + zone calculator
- [ ] 4. Constraint engine (port plan_week state)
- [ ] 5. LLM generation + validator
- [ ] 6. Frontend v1 (login, profile, generate, review)
- [x] 7. Garmin push (client, mapper, idempotent push)
- [ ] 8. Auto-pull + daily guard
- [ ] 9. Manual upload endpoint (FIT/zip)
- [ ] 10. End-to-end hardening

## Backlog (explicitly out of v1)

- Workout editor UI (v1 is regenerate/reject only)
- Multi-user support, OAuth, official Garmin Training API migration
- Strength / cross-training workouts, route planning
- Race-day predictor, VDOT charts, analytics dashboards
- Mobile app (v1 web UI is mobile-responsive only)
- Mid-week auto-adjustment beyond the daily guard's veto/swap
