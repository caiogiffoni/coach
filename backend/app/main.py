from fastapi import FastAPI

from .auth.router import router as auth_router
from .coaching import plan_models as plan_models  # noqa: F401 — register tables
from .coaching.router import router as coaching_router
from .db import Base, engine
from .garmin import models as garmin_models  # noqa: F401 — register tables
from .garmin.router import router as garmin_router
from .ingestion import models as ingestion_models  # noqa: F401 — register tables
from .ingestion.router import router as ingestion_router
from .profile import models as profile_models  # noqa: F401 — register tables
from .profile.router import router as profile_router

Base.metadata.create_all(engine)

app = FastAPI(title="AI Running Coach")
app.include_router(auth_router)
app.include_router(ingestion_router)
app.include_router(profile_router)
app.include_router(coaching_router)
app.include_router(garmin_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
