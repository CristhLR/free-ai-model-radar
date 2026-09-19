from __future__ import annotations

import html
import os
import secrets
import subprocess
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import DB_PATH, ROOT
from .db import connect
from .freellmapi_sync import PLATFORM_MAP, SAFE_FREE_TYPES, restart_freellmapi

HOST = "127.0.0.1"
PORT = 8765
SECRET_FILE = ROOT / ".env.local"

DIRECT_KEY_URLS = {
    "google-gemini": "https://aistudio.google.com/api-keys",
    "groq": "https://console.groq.com/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "modelscope": "https://modelscope.cn/my/myaccesstoken",
    "openrouter": "https://openrouter.ai/workspaces/default/keys",
    "sambanova": "https://cloud.sambanova.ai/apis",
    "ollama-cloud": "https://ollama.com/settings/keys",
    "cohere": "https://dashboard.cohere.com/api-keys",
    "zai-glm": "https://z.ai/manage-apikey/apikey-list",
    "alibaba-model-studio": "https://modelstudio.console.alibabacloud.com/ap-southeast-1/settings/workspace",
    "cloudflare-workers-ai": "https://dash.cloudflare.com/?to=/:account/workers-ai",
    "cartesia": "https://play.cartesia.ai/dashboard",
    "elevenlabs": "https://elevenlabs.io/app/settings/api-keys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "siliconflow": "https://cloud.siliconflow.com/account/ak",
    "nvidia-nim": "https://build.nvidia.com/settings/api-keys",
    "navyai": "https://api.navy/",
    "requesty": "https://app.requesty.ai/sign-up",
    "aion-labs": "https://www.aionlabs.ai/accounts/signup/",
    "aihorde": "https://aihorde.net/register",
    "bazaarlink": "https://bazaarlink.ai/login",
}

EXTRA_PROVIDER_SEEDS = {
    "navyai": ("NavyAI", "NAVY_API_KEY", "https://api.navy/docs", "https://api.navy/", "https://api.navy/v1", "renewing-quota", "Free plan: 150K tokens/day, 20 RPM; premium models excluded."),
    "requesty": ("Requesty", "REQUESTY_API_KEY", "https://docs.requesty.ai/", "https://app.requesty.ai/sign-up", "https://router.requesty.ai/v1", "renewing-quota", "Free plan: 200 requests/day on free models; no credit card required."),
    "aion-labs": ("Aion Labs", "AION_API_KEY", "https://www.aionlabs.ai/docs/", "https://www.aionlabs.ai/accounts/signup/", "https://api.aionlabs.ai/v1", "renewing-quota", "Free tier: daily allowance, 15 RPM and 20K tokens/day; no card required."),
    "aihorde": ("AI Horde", "AIHORDE_API_KEY", "https://dev.aihorde.net/", "https://aihorde.net/register", "https://oai.aihorde.net/v1", "perpetual", "Volunteer-run free service; registered key gets higher priority than anonymous access."),
    "bazaarlink": ("BazaarLink", "BAZAARLINK_API_KEY", "https://bazaarlink.ai/en/docs", "https://bazaarlink.ai/login", "https://api.bazaarlink.ai/v1", "renewing-quota", "Free tier: 10 RPM and 50 requests/day on currently free models; no card required."),
}


def _ensure_extra_providers() -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect(DB_PATH) as con:
        for slug, (name, env_key, docs_url, registration_url, api_base_url, free_type, free_tier) in EXTRA_PROVIDER_SEEDS.items():
            con.execute("""INSERT INTO provider_candidates(
                slug,name,status,source_url,docs_url,registration_url,api_base_url,env_key,
                free_type,free_tier,phone_required,card_required,commercial_ok,openai_compatible,
                verified_by_source,source_last_verified,evidence_level,first_seen,last_seen,notes,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,status=CASE WHEN provider_candidates.status IN ('key_saved','account_registered') THEN provider_candidates.status ELSE 'account_required' END,
                docs_url=excluded.docs_url,registration_url=excluded.registration_url,
                api_base_url=excluded.api_base_url,env_key=excluded.env_key,free_type=excluded.free_type,
                free_tier=excluded.free_tier,phone_required=0,card_required=0,openai_compatible=1,
                verified_by_source=1,source_last_verified=excluded.source_last_verified,
                evidence_level='official',last_seen=excluded.last_seen""",
                (slug,name,'account_required',docs_url,docs_url,registration_url,api_base_url,env_key,
                 free_type,free_tier,0,0,1,1,1,now,'official',now,now,'Global/Colombia-friendly candidate verified from official source.','{}'))
        con.commit()


