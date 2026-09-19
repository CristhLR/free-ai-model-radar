from __future__ import annotations

import html
import os
import secrets
import subprocess
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
    "cloudflare-workers-ai": "https://dash.cloudflare.com/profile/api-tokens",
    "cartesia": "https://play.cartesia.ai/dashboard",
    "elevenlabs": "https://elevenlabs.io/app/settings/api-keys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "siliconflow": "https://cloud.siliconflow.com/account/ak",
    "nvidia-nim": "https://build.nvidia.com/settings/api-keys",
}


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
        cards.append(f'''<article class="card {cls}">
<h3>{html.escape(p["name"])}</h3>
<div class="meta">{html.escape(p["free_type"])}{openai} · <b>{state}</b></div>
<div class="tier">{tier}</div>
<a class="open" href="{url}" target="_blank" rel="noopener">1. Abrir página de API key ↗</a>
<form method="post" action="/save">
<input type="hidden" name="token" value="{token}">
<input type="hidden" name="slug" value="{html.escape(p["slug"], quote=True)}">
<label>2. Pega la key aquí</label>
<input class="key" type="password" name="key" autocomplete="off" spellcheck="false" required>
<button type="submit">Guardar localmente</button>
</form></article>''')
    msg = f'<div class="message">{html.escape(message)}</div>' if message else ""
    return f'''<!doctype html><meta charset="utf-8"><title>Free AI Radar — Keys</title>
<style>body{{font-family:system-ui,Segoe UI,Arial;max-width:1050px;margin:28px auto;padding:0 18px;background:#0f1115;color:#eee}}h1{{margin-bottom:4px}}.sub,.meta{{color:#aaa}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;margin-top:22px}}.card{{background:#181b21;border:1px solid #333;border-radius:12px;padding:15px}}.card.saved{{border-color:#2e704f}}.tier{{font-size:13px;margin:8px 0;min-height:36px}}.open,button{{display:inline-block;background:#2d6cdf;color:white;border:0;text-decoration:none;padding:8px 11px;border-radius:8px;cursor:pointer}}form{{margin-top:12px}}label{{display:block;font-size:13px;margin-bottom:5px}}.key{{box-sizing:border-box;width:100%;padding:9px;background:#101218;color:#fff;border:1px solid #444;border-radius:8px;margin-bottom:8px}}.message{{background:#173b29;border:1px solid #2e704f;padding:10px;border-radius:8px;margin-top:15px}}</style>
<h1>Free AI Radar — API keys</h1><div class="sub">Las keys se envían solo a 127.0.0.1 y se guardan en .env.local, que Git ignora. El servidor no imprime ni devuelve el valor de ninguna key.</div>{msg}<div class="grid">{''.join(cards)}</div>'''


def run(port: int = PORT) -> None:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

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
            provider = next((p for p in _providers() if p["slug"] == slug), None)
            if not provider or len(key) < 8:
                self.send_error(400)
                return
            _save_secret(provider["env_key"], key)
            _mark_saved(slug)
            sync = restart_freellmapi()
            if sync.get("ok"):
                message = (
                    f"{provider['name']}: key guardada y FreeLLMAPI actualizado "
                    f"con {sync.get('count', 0)} proveedor(es)."
                )
            else:
                message = (
                    f"{provider['name']}: key guardada. FreeLLMAPI no pudo reiniciarse: "
                    f"{sync.get('error', 'error desconocido')}"
                )
            body = _page(token, message).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    url = f"http://{HOST}:{port}/?token={token}"
    print("KEY_INTAKE_READY", url, flush=True)
    webbrowser.open(url)
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    run()
