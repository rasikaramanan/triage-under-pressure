"""Real-dollar cost accumulation across conversations, INCLUDING the judge call.

``Conversation.total_cost()`` covers only the conversation (patient/advisor) turns; the judge call's
charge lives on ``conv.judgment.judge_usage.cost``. This module sums BOTH and surfaces every way the
total could silently be a LOWER BOUND:

  - ``missing_cost_turns`` — turns that hit the API (usage present, not cached) but returned no
    ``cost`` (OpenRouter occasionally omits it);
  - ``judge_calls_missing_cost`` — conversations whose judge spend is under-counted: a judge call ran
    but returned no cost; OR the conversation completed but no judgment is attached (a judge call was
    expected); OR the judge needed retries, so only the last of several billed attempts is recorded.

When either is > 0 the report's ``is_lower_bound`` flag is set, so a budget cap is never
read off an under-count. The conversation-turn helpers mirror ``Conversation.total_cost`` /
``Conversation.missing_cost_turns`` exactly on a well-formed record (a test pins them together).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Judge statuses whose call completed and must carry usage — a missing cost there is a real gap.
# NOT counted: ``skipped_incomplete`` (never sent), ``panel_incomplete`` (an aggregate; its seats
# are accounted individually), and ``judge_failed`` (the call raised before returning usage —
# its spend is unknowable, the judgment is re-derivable by scripts/rejudge.py, and treating it as
# a gap would let a judge-side failure abort the serial path, which the soft-judge design forbids).
_JUDGE_CALL_STATUSES = ("judged", "unparseable")


def _usage_of(turn) -> dict:
    """The turn's usage as a dict ({} if absent or — on a malformed/foreign record — not a dict)."""
    if not isinstance(turn, dict):
        return {}
    usage = turn.get("usage")
    return usage if isinstance(usage, dict) else {}


def turns_cost(record: dict) -> float:
    """Sum the real ``cost`` over the conversation turns (mirrors ``Conversation.total_cost``).

    On a well-formed record this is exactly ``Conversation.total_cost``; the isinstance guards only add
    graceful degradation on a malformed/hand-edited JSONL that ``load_records`` might surface.
    """
    return sum(_usage_of(t).get("cost") or 0.0 for t in record.get("turns", []))


def missing_cost_turns(record: dict) -> int:
    """Turns that hit the API (usage present, not cached) yet returned no cost.

    Mirrors ``Conversation.missing_cost_turns`` on the persisted record form.
    """
    n = 0
    for t in record.get("turns", []):
        if not isinstance(t, dict):
            continue
        usage = t.get("usage")
        if isinstance(usage, dict) and usage.get("cost") is None and not t.get("cached"):
            n += 1
    return n


def judge_cost(record: dict) -> tuple[float, bool]:
    """Return ``(cost, incomplete)`` for the judge call on this record.

    ``cost`` is counted whenever ``judge_usage.cost`` is present (an ``unparseable`` judgment still
    burned paid tokens). ``incomplete`` flags every way the judge spend is under-counted, so the report
    is never silently a lower bound:
      - a judge call ran (status judged/unparseable) but no cost came back;
      - the conversation COMPLETED but no judgment is attached — a judge call was expected, not a
        legitimately-never-sent ``skipped_incomplete``;
      - the judge needed retries (``attempts > 1``): only the last attempt's usage is stored, so the
        earlier billed attempt(s) are real spend this total omits.
    A never-sent ``skipped_incomplete`` (incomplete conversation) is NOT a gap.
    """
    j = record.get("judgment")
    if not isinstance(j, dict) or not j:
        # no judgment attached: a missing judge call is a gap only if the conversation completed
        return 0.0, is_complete(record)
    if isinstance(j.get("panel"), list):
        # 3-judge panel (full run): sum every member's cost; any member with a missing cost or a
        # retry (earlier billed attempts unrecorded) marks the record's judge spend under-counted.
        total, incomplete = 0.0, False
        for member in j["panel"]:
            mu = member.get("judge_usage") if isinstance(member, dict) else None
            c = mu.get("cost") if isinstance(mu, dict) else None
            if c is None:
                incomplete = incomplete or member.get("status") in _JUDGE_CALL_STATUSES
            else:
                total += float(c)
                a = member.get("attempts")
                incomplete = incomplete or (isinstance(a, int) and a > 1)
        return total, incomplete
    ju = j.get("judge_usage")
    cost = ju.get("cost") if isinstance(ju, dict) else None
    if cost is None:
        return 0.0, j.get("status") in _JUDGE_CALL_STATUSES
    attempts = j.get("attempts")
    retried = isinstance(attempts, int) and attempts > 1  # earlier billed attempts not in judge_usage
    return float(cost), retried


def is_complete(record: dict) -> bool:
    return (record.get("metadata") or {}).get("complete", True) is True


@dataclass(frozen=True)
class CostReport:
    """Aggregate spend across a set of conversation records (conversation turns + judge calls)."""

    n_conversations: int
    turns_usd: float
    judge_usd: float
    total_usd: float
    missing_cost_turns: int
    judge_calls_missing_cost: int

    @property
    def is_lower_bound(self) -> bool:
        """True if any charged call returned no cost, so ``total_usd`` under-counts real spend."""
        return self.missing_cost_turns > 0 or self.judge_calls_missing_cost > 0

    def as_record(self) -> dict:
        # quantize only at the report boundary (binary-float tails); internal sums stay raw float so
        # turns_usd mirrors Conversation.total_cost exactly.
        return {
            "n_conversations": self.n_conversations,
            "turns_usd": round(self.turns_usd, 6),
            "judge_usd": round(self.judge_usd, 6),
            "total_usd": round(self.total_usd, 6),
            "missing_cost_turns": self.missing_cost_turns,
            "judge_calls_missing_cost": self.judge_calls_missing_cost,
            "is_lower_bound": self.is_lower_bound,
        }


def conversation_cost(record: dict) -> dict:
    """Per-conversation cost breakdown (rendered in the viewer's conversation header)."""
    t_usd = turns_cost(record)
    j_usd, j_missing = judge_cost(record)
    return {
        "turns_usd": t_usd,
        "judge_usd": j_usd,
        "total_usd": t_usd + j_usd,
        "missing_cost_turns": missing_cost_turns(record),
        "judge_cost_missing": j_missing,
    }


def accumulate(records: Iterable[dict]) -> CostReport:
    """Sum spend across all records, INCLUDING each judge call; track lower-bound gaps."""
    n = 0
    turns_total = 0.0
    judge_total = 0.0
    missing_turns = 0
    judge_missing = 0
    for r in records:
        n += 1
        turns_total += turns_cost(r)
        j_usd, j_missing = judge_cost(r)
        judge_total += j_usd
        missing_turns += missing_cost_turns(r)
        if j_missing:
            judge_missing += 1
    return CostReport(
        n_conversations=n,
        turns_usd=turns_total,
        judge_usd=judge_total,
        total_usd=turns_total + judge_total,
        missing_cost_turns=missing_turns,
        judge_calls_missing_cost=judge_missing,
    )
