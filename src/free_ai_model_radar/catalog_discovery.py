from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from urllib.request import Request, urlopen

from .candidate_discovery import FREE_LLM_HUB_URL, import_free_llm_hub
from .config import USER_AGENT

CATALOGS = {
    "free-llm-api-hub": FREE_LLM_HUB_URL,
    "free-ai-api-tiers": "https://raw.githubusercontent.com/vhmns14/free-ai-api-tiers/main/data/providers.json",
    "free-llm-services": "https://raw.githubusercontent.com/Simao-Lopes/free-llm-services/main/providers.json",
    "china-free-llm": "https://raw.githubusercontent.com/DaBinBinah/free-LLM/main/data/providers.json",
    "awesome-freellm-apis": "https://raw.githubusercontent.com/open-free-llm-api/awesome-freellm-apis/main/README.md",
}

ALIASES = {
    "google ai studio gemini": "google-gemini",
    "google ai studio": "google-gemini",
    "google gemini": "google-gemini",
    "google gemini api ai studio": "google-gemini",
    "z ai zhipu ai": "zai-glm",
    "zhipu ai glm": "zai-glm",
    "zhipu ai": "zai-glm",
    "bigmodel": "zai-glm",
    "openrouter": "openrouter",
    "groq": "groq",
    "cloudflare workers ai": "cloudflare-workers-ai",
    "ollama cloud": "ollama-cloud",
    "sambanova": "sambanova",
    "nvidia nim": "nvidia-nim",
    "modelscope": "modelscope",
    "siliconflow": "siliconflow",
    "hugging face": "huggingface",
    "hugging face inference api": "huggingface",
    "mistral ai": "mistral",
    "ai studio aion labs": "aion-labs",
    "alibaba cloud model studio": "alibaba-model-studio",
    "aliyun bailian": "alibaba-model-studio",
    "grok": "xai",
    "xai grok": "xai",
    "cohere": "cohere",
    "cerebras": "cerebras",
}


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"})
    with urlopen(req, timeout=20) as response:
        return response.read()


def _key(name: str) -> str:
    value = unescape(name or "").lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return re.sub(r"\s+", " ", value)


def _slug(name: str, existing: dict[str, str]) -> str:
    key = _key(name)
    if key in ALIASES:
        return ALIASES[key]
    if key in existing:
        return existing[key]
    return re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "unknown-provider"


def _bool(value):
    if value is None or value == "partial":
        return None
    return 1 if bool(value) else 0


def _free_type(value: str | None) -> str | None:
    mapping = {
        "permanent_free": "perpetual",
        "permanent_free_and_trial": "perpetual",
        "free_tier": "renewing-quota",
    }
    return mapping.get(value or "", value)


def _parse_freellm_readme(text: str) -> list[dict]:
    match = re.search(r"<!-- BEGIN_QUICK_REF -->(.*?)<!-- END_QUICK_REF -->", text, re.S)
    if not match:
        return []
    rows = []
    for line in match.group(1).splitlines():
        if not line.startswith("|") or line.startswith("|---") or "| Provider |" in line:
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 4:
            continue
        name, base_url, key_cell, card = cols[:4]
        base_url = base_url.strip("`") or None
        href = re.search(r'href="([^"]*)"', key_cell)
        rows.append({
            "name": name,
            "api_base_url": base_url,
            "registration_url": href.group(1) if href and href.group(1) else None,
            "card_required": False if card.lower() == "no" else None,
            "catalog_note": card,
        })
    return rows


def _records(source_id: str, raw: bytes) -> list[dict]:
    if source_id == "awesome-freellm-apis":
        return _parse_freellm_readme(raw.decode("utf-8", errors="replace"))
    payload = json.loads(raw)
    items = payload.get("providers", [])
    out = []
    for p in items:
        if source_id == "free-llm-api-hub":
            out.append({
                "source_provider_id": p.get("slug"), "name": p.get("name"),
                "docs_url": p.get("docs_url"), "api_base_url": p.get("openai_base_url"),
                "env_key": p.get("env_key"), "free_type": p.get("free_type"),
                "free_tier": p.get("free_tier"), "phone_required": p.get("phone_required"),
                "card_required": p.get("card_required"), "openai_compatible": p.get("openai_compatible"),
                "last_verified": p.get("last_verified"), "verified": p.get("verified"),
            })
        elif source_id == "free-ai-api-tiers":
            out.append({
                "name": p.get("name"), "docs_url": p.get("url"), "free_tier": p.get("free_tier"),
                "card_required": p.get("credit_card"), "last_verified": p.get("last_verified"),
                "catalog_note": p.get("promo"),
            })
        elif source_id == "free-llm-services":
            out.append({
                "name": p.get("name"), "registration_url": p.get("site"),
                "free_tier": p.get("free_tier_desc"), "card_required": p.get("credit_card_required"),
                "openai_compatible": p.get("openai_compatible"), "last_verified": p.get("last_checked"),
                "models_free": p.get("models"), "catalog_note": p.get("status"),
            })
        elif source_id == "china-free-llm":
            auth = p.get("auth_requirements") or {}
            out.append({
                "source_provider_id": p.get("id"), "name": p.get("name"),
                "docs_url": p.get("api_doc_url"), "registration_url": p.get("console_url"),
                "api_base_url": p.get("base_url"), "free_type": _free_type(p.get("free_tier_type")),
                "free_tier": p.get("free_tier_desc"), "phone_required": auth.get("phone_required"),
                "card_required": auth.get("credit_card_required"),
                "openai_compatible": p.get("openai_compatible"), "last_verified": p.get("last_verified"),
                "catalog_note": p.get("note"),
            })
    return out


