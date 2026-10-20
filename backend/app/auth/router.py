from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .rate_limit import LoginRateLimiter, client_ip, get_login_rate_limiter
from .security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str


class UserResponse(BaseModel):
    email: str


class StatusResponse(BaseModel):
    registration_open: bool


@router.get("/status", response_model=StatusResponse)
def auth_status(db: Session = Depends(get_db)) -> StatusResponse:
    """First-run setup: registration is open only while no user exists."""
    user_count = db.scalar(select(func.count()).select_from(User))
    return StatusResponse(registration_open=user_count == 0)


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user_count = db.scalar(select(func.count()).select_from(User))
    if user_count is not None and user_count > 0:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(token=create_token(user.id))


def _raise_if_locked_out(limiter: LoginRateLimiter, ip: str) -> None:
    """Reject the request with 429 + Retry-After when ``ip`` is locked out."""
    retry_after = limiter.retry_after_seconds(ip)
    if retry_after == 0:
        return
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"Too many failed logins from {ip}; retry in {retry_after} s",
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> TokenResponse:
    ip = client_ip(request)
    _raise_if_locked_out(limiter, ip)
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        limiter.record_failure(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    limiter.reset(ip)
    return TokenResponse(token=create_token(user.id))


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(email=user.email)
