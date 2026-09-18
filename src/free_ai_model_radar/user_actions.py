from __future__ import annotations

import json
from datetime import datetime, timezone

def build_registration_actions(con) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    created = 0
    rows = con.execute(
        """SELECT slug,name,docs_url,registration_url,env_key,phone_required,
        card_required,api_base_url,status FROM provider_candidates"""
    ).fetchall()

    for slug, name, docs_url, registration_url, env_key, phone, card, api_base, status in rows:
        action_url = registration_url or docs_url

        if env_key:
            created += _insert_action(
                con, slug, "register_account", action_url,
                f"Create or sign in to the {name} account. Use the official page, then return to the radar.",
                now,
            )
            if phone:
                created += _insert_action(
                    con, slug, "phone_verification", action_url,
                    f"{name} reports phone verification as required. Complete it manually if requested.",
                    now,
                )
            if card:
                created += _insert_action(
                    con, slug, "card_required", action_url,
                    f"{name} reports a payment method/card requirement. Review this manually before proceeding.",
                    now,
                )
            created += _insert_action(
                con, slug, "create_api_key", action_url,
                f"Create an API key for {name}. Do not paste the key into chat; store it in the local secret/env setup.",
                now,
            )
            con.execute(
                "UPDATE provider_candidates SET status='account_required' WHERE slug=? AND status='discovered'",
                (slug,),
            )
        elif api_base:
            con.execute(
                "UPDATE provider_candidates SET status='verification_required' WHERE slug=? AND status='discovered'",
                (slug,),
            )

    con.commit()
    return {"created_actions": created, "providers_seen": len(rows)}

def _insert_action(con, slug: str, action_type: str, url: str | None, message: str, now: str) -> int:
    before = con.total_changes
    con.execute(
        """INSERT OR IGNORE INTO user_actions(
        provider_slug,action_type,status,action_url,message,created_at)
        VALUES(?,?,'pending',?,?,?)""",
        (slug, action_type, url, message, now),
    )
    return 1 if con.total_changes > before else 0

def list_pending_actions(con, provider: str | None = None) -> list[dict]:
    sql = """SELECT a.id,a.provider_slug,p.name,a.action_type,a.action_url,a.message,
    p.free_type,p.free_tier,p.phone_required,p.card_required,p.openai_compatible
    FROM user_actions a JOIN provider_candidates p ON p.slug=a.provider_slug
    WHERE a.status='pending'"""
    params: tuple = ()
    if provider:
        sql += " AND a.provider_slug=?"
        params = (provider,)
    sql += """ ORDER BY
    CASE a.action_type
      WHEN 'register_account' THEN 1
      WHEN 'phone_verification' THEN 2
      WHEN 'card_required' THEN 3
      WHEN 'create_api_key' THEN 4
      ELSE 9 END,
    p.name"""
    rows = con.execute(sql, params).fetchall()
    return [
        {
            "id": r[0], "provider": r[1], "name": r[2], "action": r[3],
            "url": r[4], "message": r[5], "free_type": r[6], "free_tier": r[7],
            "phone_required": None if r[8] is None else bool(r[8]),
            "card_required": None if r[9] is None else bool(r[9]),
            "openai_compatible": None if r[10] is None else bool(r[10]),
        }
        for r in rows
    ]

def complete_action(con, action_id: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    row = con.execute(
        "SELECT provider_slug,action_type FROM user_actions WHERE id=? AND status='pending'",
        (action_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"pending action not found: {action_id}")
    con.execute(
        "UPDATE user_actions SET status='completed',completed_at=? WHERE id=?",
        (now, action_id),
    )
    con.commit()
    return {"id": action_id, "provider": row[0], "action": row[1], "status": "completed"}

def _priority_score(row: tuple) -> int:
    (
        free_type, verified, openai_compatible, phone_required, card_required,
        commercial_ok, expires, metadata_json,
    ) = row
    score = 0
    if verified:
        score += 25
    if openai_compatible:
        score += 20
    score += {
        "perpetual": 35,
        "renewing-quota": 32,
        "recurring-credit": 24,
        "ongoing": 20,
        "trial-credit": 6,
    }.get(free_type or "", 10)
    if phone_required:
        score -= 6
    if card_required:
        score -= 30
    if commercial_ok is True or commercial_ok == 1:
        score += 5
    if commercial_ok is False or commercial_ok == 0:
        score -= 3
    if expires:
        score -= 5
    try:
        metadata = json.loads(metadata_json or "{}")
    except Exception:
        metadata = {}
    if metadata.get("models_free"):
        score += 10
    return score

def registration_plan(con, limit: int = 10) -> list[dict]:
    providers = con.execute(
        """SELECT slug,name,free_type,verified_by_source,openai_compatible,
        phone_required,card_required,commercial_ok,expires,metadata_json,
        registration_url,docs_url,free_tier,status
        FROM provider_candidates"""
    ).fetchall()

    ranked = []
    for p in providers:
        slug, name = p[0], p[1]
        score = _priority_score((p[2],p[3],p[4],p[5],p[6],p[7],p[8],p[9]))
        next_action = con.execute(
            """SELECT id,action_type,action_url,message FROM user_actions
            WHERE provider_slug=? AND status='pending'
            ORDER BY CASE action_type
              WHEN 'register_account' THEN 1
              WHEN 'phone_verification' THEN 2
              WHEN 'card_required' THEN 3
              WHEN 'create_api_key' THEN 4
              ELSE 9 END LIMIT 1""",
            (slug,),
        ).fetchone()
        if not next_action:
            continue
        ranked.append({
            "provider": slug,
            "name": name,
            "score": score,
            "free_type": p[2],
            "phone_required": None if p[5] is None else bool(p[5]),
            "card_required": None if p[6] is None else bool(p[6]),
            "openai_compatible": None if p[4] is None else bool(p[4]),
            "free_tier": p[12],
            "status": p[13],
            "next_action_id": next_action[0],
            "next_action": next_action[1],
            "url": next_action[2] or p[10] or p[11],
            "message": next_action[3],
        })
    ranked.sort(key=lambda item: (-item["score"], item["name"].lower()))
    return ranked[:max(1, limit)]
