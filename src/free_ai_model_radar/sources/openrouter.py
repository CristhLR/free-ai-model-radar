from __future__ import annotations

import json
from urllib.request import Request, urlopen
from ..config import USER_AGENT
from ..domain import CandidateModel

URL = "https://openrouter.ai/api/v1/models"

class OpenRouterSource:
    name = "openrouter"

    @staticmethod
    def parse(payload: dict) -> list[CandidateModel]:
        out: list[CandidateModel] = []
        for row in payload.get("data", []):
            pricing = row.get("pricing") or {}
            if str(pricing.get("prompt")) != "0" or str(pricing.get("completion")) != "0":
                continue
            out.append(CandidateModel(
                provider="openrouter", model_id=row["id"], endpoint="https://openrouter.ai/api/v1",
                source_url=URL, metadata={"context_length": row.get("context_length"), "name": row.get("name")}
            ))
        return out

    def fetch(self) -> list[CandidateModel]:
        req = Request(URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urlopen(req, timeout=20) as response:
            return self.parse(json.load(response))
