from __future__ import annotations

from typing import Protocol
from ..domain import CandidateModel

class Source(Protocol):
    name: str
    def fetch(self) -> list[CandidateModel]: ...
