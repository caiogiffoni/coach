"""
Stored week plans (PLAN.md build-order step 5).

One WeekPlan per user per week (unique constraint); regenerating a week
replaces the existing DRAFT row and its workouts in one transaction (see
router). Workout steps are stored as JSON — the schema is the validator's
WorkoutStep, serialized.
"""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class WeekPlan(Base):
    __tablename__ = "week_plans"
    __table_args__ = (UniqueConstraint("user_id", "week_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date)  # Monday of the ISO week
    goal_mode: Mapped[str] = mapped_column(String(10))  # snapshot at generation
    notes: Mapped[str] = mapped_column(String, default="")  # notes-to-coach
    source: Mapped[str] = mapped_column(String(10))  # llm | fallback
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft|approved|pushed
    validation_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    workouts: Mapped[list["Workout"]] = relationship(
        back_populates="week_plan",
        cascade="all, delete-orphan",
        order_by="Workout.date",
    )


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_plan_id: Mapped[int] = mapped_column(
        ForeignKey("week_plans.id"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(200))
    sport: Mapped[str] = mapped_column(String(20), default="running")
    duration_min: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String, default="")
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    slot_type: Mapped[str] = mapped_column(String(10))  # aerobic|quality|recovery|long
    status: Mapped[str] = mapped_column(String(10), default="planned")

    week_plan: Mapped[WeekPlan] = relationship(back_populates="workouts")
