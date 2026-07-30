"""Garmin push bookkeeping (PLAN.md build-order step 7).

Stores the mapping between app-created WeekPlan workouts and the Garmin
Connect workout IDs we uploaded, so re-pushing a week can replace only the
workouts we created and leave everything else alone.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class GarminWorkoutMapping(Base):
    __tablename__ = "garmin_workout_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_plan_id: Mapped[int] = mapped_column(
        ForeignKey("week_plans.id"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    garmin_workout_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
