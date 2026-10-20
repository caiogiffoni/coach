"""Builders for workout-library test payloads (plain dicts on the wire)."""


def step(
    step_type: str = "run",
    end: dict | None = None,
    target: dict | None = None,
    notes: str = "",
) -> dict:
    return {
        "kind": "step",
        "step_type": step_type,
        "end": end or {"type": "time", "seconds": 600},
        "target": target or {"type": "none"},
        "notes": notes,
    }


def repeat(iterations: int, *steps: dict) -> dict:
    return {"kind": "repeat", "iterations": iterations, "steps": list(steps)}


def pace(fast: int, slow: int) -> dict:
    return {"type": "pace_range", "fast_sec_per_km": fast, "slow_sec_per_km": slow}


def workout(name: str = "Intervals", *items: dict) -> dict:
    return {
        "name": name,
        "description": "Track session",
        "steps": list(items) or [step("warmup")],
    }


def interval_workout(name: str = "Intervals") -> dict:
    """10' warmup, 4 x (400 m @ 4:00-4:20/km + 90 s recover), lap-button cooldown."""
    return workout(
        name,
        step("warmup", notes="easy"),
        repeat(
            4,
            step("run", {"type": "distance", "meters": 400}, pace(240, 260)),
            step(
                "recover",
                {"type": "time", "seconds": 90},
                {"type": "hr_zone", "zone": 1},
            ),
        ),
        step("cooldown", {"type": "lap_button"}),
    )
