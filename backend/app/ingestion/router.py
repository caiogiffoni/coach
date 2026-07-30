from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..garmin.client import GarminClient, garmin_client_or_raise
from ..models import User
from .api_pull import SyncReport, latest_local_date, sync_garmin_data
from .export_import import ImportReport, import_export

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class ImportRequest(BaseModel):
    path: str  # server-local path to an export directory or .zip


class IngestionStatusResponse(BaseModel):
    newest_date: date | None


class SyncRequest(BaseModel):
    days: int = 14


@router.get("/status", response_model=IngestionStatusResponse)
def ingestion_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestionStatusResponse:
    """Return the newest calendar date present in the local ingestion tables."""
    return IngestionStatusResponse(newest_date=latest_local_date(db))


@router.post("/import", response_model=ImportReport)
def import_garmin_export(
    body: ImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportReport:
    try:
        return import_export(Path(body.path), db)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid export: {exc}") from None


@router.post("/sync")
def sync_garmin(
    body: SyncRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GarminClient = Depends(garmin_client_or_raise),
) -> SyncReport:
    """Pull recent data from Garmin Connect and upsert into the local store."""
    report = sync_garmin_data(db, client, days_back=body.days)
    if report.needs_mfa:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"needs_mfa": True, "detail": "Garmin MFA required"},
        )
    return report
