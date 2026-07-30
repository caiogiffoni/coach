# Backend Docker image
# Multi-stage build using uv for fast, reproducible dependency installs.

FROM python:3.12-slim-bookworm AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency metadata first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install production dependencies into a virtual environment
RUN uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runner

WORKDIR /app

# Copy the synced venv from the builder stage
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app ./app

# Ensure data directory exists and is writable (SQLite DB, tokens, uploads)
RUN mkdir -p /app/data && chmod 777 /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL="sqlite:////app/data/coach.db"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
