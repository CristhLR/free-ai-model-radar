from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("RADAR_DB_PATH", DATA_DIR / "radar.db"))
USER_AGENT = "free-ai-model-radar/0.1 (+personal research)"
FREE_ONLY = os.getenv("FREE_ONLY", "true").lower() not in {"0", "false", "no"}
USE_JEV = os.getenv("USE_JEV", "false").lower() in {"1", "true", "yes"}
