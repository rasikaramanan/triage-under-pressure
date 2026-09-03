"""Persist + reload full per-conversation records as JSONL.

One JSON object per line = one ``Conversation``'s full record: the transcript (every turn with its
per-call usage/cost/routing), the metadata, AND the attached ``Judgment`` (incl. the judge prompt
version/sha — PROJECT_SPEC.md section 14). This is the canonical record persistence that the aggregator / cost accumulator
/ viewer read back.

The batch driver (tup/harness/driver.py) layers incremental append + skip-if-done resume on top of ``append_record``
(a ``'w'``-mode writer would truncate the file on every call).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Optional, Union

from tup.orchestration.transcript import Conversation


def to_record(item: Union[Conversation, dict]) -> dict:
    """Full serializable record for one conversation (Conversation -> dict; a dict passes through)."""
    if isinstance(item, Conversation):
        return item.to_dict()
    if isinstance(item, dict):
        return item
    raise TypeError(f"expected Conversation or dict record, got {type(item).__name__}")


def save_records(items: Iterable[Union[Conversation, dict]], path) -> Path:
    """Write all records as JSONL (mode ``'w'`` — full rewrite). Returns the path written."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(to_record(it), ensure_ascii=False) + "\n")
    return p


def append_record(item: Union[Conversation, dict], path) -> Path:
    """Append ONE record as a single JSONL line (the harness driver's incremental-persist primitive).

    Torn-tail guard: a run killed mid-append leaves a final line with no trailing
    newline; blindly appending would concatenate the fresh record onto that fragment, making the
    paid-for record unreadable forever while the driver still counts the cell done. If the file's
    last byte isn't a newline, terminate the fragment first — the torn line stays skippable garbage
    and the new record lands on its own intact line.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if p.exists() and p.stat().st_size > 0:
        with p.open("rb") as fh:
            fh.seek(-1, 2)  # os.SEEK_END
            needs_newline = fh.read(1) != b"\n"
    with p.open("a", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        f.write(json.dumps(to_record(item), ensure_ascii=False) + "\n")
    return p


def load_records(path, *, strict: bool = False) -> list[dict]:
    """Read a JSONL file back into a list of record dicts (blank lines skipped).

    ``strict=False`` (default) recovers every well-formed record and SKIPS a malformed line instead of
    aborting the whole read — ``append_record`` is non-atomic (plain ``open('a')`` + ``write``), so a run
    killed mid-write can leave a torn final line, and the resume reader must still recover every
    fully-written record before it to honor skip-if-done.

    The tolerance is deliberately NOT blind to where corruption sits — position is what separates
    an expected artifact from real corruption:
      - a **torn trailing line** is the EXPECTED artifact of a killed non-atomic append → a quiet warning;
      - a **mid-file** unparseable line is genuine corruption (something a clean append never produces) →
        a LOUD, separately-labelled warning so it can't hide behind the benign tail case.
    Either way the read returns the recoverable records. Pass ``strict=True`` to instead raise on the
    first bad line (e.g. when validating a file you expect to be whole, not a resume-in-progress tail).
    """
    p = Path(path)
    records: list[dict] = []
    bad_mid: list[int] = []
    pending_bad: Optional[int] = None   # a bad line not yet known to be mid-file (more lines?) or the tail
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            # a later non-blank line proves any pending bad line was mid-file, not the trailing tail
            if pending_bad is not None:
                bad_mid.append(pending_bad)
                pending_bad = None
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                if strict:
                    raise
                pending_bad = lineno
    if bad_mid:
        print(f"warning: skipped {len(bad_mid)} CORRUPT mid-file line(s) in {p} at {bad_mid} "
              f"(genuine corruption — NOT a torn tail)", file=sys.stderr)
    if pending_bad is not None:   # the last non-blank line failed to parse: a torn trailing append
        print(f"warning: dropped a torn trailing line {p}:{pending_bad} "
              f"(expected if a writer was killed mid-append)", file=sys.stderr)
    return records
