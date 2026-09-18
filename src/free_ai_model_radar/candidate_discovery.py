from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from .config import USER_AGENT

FREE_LLM_HUB_URL = (
    "https://raw.githubusercontent.com/pacocartones/"
    "free-llm-api-hub/main/data/providers.json"
)

def _bool(value):
    if value is None:
        return None
    return 1 if bool(value) else 0

def fetch_free_llm_hub() -> dict:
    req = Request(
        FREE_LLM_HUB_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urlopen(req, timeout=20) as response:
        return json.load(response)

def import_free_llm_hub(con) -> dict:
    payload = fetch_free_llm_hub()
    now = datetime.now(timezone.utc).isoformat()
    added = updated = 0

    for provider in payload.get("providers", []):
        slug = provider["slug"]
        existed = con.execute(
            "SELECT 1 FROM provider_candidates WHERE slug=?", (slug,)
        ).fetchone() is not None
        metadata = {
            "category": provider.get("category"),
            "rate_limits": provider.get("rate_limits"),
            "best_for": provider.get("best_for"),
            "modalities": provider.get("modalities"),
            "models_free": provider.get("models_free"),
        }
        con.execute(
            """INSERT INTO provider_candidates(
            slug,name,status,source_url,docs_url,api_base_url,env_key,free_type,
            free_tier,expires,phone_required,card_required,commercial_ok,
            openai_compatible,verified_by_source,source_last_verified,evidence_level,
            first_seen,last_seen,notes,metadata_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
            name=excluded.name,source_url=excluded.source_url,docs_url=excluded.docs_url,
            api_base_url=excluded.api_base_url,env_key=excluded.env_key,
            free_type=excluded.free_type,free_tier=excluded.free_tier,
            expires=excluded.expires,phone_required=excluded.phone_required,
            card_required=excluded.card_required,commercial_ok=excluded.commercial_ok,
            openai_compatible=excluded.openai_compatible,
            verified_by_source=excluded.verified_by_source,
            source_last_verified=excluded.source_last_verified,last_seen=excluded.last_seen,
            notes=excluded.notes,metadata_json=excluded.metadata_json""",
            (
                slug, provider["name"], "discovered", FREE_LLM_HUB_URL,
                provider.get("docs_url"), provider.get("openai_base_url"),
                provider.get("env_key"), provider.get("free_type"),
                provider.get("free_tier"), provider.get("expires"),
                _bool(provider.get("phone_required")), _bool(provider.get("card_required")),
                _bool(provider.get("commercial_ok")), _bool(provider.get("openai_compatible")),
                _bool(provider.get("verified")), provider.get("last_verified"),
                "community_verified" if provider.get("verified") else "community",
                now, now, provider.get("notes"),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            ),
        )
        if existed: updated += 1
        else: added += 1

    con.commit()
    return {
        "source": FREE_LLM_HUB_URL,
        "dataset_version": payload.get("version"),
        "providers": len(payload.get("providers", [])),
        "added": added,
        "updated": updated,
    }
