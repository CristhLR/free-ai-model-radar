from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class CandidateModel:
    provider: str
    model_id: str
    endpoint: str
    source_url: str
    free_type: str = "verified_zero_price"
    evidence: str = "official_api"
    openai_compatible: bool = True
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model_id}"
