"""Workout library tables.

``LibraryWorkout`` rows hold user-built running workouts independent of the
weekly plan; ``steps`` is the builder's ``WorkoutItem`` list serialized as JSON
(see ``schemas.py``). Each Garmin push is recorded in ``LibraryWorkoutPush``.
Names avoid ``WorkoutTemplate``, which is reserved for a future chatbot feature.
"""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def utc_now() -> datetime:
    """Current UTC time, used as the column default for timestamps.

    Example:
        >>> utc_now().tzinfo is not None
        True
    """
    return datetime.now(timezone.utc)


class LibraryWorkout(Base):
    __tablename__ = "library_workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(1000), default="")
    steps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    pushes: Mapped[list["LibraryWorkoutPush"]] = relationship(
        back_populates="library_workout", cascade="all, delete-orphan"
    )


class LibraryWorkoutPush(Base):
    __tablename__ = "library_workout_pushes"

    id: Mapped[int] = mapped_column(primary_key=True)
    library_workout_id: Mapped[int] = mapped_column(
        ForeignKey("library_workouts.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    garmin_workout_id: Mapped[str] = mapped_column(String(32))
    pushed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    library_workout: Mapped[LibraryWorkout] = relationship(back_populates="pushes")
