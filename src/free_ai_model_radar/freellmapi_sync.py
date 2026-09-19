from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

from .config import DB_PATH, ROOT
from .db import connect

FREELLMAPI_DIR = Path.home() / "freellmapi"
SECRET_FILE = ROOT / ".env.local"
PORT = 3001
LOG_FILE = ROOT / "data" / "freellmapi.log"

PLATFORM_MAP = {
    "google-gemini": ("google", "GEMINI_API_KEY"),
    "groq": ("groq", "GROQ_API_KEY"),
    "mistral": ("mistral", "MISTRAL_API_KEY"),
    "modelscope": ("modelscope", "MODELSCOPE_API_KEY"),
    "openrouter": ("openrouter", "OPENROUTER_API_KEY"),
    "ollama-cloud": ("ollama", "OLLAMA_API_KEY"),
    "cloudflare-workers-ai": ("cloudflare", "CLOUDFLARE_API_TOKEN"),
    "cohere": ("cohere", "COHERE_API_KEY"),
    "zai-glm": ("zhipu", "ZAI_API_KEY"),
    "huggingface": ("huggingface", "HF_TOKEN"),
    "siliconflow": ("siliconflow", "SILICONFLOW_API_KEY"),
    "nvidia-nim": ("nvidia", "NVIDIA_API_KEY"),
    "navyai": ("navy", "NAVY_API_KEY"),
    "requesty": ("requesty", "REQUESTY_API_KEY"),
    "aion-labs": ("aion", "AION_API_KEY"),
    "aihorde": ("aihorde", "AIHORDE_API_KEY"),
    "bazaarlink": ("bazaarlink", "BAZAARLINK_API_KEY"),
}

SAFE_FREE_TYPES = {
    "perpetual", "renewing-quota", "recurring-credit", "ongoing",
    "trial-credit", "free_quota_trial", "quota_with_expiry",
    "new_user_trial", "limited_time_free", "free_points",
}
def _load_env() -> dict[str, str]:
    data: dict[str, str] = {}
    if not SECRET_FILE.exists():
        return data
    for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def build_config() -> tuple[dict, list[str]]:
    secrets = _load_env()
    keys = [{"platform": "kilo", "label": "radar-anonymous"}]
    enabled = ["kilo"]
    with connect(DB_PATH) as con:
        for slug, (platform, env_key) in PLATFORM_MAP.items():
            row = con.execute(
                "SELECT free_type,card_required,status FROM provider_candidates WHERE slug=?",
                (slug,),
            ).fetchone()
            if not row:
                continue
            free_type, card_required, status = row
            value = secrets.get(env_key)
            if free_type not in SAFE_FREE_TYPES or card_required == 1:
                continue
            if not value or status != "key_saved":
                continue
            keys.append({"platform": platform, "key": value, "label": "radar"})
            enabled.append(platform)
    return {"keys": keys, "routing": {"strategy": "balanced"}}, enabled
def _listener_pids(port: int = PORT) -> list[int]:
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"], text=True, errors="ignore"
        )
    except Exception:
        return []
    pids: set[int] = set()
    needle = f":{port}"
    for line in output.splitlines():
        if "LISTENING" not in line.upper() or needle not in line:
            continue
        try:
            pids.add(int(line.split()[-1]))
        except (ValueError, IndexError):
            pass
    return sorted(pids)


def _port_open(port: int = PORT) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.7):
            return True
    except OSError:
        return False


def restart_freellmapi(wait_seconds: float = 25.0) -> dict:
    server = FREELLMAPI_DIR / "server" / "dist" / "index.js"
    if not server.exists():
        return {"ok": False, "error": "FreeLLMAPI build not found", "platforms": []}

    config, platforms = build_config()
    for pid in _listener_pids():
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    deadline = time.time() + 4
    while _port_open() and time.time() < deadline:
        time.sleep(0.15)

    env = os.environ.copy()
    env["FREEAPI_CONFIG_JSON"] = json.dumps(
        config, ensure_ascii=False, separators=(",", ":")
    )
    env.pop("FREEAPI_CONFIG_PATH", None)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab", buffering=0)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        ["node", "server/dist/index.js"],
        cwd=str(FREELLMAPI_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )

    end = time.time() + wait_seconds
    while time.time() < end:
        if _port_open():
            return {"ok": True, "platforms": platforms, "count": len(platforms)}
        time.sleep(0.25)
    return {"ok": False, "error": "port 3001 did not open", "platforms": platforms}


if __name__ == "__main__":
    print(json.dumps(restart_freellmapi(), ensure_ascii=False, indent=2))
