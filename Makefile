.PHONY: backend frontend dev install docker test test-backend test-frontend lint-backend format-backend build clean

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

build:
	cd frontend && npm run build

clean:
	rm -rf backend/data backend/__pycache__ \
	       frontend/node_modules frontend/dist \
	       backend/.venv