def _load_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if not SECRET_FILE.exists():
        return data
    for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value
    return data


def _save_secret(env_key: str, value: str) -> None:
    data = _load_env()
    data[env_key] = value.strip()
    text = "# Local secrets for Free AI Model Radar. Never commit this file.\n"
    text += "\n".join(f"{key}={val}" for key, val in sorted(data.items())) + "\n"
    SECRET_FILE.write_text(text, encoding="utf-8")
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    if os.name == "nt":
        username = os.environ.get("USERNAME")
        if username:
            subprocess.run(
                ["icacls", str(SECRET_FILE), "/inheritance:r", "/grant:r", f"{username}:(R,W)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def _providers() -> list[dict]:
    _ensure_extra_providers()
    saved = _load_env()
    with connect(DB_PATH) as con:
        rows = con.execute(
            """SELECT slug,name,env_key,registration_url,docs_url,free_type,free_tier,
            openai_compatible,status FROM provider_candidates
            WHERE status IN ('account_required','account_registered','key_saved') AND env_key IS NOT NULL
            ORDER BY CASE WHEN openai_compatible=1 THEN 0 ELSE 1 END, name COLLATE NOCASE"""
        ).fetchall()
    return [
        {
            "slug": r[0], "name": r[1], "env_key": r[2],
            "url": DIRECT_KEY_URLS.get(r[0]) or r[3] or r[4],
            "free_type": r[5] or "unknown", "free_tier": r[6] or "",
            "openai": bool(r[7]), "status": r[8], "saved": r[2] in saved,
        }
        for r in rows
        if r[0] in PLATFORM_MAP and r[5] in SAFE_FREE_TYPES
    ]


def _mark_saved(slug: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect(DB_PATH) as con:
        existing = con.execute(
            "SELECT id FROM user_actions WHERE provider_slug=? AND action_type='create_api_key' AND status='completed' LIMIT 1",
            (slug,),
        ).fetchone()
        if not existing:
            con.execute(
                "UPDATE user_actions SET status='completed',completed_at=? WHERE provider_slug=? AND action_type='create_api_key' AND status='pending'",
                (now, slug),
            )
        else:
            con.execute(
                "UPDATE user_actions SET status='cancelled',completed_at=? WHERE provider_slug=? AND action_type='create_api_key' AND status='pending'",
                (now, slug),
            )
        con.execute("UPDATE provider_candidates SET status='key_saved' WHERE slug=?", (slug,))
        con.commit()


def _page(token: str, message: str = "") -> str:
    rows = _providers()
    cards = []
    for p in rows:
        state = "Guardada ✅" if p["saved"] else "Pendiente"
        cls = "saved" if p["saved"] else "pending"
        tier = html.escape(p["free_tier"][:260])
        openai = " · OpenAI-compatible" if p["openai"] else ""
        url = html.escape(p["url"] or "#", quote=True)
        extra = ""
        key_label = "2. Pega la key aquí"
        if p["slug"] == "cloudflare-workers-ai":
            extra = '<label>2. Account ID</label><input class="key" name="account_id" autocomplete="off" spellcheck="false" required>'
            key_label = "3. API Token"
        cards.append(f'''<article class="card {cls}">
<h3>{html.escape(p["name"])}</h3>
<div class="meta">{html.escape(p["free_type"])}{openai} · <b>{state}</b></div>
<div class="tier">{tier}</div>
<a class="open" href="{url}" target="_blank" rel="noopener">1. Abrir página de API key ↗</a>
<form method="post" action="/save">
<input type="hidden" name="token" value="{token}">
<input type="hidden" name="slug" value="{html.escape(p["slug"], quote=True)}">
{extra}
<label>{key_label}</label>
<input class="key" type="password" name="key" autocomplete="off" spellcheck="false" required>
<button type="submit">Guardar localmente</button>
</form></article>''')
    jev_saved = "TYPESAFE_API_KEY" in _load_env()
    jev_state = "Guardada ✅" if jev_saved else "Pendiente"
    jev_cls = "saved" if jev_saved else "pending"
    cards.insert(0, f'''<article class="card {jev_cls}">\n<h3>TypeSafe / Jev (opcional)</h3>\n<div class="meta">Early access / invitación · <b>{jev_state}</b></div>\n<div class="tier">No es necesario para Smart. Si algún día consigues acceso, mejora la decisión entre fast, balanced, smart, verificación o fusion.</div>\n<a class="open" href="https://console.typesafe.ai" target="_blank" rel="noopener">1. Abrir TypeSafe Console ↗</a>\n<form method="post" action="/save">\n<input type="hidden" name="token" value="{token}">\n<input type="hidden" name="slug" value="typesafe-jev">\n<label>2. Pega la API key aquí</label>\n<input class="key" type="password" name="key" autocomplete="off" spellcheck="false" required>\n<button type="submit">Guardar localmente</button>\n</form></article>''')
    msg = f'<div class="message">{html.escape(message)}</div>' if message else ""
    return f'''<!doctype html><meta charset="utf-8"><title>Free AI Radar — Keys</title>
<style>body{{font-family:system-ui,Segoe UI,Arial;max-width:1050px;margin:28px auto;padding:0 18px;background:#0f1115;color:#eee}}h1{{margin-bottom:4px}}.sub,.meta{{color:#aaa}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;margin-top:22px}}.card{{background:#181b21;border:1px solid #333;border-radius:12px;padding:15px}}.card.saved{{border-color:#2e704f}}.tier{{font-size:13px;margin:8px 0;min-height:36px}}.open,button{{display:inline-block;background:#2d6cdf;color:white;border:0;text-decoration:none;padding:8px 11px;border-radius:8px;cursor:pointer}}form{{margin-top:12px}}label{{display:block;font-size:13px;margin-bottom:5px}}.key{{box-sizing:border-box;width:100%;padding:9px;background:#101218;color:#fff;border:1px solid #444;border-radius:8px;margin-bottom:8px}}.message{{background:#173b29;border:1px solid #2e704f;padding:10px;border-radius:8px;margin-top:15px}}</style>
<h1>Free AI Radar — API keys</h1><div class="sub">Las keys se envían solo a 127.0.0.1 y se guardan en .env.local, que Git ignora. El servidor no imprime ni devuelve el valor de ninguna key.</div>{msg}<div class="grid">{''.join(cards)}</div>'''


def run(port: int = PORT) -> None:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def send_panel(self, message: str, status: int = 200):
            body = _page(token, message).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path)
            if path.path != "/":
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(path.query)
            if query.get("token", [""])[0] != token:
                self.send_error(403)
                return
            body = _page(token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/save":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            if form.get("token", [""])[0] != token:
                self.send_error(403)
                return
            slug = form.get("slug", [""])[0]
            key = form.get("key", [""])[0].strip()
            account_id = form.get("account_id", [""])[0].strip()
            if slug == "typesafe-jev":
                if len(key) < 8:
                    self.send_panel("TypeSafe / Jev: la API key parece incompleta.")
                    return
                _save_secret("TYPESAFE_API_KEY", key)
                self.send_panel("TypeSafe / Jev: API key guardada. Smart la usará en la próxima petición.")
                return
            provider = next((p for p in _providers() if p["slug"] == slug), None)
            if not provider:
                self.send_panel("Proveedor no reconocido. Recarga el panel e inténtalo de nuevo.")
                return
            if slug == "cloudflare-workers-ai":
                if len(account_id) < 16:
                    self.send_panel("Cloudflare: falta el Account ID o parece incompleto.")
                    return
                if len(key) < 8:
                    self.send_panel("Cloudflare: falta el API Token o parece incompleto.")
                    return
                key = f"{account_id}:{key}"
            elif len(key) < 8:
                self.send_panel(f"{provider['name']}: la key parece incompleta.")
                return
            _save_secret(provider["env_key"], key)
            _mark_saved(slug)
            threading.Thread(target=restart_freellmapi, daemon=True).start()
            self.send_panel(
                f"{provider['name']}: key guardada localmente. FreeLLMAPI se está actualizando en segundo plano."
            )

    url = f"http://{HOST}:{port}/?token={token}"
    print("KEY_INTAKE_READY", url, flush=True)
    webbrowser.open(url)
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    run()
