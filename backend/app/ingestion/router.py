import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..config import settings
from ..db import get_db
from ..garmin.client import GarminClient, garmin_client_or_raise
from ..models import User
from .api_pull import SyncReport, latest_local_date, sync_garmin_data
from .export_import import ImportReport, import_export
from .fit_parser import FitParser, fit_parser_dependency, upsert_activity_from_fit

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class ImportRequest(BaseModel):
    path: str  # server-local path to an export directory or .zip


class IngestionStatusResponse(BaseModel):
    newest_date: date | None


class SyncRequest(BaseModel):
    days: int = 14


class FileResult(BaseModel):
    filename: str
    status: str  # "ok" | "error"
    detail: str | None = None
    counts: ImportReport | None = None


class UploadReport(BaseModel):
    files: list[FileResult]
    totals: ImportReport


def _empty_report() -> ImportReport:
    return ImportReport()


def _add_report(total: ImportReport, other: ImportReport) -> None:
    for field in ImportReport.model_fields:
        setattr(total, field, getattr(total, field) + getattr(other, field))


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
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Invalid export: {exc}"
        ) from None


@router.post("/upload", response_model=UploadReport)
def upload_files(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    parser: FitParser = Depends(fit_parser_dependency),
) -> UploadReport:
    """Accept GDPR export zips and/or FIT activity files from the browser."""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="upload_", dir=upload_dir))

    results: list[FileResult] = []
    totals = _empty_report()

    try:
        for upload in files:
            ext = Path(upload.filename or "").suffix.lower()
            result = _process_upload(upload, ext, tmpdir, db, parser)
            results.append(result)
            if result.counts is not None:
                _add_report(totals, result.counts)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return UploadReport(files=results, totals=totals)


def _process_upload(
    upload: UploadFile,
    ext: str,
    tmpdir: Path,
    db: Session,
    parser: FitParser,
) -> FileResult:
    filename = upload.filename or "unknown"

    if ext == ".zip":
        return _process_zip(upload, tmpdir, db, filename)

    if ext in {".fit", ".FIT"}:
        return _process_fit(upload, tmpdir, db, parser, filename)

    return FileResult(
        filename=filename,
        status="error",
        detail=f"Unsupported file type: {ext or 'none'}. Only .zip and .fit are accepted.",
    )


def _process_zip(
    upload: UploadFile,
    tmpdir: Path,
    db: Session,
    filename: str,
) -> FileResult:
    zip_path = tmpdir / f"{upload.filename or 'export'}.zip"
    try:
        _save_upload(upload, zip_path)
        report = import_export(zip_path, db)
        return FileResult(filename=filename, status="ok", counts=report)
    except FileNotFoundError as exc:
        return FileResult(filename=filename, status="error", detail=str(exc))
    except (ValueError, KeyError, zipfile.BadZipFile) as exc:
        return FileResult(
            filename=filename, status="error", detail=f"Invalid zip: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        return FileResult(
            filename=filename, status="error", detail=f"Import failed: {exc}"
        )


def _process_fit(
    upload: UploadFile,
    tmpdir: Path,
    db: Session,
    parser: FitParser,
    filename: str,
) -> FileResult:
    fit_path = tmpdir / f"{upload.filename or 'activity'}.fit"
    try:
        _save_upload(upload, fit_path)
        parsed = parser(fit_path)
        upsert_activity_from_fit(db, parsed)
        db.commit()
        report = ImportReport(activities=1)
        return FileResult(filename=filename, status="ok", counts=report)
    except ValueError as exc:
        db.rollback()
        return FileResult(filename=filename, status="error", detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return FileResult(
            filename=filename, status="error", detail=f"FIT parse failed: {exc}"
        )


def _save_upload(upload: UploadFile, dest: Path) -> None:
    with open(dest, "wb") as f:
        for chunk in upload.file:
            f.write(chunk)


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
