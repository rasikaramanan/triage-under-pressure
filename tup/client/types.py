"""Shared dataclasses for the TUP client layer.

Plain frozen dataclasses keep the layer dependency-free and trivially serializable for the
response cache and the JSONL persister.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Sampling:
    """Generation parameters for one role."""

    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class Config:
    """Parsed ``config/models.yaml``."""

    providers: dict[str, str]          # provider family -> model slug
    advisors: list[str]                # advisor provider keys (the models under test)
    patient: str                       # patient provider key
    judge_panel: int                   # judge panel size (the run of record: 3)
    sampling: dict[str, Sampling]      # role -> Sampling  (advisor / patient / judge)
    seed: int                          # base RNG seed; the runner derives distinct per-conversation seeds from it
                       # (tup/orchestration/runner.py:conversation_seed)
    patient_model: Optional[str] = None       # per-role slug override (the patient runs its own slug)
    provider_pins: Optional[dict] = None      # slug -> [OpenRouter provider names] routing pin
    guard_model: Optional[str] = None         # patient role-compliance guard classifier slug; None => guard off


@dataclass(frozen=True)
class Usage:
    """Token + cost accounting from a single OpenRouter call."""

    prompt_tokens: int
    completion_tokens: int
    cost: Optional[float]              # USD, from OpenRouter's usage.cost (may be None)
    reasoning_tokens: Optional[int] = None  # usage.completion_tokens_details.reasoning_tokens
    cached_tokens: Optional[int] = None     # usage.prompt_tokens_details.cached_tokens — provider
                                            # prompt-cache reads (None = provider didn't report)
    cache_discount: Optional[float] = None  # OpenRouter usage.cache_discount (USD credited), if reported



@dataclass(frozen=True)
class ClientResponse:
    """The result of one ``complete()`` call."""

    content: str
    model: str
    role: str
    finish_reason: Optional[str]       # "stop" | "length" | ...  ("length" => truncated)
    usage: Optional[Usage]
    cached: bool = False
    generation_id: Optional[str] = None   # OpenRouter generation id (resp.id) — reproducibility
    served_model: Optional[str] = None    # model string OpenRouter actually served (resp.model)
    provider: Optional[str] = None        # upstream provider OpenRouter routed to, if reported

    @property
    def truncated(self) -> bool:
        """True if generation stopped at the token cap (watch reasoning models)."""
        return self.finish_reason == "length"
