.PHONY: backend frontend dev install docker test test-backend test-frontend lint-backend format-backend type-check-backend build clean migrate migration

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8003

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run these two commands in separate terminals:"
	@echo "  make backend"
	@echo "  make frontend"

install:
	cd backend && uv sync
	cd frontend && npm install

docker:
	docker compose up --build

test-backend:
	cd backend && uv run pytest tests/ -q

test-frontend:
	cd frontend && npm run build && npm run lint

test: test-backend test-frontend

lint-backend:
	cd backend && uv run ruff check app tests

format-backend:
	cd backend && uv run ruff format app tests && uv run ruff check --fix app tests

type-check-backend:
	cd backend && uv run mypy app tests

# Apply pending migrations (the backend also does this on startup).
migrate:
	cd backend && uv run alembic upgrade head

# Autogenerate a migration from model changes: make migration msg="add foo column"
migration:
	@test -n "$(msg)" || (echo 'usage: make migration msg="describe the change"' && exit 1)
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

build:
	cd frontend && npm run build

clean:
	rm -rf backend/data backend/__pycache__ \
	       frontend/node_modules frontend/dist \
	       backend/.venv
