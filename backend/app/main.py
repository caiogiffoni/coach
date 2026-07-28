from fastapi import FastAPI

from .auth.router import router as auth_router
from .db import Base, engine
from .ingestion import models as ingestion_models  # noqa: F401 — register tables
from .ingestion.router import router as ingestion_router

Base.metadata.create_all(engine)

app = FastAPI(title="AI Running Coach")
app.include_router(auth_router)
app.include_router(ingestion_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
