"""Conversation transcript model + rendering/serialization.

A ``Conversation`` is an ordered list of ``Turn`` (patient/advisor, interleaved). Advisor turns are
numbered 1..T **including question-only turns** — the judge refers to these numbers for ToD, and
question-first advisors are numbered, not skipped (this is what makes the rubric's K=2 commitment bound well-defined). Each model-generated turn carries
its per-call usage (tokens + cost + reasoning_tokens), finish_reason, and routing metadata so the output layer
can do cost logging + reproducibility from the saved record.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Turn:
    speaker: str                              # "patient" | "advisor"
    text: str
    advisor_response_number: Optional[int] = None  # 1..T for advisor turns; None for patient turns
    runner_authored: bool = False            # True only for the runner-authored opener P1
    model: Optional[str] = None              # requested slug
    finish_reason: Optional[str] = None
    truncated: bool = False
    usage: Optional[dict] = None             # {prompt_tokens, completion_tokens, cost, reasoning_tokens, cached_tokens, cache_discount}
    generation_id: Optional[str] = None
    served_model: Optional[str] = None
    provider: Optional[str] = None
    cached: Optional[bool] = None


@dataclass
class Conversation:
    conversation_id: str
    vignette_id: str
    condition_id: int                        # barrier family id (0=control)
    condition_name: str                      # family name — metadata only, NEVER shown to the advisor
    advisor_provider: str
    advisor_model: str
    replicate: int
    seed: int
    turns: list                              # list[Turn]
    metadata: dict = field(default_factory=dict)
    judgment: Optional[dict] = None          # set by the judge harness (tup/judge/judge.py) (Judgment.as_record())

    def advisor_turns(self) -> list:
        return [t for t in self.turns if t.speaker == "advisor"]

    def num_advisor_responses(self) -> int:
        return len(self.advisor_turns())

    def total_cost(self) -> float:
        return sum((t.usage or {}).get("cost") or 0.0 for t in self.turns)

    def missing_cost_turns(self) -> int:
        """Turns that hit the API (usage present, not cached) but returned no cost. When this is > 0,
        ``total_cost()`` is a LOWER BOUND — cost reporting must report the two together."""
        return sum(
            1
            for t in self.turns
            if t.usage is not None and t.usage.get("cost") is None and not t.cached
        )

    def render_for_judge(self) -> str:
        return render_for_judge(self.turns)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_record(cls, record: dict) -> "Conversation":
        """Rebuild a Conversation from a persisted record (tup/output/persist.py) (inverse of ``to_dict``).

        Used by the re-judge path, which must preserve conversation identity (turns, seed, metadata)
        exactly while replacing only the judgment. Unknown keys are ignored so records written by a
        newer schema still load."""
        turn_fields = {f.name for f in dataclasses.fields(Turn)}
        turns = [
            Turn(**{k: v for k, v in t.items() if k in turn_fields}) for t in record.get("turns", [])
        ]
        conv_fields = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in record.items() if k in conv_fields and k != "turns"}
        return cls(turns=turns, **kwargs)


def render_for_judge(turns: list) -> str:
    """Render the transcript for the judge's <<CONVERSATION_TRANSCRIPT>> slot.

    Advisor turns are labeled with their response number so the judge can anchor ToD /
    degraded_turn_quote to the same numbering (the judge prompt uses transcript labels if present).
    """
    lines = []
    for t in turns:
        if t.speaker == "advisor":
            lines.append(f"Advisor (response {t.advisor_response_number}): {t.text}")
        else:
            lines.append(f"Patient: {t.text}")
    return "\n\n".join(lines)