def _merge_candidate(con, source_id: str, source_url: str, record: dict, existing: dict[str, str], now: str) -> str:
    name = record.get("name") or record.get("source_provider_id") or "Unknown"
    slug = _slug(record.get("source_provider_id") or name, existing)
    row = con.execute(
        "SELECT docs_url,registration_url,api_base_url,env_key,free_type,free_tier,phone_required,card_required,openai_compatible,metadata_json FROM provider_candidates WHERE slug=?",
        (slug,),
    ).fetchone()
    if row is None:
        con.execute(
            """INSERT INTO provider_candidates(slug,name,status,source_url,docs_url,registration_url,api_base_url,env_key,free_type,free_tier,phone_required,card_required,openai_compatible,verified_by_source,source_last_verified,evidence_level,first_seen,last_seen,metadata_json)
            VALUES(?,?,'discovered',?,?,?,?,?,?,?,?,?,?,0,?,'community',?,?,?)""",
            (slug,name,source_url,record.get("docs_url"),record.get("registration_url"),record.get("api_base_url"),record.get("env_key"),record.get("free_type"),record.get("free_tier"),_bool(record.get("phone_required")),_bool(record.get("card_required")),_bool(record.get("openai_compatible")),record.get("last_verified"),now,now,"{}"),
        )
        row = con.execute(
            "SELECT docs_url,registration_url,api_base_url,env_key,free_type,free_tier,phone_required,card_required,openai_compatible,metadata_json FROM provider_candidates WHERE slug=?",
            (slug,),
        ).fetchone()
        existing[_key(name)] = slug
    fields = ["docs_url","registration_url","api_base_url","env_key","free_type","free_tier","phone_required","card_required","openai_compatible"]
    values = dict(zip(fields, row[:9]))
    conflicts = []
    updates = {}
    for field in fields:
        incoming = record.get(field)
        if field in {"phone_required","card_required","openai_compatible"}:
            incoming = _bool(incoming)
        if incoming is None or incoming == "":
            continue
        if values[field] is None or values[field] == "":
            updates[field] = incoming
        elif values[field] != incoming and field in {"api_base_url","phone_required","card_required","openai_compatible"}:
            conflicts.append({"source": source_id, "field": field, "candidate": values[field], "reported": incoming})
    metadata = json.loads(row[9] or "{}")
    sources = set(metadata.get("catalog_sources", [])); sources.add(source_id)
    metadata["catalog_sources"] = sorted(sources)
    metadata["catalog_source_count"] = len(sources)
    if conflicts:
        known = metadata.get("catalog_conflicts", [])
        for c in conflicts:
            if c not in known: known.append(c)
        metadata["catalog_conflicts"] = known[-30:]
    if record.get("models_free"):
        metadata.setdefault("models_free_by_catalog", {})[source_id] = record.get("models_free")
    sets = [f"{k}=?" for k in updates]
    params = list(updates.values())
    sets += ["last_seen=?", "metadata_json=?"]
    params += [now, json.dumps(metadata, ensure_ascii=False, sort_keys=True), slug]
    con.execute(f"UPDATE provider_candidates SET {', '.join(sets)} WHERE slug=?", params)
    return slug


def import_all_catalogs(con) -> dict:
    primary = import_free_llm_hub(con)
    now = datetime.now(timezone.utc).isoformat()
    existing = {_key(name): slug for slug, name in con.execute("SELECT slug,name FROM provider_candidates")}
    results = []
    for source_id, source_url in CATALOGS.items():
        raw = _fetch(source_url)
        records = _records(source_id, raw)
        slugs = set()
        for record in records:
            slug = _merge_candidate(con, source_id, source_url, record, existing, now)
            source_provider_id = str(record.get("source_provider_id") or _key(record.get("name") or slug))
            con.execute(
                """INSERT INTO provider_catalog_evidence(source_id,source_provider_id,provider_slug,provider_name,source_url,observed_at,payload_json)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,source_provider_id) DO UPDATE SET provider_slug=excluded.provider_slug,provider_name=excluded.provider_name,source_url=excluded.source_url,observed_at=excluded.observed_at,payload_json=excluded.payload_json""",
                (source_id,source_provider_id,slug,record.get("name") or slug,source_url,now,json.dumps(record,ensure_ascii=False,sort_keys=True)),
            )
            slugs.add(slug)
        results.append({"source": source_id, "records": len(records), "unique_providers": len(slugs)})
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM provider_candidates").fetchone()[0]
    conflicts = con.execute("SELECT COUNT(*) FROM provider_candidates WHERE metadata_json LIKE '%catalog_conflicts%'").fetchone()[0]
    return {"primary": primary, "catalogs": results, "provider_candidates": total, "providers_with_conflicts": conflicts}
