from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..models import User
from .export_import import ImportReport, import_export

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class ImportRequest(BaseModel):
    path: str  # server-local path to an export directory or .zip


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
