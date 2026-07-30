from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Profile(Base):
    """One athlete profile per user. See PLAN.md locked decision #11."""

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )

    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold_pace_sec_per_km: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    threshold_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recent_race_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    recent_race_time_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_weekly_volume_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Always manual (never seeded): injury history and goal fields.
    injury_history: Mapped[list[str]] = mapped_column(JSON, default=list)
    goal_mode: Mapped[str] = mapped_column(
        String(10), default="health"
    )  # race | health
    goal_race_distance: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # 5K|10K|HM|MARATHON
    goal_race_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    preferred_days: Mapped[list[int]] = mapped_column(
        JSON, default=list
    )  # weekday ints, 0=Mon..6=Sun
    seeded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
