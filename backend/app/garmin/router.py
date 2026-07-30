"""Garmin Connect endpoints (PLAN.md step 7).

- POST /api/garmin/login     — authenticate (with optional MFA code)
- GET  /api/garmin/status    — credentials configured / session active
- POST /api/garmin/push      — push an approved week to Garmin Connect
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.security import get_current_user
from ..db import get_db
from ..models import User
from .client import (
    GarminClient,
    LoginResult,
    garmin_client_or_raise,
    get_garmin_client,
)
from .push import PushReport, push_week

router = APIRouter(prefix="/api/garmin", tags=["garmin"])


class LoginRequest(BaseModel):
    mfa_code: str | None = None


class StatusResponse(BaseModel):
    configured: bool
    logged_in: bool
    message: str


class PushResponse(BaseModel):
    pushed_dates: list[str]
    skipped_dates: list[dict[str, str]]
    errors: list[str]


@router.post("/login", response_model=LoginResult)
def garmin_login(
    body: LoginRequest,
    client: GarminClient = Depends(garmin_client_or_raise),
) -> LoginResult:
    """Log in to Garmin Connect, resuming an MFA challenge if one is pending."""
    return client.login(mfa_code=body.mfa_code)


@router.get("/status", response_model=StatusResponse)
def garmin_status(
    client: GarminClient | None = Depends(get_garmin_client),
) -> StatusResponse:
    """Return whether Garmin credentials are configured and the session state."""
    if client is None:
        return StatusResponse(
            configured=False,
            logged_in=False,
            message="Garmin credentials not configured",
        )
    if client.is_logged_in():
        return StatusResponse(
            configured=True,
            logged_in=True,
            message="Connected to Garmin",
        )
    return StatusResponse(
        configured=True,
        logged_in=False,
        message="Login required",
    )


@router.post("/push", response_model=PushResponse)
def push_week_plan(
    week_start: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    client: GarminClient = Depends(garmin_client_or_raise),
) -> PushResponse:
    """Push the approved week starting on ``week_start`` to Garmin Connect."""
    report = push_week(week_start, user, db, client)
    return PushResponse(**report.model_dump())
