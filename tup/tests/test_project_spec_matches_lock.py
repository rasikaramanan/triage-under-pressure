"""``PROJECT_SPEC.md`` section 13.1 mirrors ``config/locked_stack.yaml`` for human readers; the lock is
the authority (machine-asserted before every run and re-derived from the records afterward).
The table is parsed here and compared to the lock in BOTH directions:

* a lock term with no row, or a row whose value disagrees, fails — the spec has gone stale;
* a row naming a term the lock does not define fails too — the spec is inventing authority.

The fix for a failure is to correct ``PROJECT_SPEC.md``, or to change the lock deliberately. It is
never to edit a value here to make the assertion pass.

Companion to ``tup/tests/test_store_contract_is_executable.py``, which does the same job for the
store's contract in ``results/README.md``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "PROJECT_SPEC.md"
LOCK = REPO_ROOT / "config" / "locked_stack.yaml"

#: Keys under ``lock:`` that are provenance about the lock itself rather than instrument terms.
_NOT_INSTRUMENT_TERMS = {"name", "locked_on", "rationale"}

_HEADING = "### 13.1 Instrument terms"
#: ``| `term` | `value` | gloss |`` — value may be backticked or bare (e.g. a plain 7).
_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|\s*`?([^|`]+?)`?\s*\|\s*([^|]*?)\s*\|\s*$")


def _spec_rows() -> dict[str, str]:
    """{term: value} parsed out of the section 13.1 instrument table in PROJECT_SPEC.md."""
    text = SPEC.read_text(encoding="utf-8")
    parts = text.split(_HEADING, 1)
    assert len(parts) == 2, (
        f"PROJECT_SPEC.md lost its '{_HEADING}' section — that table is the machine-checked "
        f"mirror of config/locked_stack.yaml and may not simply be deleted.")
    rows: dict[str, str] = {}
    for line in parts[1].splitlines():
        if line.startswith("## "):          # next top-level section: table is over
            break
        m = _ROW.match(line)
        if not m:
            continue
        term, value = m.group(1), m.group(2).strip()
        if term == "term":                  # the header row
            continue
        assert term not in rows, f"PROJECT_SPEC.md lists `{term}` twice in the instrument table"
        rows[term] = value
    assert rows, "the section 13.1 instrument table parsed to zero rows — did its format change?"
    return rows


def _lock_terms() -> dict[str, str]:
    """{term: value} from config/locked_stack.yaml's lock: block, as strings."""
    doc = yaml.safe_load(LOCK.read_text(encoding="utf-8"))
    lock = doc["lock"]
    return {k: str(v) for k, v in lock.items() if k not in _NOT_INSTRUMENT_TERMS}


def test_every_locked_term_has_a_matching_row_in_the_spec():
    """The spec going stale against the instrument is the failure this file exists to catch."""
    lock, rows = _lock_terms(), _spec_rows()

    missing = sorted(set(lock) - set(rows))
    assert not missing, (
        "config/locked_stack.yaml defines these terms, but PROJECT_SPEC.md section 13.1 has no row for "
        "them:\n  " + "\n  ".join(f"{t} = {lock[t]}" for t in missing))

    drifted = {t: (lock[t], rows[t]) for t in lock if rows[t] != lock[t]}
    assert not drifted, "PROJECT_SPEC.md section 13.1 has drifted from the lock:\n  " + "\n  ".join(
        f"{t}: lock says {locked!r}, spec says {spec!r}"
        for t, (locked, spec) in sorted(drifted.items()))


def test_the_spec_names_no_term_the_lock_does_not_define():
    """The converse: a row inventing a locked term the instrument never asserts."""
    lock, rows = _lock_terms(), _spec_rows()
    extra = sorted(set(rows) - set(lock))
    assert not extra, (
        "PROJECT_SPEC.md section 13.1 lists these as instrument terms, but config/locked_stack.yaml does not "
        "define them — either add them to the lock or drop the rows:\n  "
        + "\n  ".join(f"{t} = {rows[t]}" for t in extra))


@pytest.mark.parametrize("phrase", ["provisional", "under review"])
def test_the_spec_does_not_hedge_about_settled_instrument_values(phrase):
    """`PROJECT_SPEC.md` must carry no 'provisional'/'under review' hedge anywhere: a hedge on
    a settled instrument value misleads every reader."""
    hits = [f"{n}: {ln.strip()}"
            for n, ln in enumerate(SPEC.read_text(encoding="utf-8").splitlines(), 1)
            if phrase in ln.lower()]
    assert not hits, (
        f"PROJECT_SPEC.md still calls something {phrase!r}; if the decision is locked, say so:\n  "
        + "\n  ".join(hits))
