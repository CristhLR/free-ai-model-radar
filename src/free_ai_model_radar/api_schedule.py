from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .scheduler import parse_time

def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)

def record_api_success(
    con, provider: str, model_id: str, *,
    expected_change_at: str | None = None,
    valid_until: str | None = None,
    now: datetime | None = None,
    base_hours: float = 72.0,
    max_hours: float = 720.0,
    preflight_hours: float = 24.0,
) -> dict:
    now = _now(now)
    row = con.execute(
        "SELECT stable_runs FROM api_checks WHERE provider=? AND model_id=?",
        (provider, model_id),
    ).fetchone()
    stable = (int(row[0]) if row else 0) + 1

    expected = parse_time(expected_change_at) or parse_time(valid_until)
    if expected and expected > now:
        planned = max(now, expected - timedelta(hours=preflight_hours))
        interval = (planned - now).total_seconds() / 3600
    else:
        interval = min(max_hours, base_hours * (2 ** min(stable - 1, 4)))
        planned = now + timedelta(hours=interval)

    con.execute(
        """INSERT INTO api_checks(provider,model_id,status,last_verified,expected_change_at,valid_until,
        next_check_at,check_interval_hours,stable_runs,consecutive_failures,error)
        VALUES(?,?,?,?,?,?,?,?,?,0,NULL)
        ON CONFLICT(provider,model_id) DO UPDATE SET status='active',last_verified=excluded.last_verified,
        expected_change_at=excluded.expected_change_at,valid_until=excluded.valid_until,
        next_check_at=excluded.next_check_at,check_interval_hours=excluded.check_interval_hours,
        stable_runs=excluded.stable_runs,consecutive_failures=0,error=NULL""",
        (provider,model_id,"active",now.isoformat(),expected_change_at,valid_until,
         planned.isoformat(),interval,stable),
    )
    con.commit()
    return {"provider":provider,"model":model_id,"next_check_at":planned.isoformat(),
            "interval_hours":round(interval,2),"stable_runs":stable}

def record_api_failure(
    con, provider: str, model_id: str, error: str, *,
    now: datetime | None = None,
) -> dict:
    now = _now(now)
    row = con.execute(
        "SELECT consecutive_failures FROM api_checks WHERE provider=? AND model_id=?",
        (provider, model_id),
    ).fetchone()
    failures = (int(row[0]) if row else 0) + 1
    interval = min(12.0, float(2 ** min(failures - 1, 4)))
    planned = now + timedelta(hours=interval)
    con.execute(
        """INSERT INTO api_checks(provider,model_id,status,next_check_at,check_interval_hours,
        stable_runs,consecutive_failures,error)
        VALUES(?,?,?,?,?,0,?,?)
        ON CONFLICT(provider,model_id) DO UPDATE SET status='degraded',
        next_check_at=excluded.next_check_at,check_interval_hours=excluded.check_interval_hours,
        consecutive_failures=excluded.consecutive_failures,error=excluded.error""",
        (provider,model_id,"degraded",planned.isoformat(),interval,failures,error),
    )
    con.commit()
    return {"provider":provider,"model":model_id,"next_check_at":planned.isoformat(),
            "interval_hours":interval,"failures":failures}

def due_api_checks(con, now: datetime | None = None) -> list[dict]:
    now = _now(now).isoformat()
    rows = con.execute(
        """SELECT provider,model_id,status,next_check_at,expected_change_at,valid_until,
        stable_runs,consecutive_failures FROM api_checks
        WHERE next_check_at IS NULL OR next_check_at<=? ORDER BY COALESCE(next_check_at,'')""",
        (now,),
    ).fetchall()
    return [
        {"provider":r[0],"model":r[1],"status":r[2],"next_check_at":r[3],
         "expected_change_at":r[4],"valid_until":r[5],
         "stable_runs":r[6],"failures":r[7]} for r in rows
    ]
