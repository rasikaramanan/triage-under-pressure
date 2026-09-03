"""Record classification for every consumer of persisted records.

Operates on persisted record dicts (see ``persist.py``). A conversation is ANALYZABLE only when it
is complete (``metadata.complete``) and its judgment is a clean, internally consistent parse —
``skipped_incomplete`` / ``unparseable`` / missing / malformed judgments never enter init_correct /
ToD / Resistance. ``exclusion_reason`` names why a record is excluded (incomplete / unparseable /
panel_incomplete / judge_failed / unjudged / malformed) so exclusions are itemized, never silent.
"""
from __future__ import annotations

from typing import Optional


def is_complete(record: dict) -> bool:
    """True unless the runner marked the conversation incomplete (an empty turn aborted it)."""
    return (record.get("metadata") or {}).get("complete", True) is True


def _judged_wellformed(j) -> bool:
    """A judgment is analyzable iff status=='judged' with a 0/1 init AND a ToD consistent with it.

    The judge parser (tup/judge/parser.py) guarantees this for live records, but ``load_records`` reads arbitrary on-disk
    JSONL — so the output layer re-checks rather than trusting the invariant. A record that violates it
    (e.g. init==1 with ToD=='NA', or a missing ToD key) is treated as not-analyzable and EXCLUDED, never
    half-counted (counted in init_correct yet silently dropped from the ToD/Resistance denominator).
    """
    if not (isinstance(j, dict) and j.get("status") == "judged"):
        return False
    init = j.get("init_correct")
    if init not in (0, 1):
        return False
    tod = j.get("ToD")
    if init == 0:
        return tod == "NA"
    return isinstance(tod, int) and not isinstance(tod, bool)


def is_judged(record: dict) -> bool:
    """True if a clean, internally-consistent judgment is attached."""
    return _judged_wellformed(record.get("judgment"))


def is_analyzable(record: dict) -> bool:
    """A conversation enters the metrics iff it is complete AND cleanly judged."""
    return is_complete(record) and is_judged(record)


def exclusion_reason(record: dict) -> Optional[str]:
    """None if analyzable; else WHY excluded — so the summary can break out the conflated n_excluded."""
    if is_analyzable(record):
        return None
    if not is_complete(record):
        return "incomplete"
    j = record.get("judgment")
    if not j:
        return "unjudged"
    if isinstance(j, dict) and j.get("status") == "unparseable":
        return "unparseable"
    if isinstance(j, dict) and j.get("status") == "panel_incomplete":
        # Full-run analogue of unparseable: no aggregate could be formed. This means >=2
        # seats failed to parse after the corrective rejudge
        # retry (exactly one dead seat aggregates as `median2_Tplus1_fallback` instead of
        # voiding). Without this branch these landed in "malformed", making judge-output failures
        # read as data corruption.
        return "panel_incomplete"
    if isinstance(j, dict) and j.get("status") == "judge_failed":
        # SOFT JUDGE: the judge CALL errored (e.g. an upstream 429) after a
        # complete conversation was generated. The transcript is intact and re-judgeable via
        # scripts/rejudge.py, so this is a recoverable gap — it must not read as data corruption.
        return "judge_failed"
    return "malformed"   # complete + judgment present but not a well-formed 'judged' record


def num_advisor_responses(record: dict) -> int:
    return sum(1 for t in record.get("turns", []) if isinstance(t, dict) and t.get("speaker") == "advisor")
