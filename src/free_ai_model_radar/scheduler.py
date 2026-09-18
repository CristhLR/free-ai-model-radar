from __future__ import annotations

from datetime import datetime, timedelta, timezone

DEFAULT_CADENCE = {
    "release": (12.0, 72.0),
    "changelog": (6.0, 72.0),
    "models-api": (6.0, 48.0),
    "models-doc": (12.0, 168.0),
    "free-catalog": (12.0, 72.0),
    "pricing": (24.0, 336.0),
    "rate-limits": (24.0, 336.0),
    "deprecations": (12.0, 168.0),
}
DEFAULT_FALLBACK = (24.0, 168.0)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def cadence_for(source: dict) -> tuple[float, float]:
    base, maximum = DEFAULT_CADENCE.get(source.get("kind"), DEFAULT_FALLBACK)
    return float(source.get("base_interval_hours", base)), float(source.get("max_interval_hours", maximum))

def next_check_time(
    source: dict,
    stable_runs: int,
    *,
    changed: bool,
    failed: bool = False,
    now: datetime | None = None,
) -> tuple[datetime, float]:
    now = now or utcnow()
    base, maximum = cadence_for(source)

    if failed:
        interval = min(base, max(1.0, 2.0 ** min(stable_runs, 3)))
    elif changed:
        interval = base
    else:
        interval = min(maximum, base * (2 ** min(stable_runs, 5)))

    planned = now + timedelta(hours=interval)
    expected = parse_time(source.get("expected_change_at"))
    if expected and expected > now:
        lead = timedelta(hours=float(source.get("preflight_hours", 24)))
        preflight = max(now, expected - lead)
        if source.get("hold_until_expected_change", False):
            planned = preflight
            interval = max(0.0, (planned - now).total_seconds() / 3600)
        elif preflight < planned:
            planned = preflight
            interval = max(0.0, (planned - now).total_seconds() / 3600)

    return planned, interval

def is_due(next_check_at: str | None, now: datetime | None = None) -> bool:
    due = parse_time(next_check_at)
    return due is None or due <= (now or utcnow())
