from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .auth.router import router as auth_router
from .coaching.router import router as coaching_router
from .config import settings
from .db import import_all_models, upgrade_database
from .garmin.router import router as garmin_router
from .ingestion.router import router as ingestion_router
from .logging_config import configure_logging
from .profile.router import router as profile_router
from .workouts.router import router as workouts_router

configure_logging(settings.log_level)
# Register every table on Base.metadata (tests' create_all relies on this).
import_all_models()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Apply pending Alembic migrations before serving requests."""
    upgrade_database(settings.database_url)
    yield


app = FastAPI(title="AI Running Coach", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(profile_router)
app.include_router(coaching_router)
app.include_router(garmin_router)
app.include_router(workouts_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
