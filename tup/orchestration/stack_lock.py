"""Fail-closed enforcement of the locked instrument stack (config/locked_stack.yaml).

The rule this module enforces: **anything that must be true at runtime is asserted at runtime,
against the resolved configuration, before any money is spent.** Prose is documentation; this is
the lock.

Usage (launchers):

    from tup.orchestration.stack_lock import assert_locked_stack
    assert_locked_stack(resolved={"patient_framing": framing, "max_turns": max_turns, ...},
                        allow_override=args.unlock_stack)

`verify_records` provides the matching post-hoc check: given persisted records, confirm the run
that actually happened carries the locked values (the half that catches what preflight alone cannot).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = REPO_ROOT / "config" / "locked_stack.yaml"


class StackLockError(RuntimeError):
    """Raised when the resolved runtime configuration contradicts the declared lock."""


def load_lock(path: Optional[Path] = None) -> dict:
    import yaml
    p = Path(path or LOCK_PATH)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    lock = doc.get("lock")
    if not isinstance(lock, dict) or not lock:
        raise StackLockError(f"{p} contains no usable `lock:` mapping")
    return lock


def resolve_current() -> dict:
    """Read the instrument values the code would actually use right now, from the files themselves."""
    from tup.data.prompts import PATIENT_SYSTEM, load_advisor_info, load_families, load_judge_prompt
    out: dict = {}
    try:
        m = re.search(r"^version:\s*(\S+)", PATIENT_SYSTEM.read_text(encoding="utf-8"), re.M)
        if m:
            out["patient_prompt_version"] = int(m.group(1))
    except OSError:
        pass
    try:
        out["families_version"] = (load_families() or {}).get("version")
    except Exception:  # noqa: BLE001 — a resolution failure must not mask the mismatch report
        pass
    try:
        out["judge_prompt_version"] = load_judge_prompt().version
    except Exception:  # noqa: BLE001
        pass
    try:
        out["advisor_option"] = (load_advisor_info() or {}).get("option")
    except Exception:  # noqa: BLE001
        pass
    # NOTE: each term gets its OWN try block. Grouping them means one import failure silently drops
    # several lock terms at once, which is the failure shape this whole module exists to prevent.
    try:
        # A declared-but-unresolved key is silently never compared (check() only compares keys
        # present in both). Reading guard_version here is what makes the guard rule-set a real
        # term of the lock.
        from tup.orchestration.guard import GUARD_VERSION
        out["guard_version"] = GUARD_VERSION
    except Exception:  # noqa: BLE001
        pass
    try:
        # The patient simulator's slug: config/models.yaml roles.patient_model, falling back to the
        # patient provider's own slug when no per-role override is set (client.resolve_model does
        # the same). Resolving it here is what makes a silent patient swap impossible.
        from tup.client.config import load_config
        cfg = load_config()
        out["patient_model"] = cfg.patient_model or cfg.providers.get(cfg.patient)
    except Exception:  # noqa: BLE001
        pass
    try:
        # The turn cap the code would ACTUALLY use when a launcher does not override it — a
        # locked value that lives only as a code default is unasserted, the precise defect class
        # this module exists to close. An explicit --max-turns still overrides this in the
        # caller's payload, which is the correct precedence.
        from tup.orchestration.runner import DEFAULT_MAX_TURNS
        out["max_turns"] = DEFAULT_MAX_TURNS
    except Exception:  # noqa: BLE001
        pass
    try:
        # Condition count, resolved from the live families file so a family silently vanishing
        # fails closed (a declared count that nothing resolves asserts nothing at all).
        out["n_families"] = len((load_families() or {}).get("families") or [])
    except Exception:  # noqa: BLE001
        pass
    return out


def check(resolved: dict, lock: Optional[dict] = None) -> list[str]:
    """Return a list of human-readable mismatch descriptions (empty list == compliant).

    Only keys present in BOTH the lock and `resolved` are compared, so a caller may assert a
    subset; a key the caller leaves out of ``resolved`` is NOT asserted — which is why the launcher passes
    patient_framing explicitly (resolve_current() cannot see an invocation property).
    """
    lock = lock or load_lock()
    problems = []
    for key, want in lock.items():
        if key in ("name", "locked_on", "rationale"):
            continue
        if key not in resolved:
            continue
        got = resolved[key]
        if got != want:
            problems.append(f"{key}: locked={want!r} but this run resolves to {got!r}")
    return problems


def assert_locked_stack(resolved: dict, *, allow_override: bool = False,
                        lock: Optional[dict] = None, include_files: bool = True) -> dict:
    """Fail closed unless the resolved configuration matches the lock.

    Returns a provenance dict for the run manifest (what was checked, and whether it was
    overridden), so a deliberately unlocked run is permanently self-identifying in its output.
    """
    lock = lock or load_lock()
    merged = dict(resolve_current()) if include_files else {}
    merged.update(resolved)
    problems = check(merged, lock)
    record = {
        "lock_name": lock.get("name"), "locked_on": lock.get("locked_on"),
        "checked": {k: merged.get(k) for k in lock if k not in ("name", "locked_on", "rationale")
                    and k in merged},
        "mismatches": problems, "overridden": bool(problems and allow_override),
    }
    if problems and not allow_override:
        raise StackLockError(
            "LOCKED STACK VIOLATION — refusing to start.\n  "
            + "\n  ".join(problems)
            + f"\n\nThe locked stack is declared in {LOCK_PATH.relative_to(REPO_ROOT)} "
              f"(lock '{lock.get('name')}', locked {lock.get('locked_on')}).\n"
              "Fix the configuration, or pass the explicit unlock flag if this deviation is "
              "intended — an unlocked run is recorded as such in its manifest."
        )
    return record


def verify_records(records: Iterable[dict], lock: Optional[dict] = None) -> dict:
    """Post-hoc: confirm persisted records carry the locked values they observably record.

    This is the check that catches a run whose records contradict its lock within one second
    of it finishing. Observable per record: patient_framing, max_turns,
    patient_prompt_version, families_version, guard_version, judge_prompt_version, and
    patient_model (from the live patient turns). The remaining lock terms (advisor_option,
    n_families) leave no per-record trace and are asserted by the preflight only.
    Returns {"ok": bool, "problems": [...], "observed": {...}}.
    """
    lock = lock or load_lock()
    keys = {"patient_framing": ("metadata", "patient_framing"),
            "max_turns": ("metadata", "max_turns")}
    observed: dict = {}
    for r in records:
        meta = (r or {}).get("metadata") or {}
        for key, (_, field) in keys.items():
            if field in meta:
                observed.setdefault(key, set()).add(meta[field])
        prompts = meta.get("prompts") or {}
        pv = (prompts.get("patient") or {}).get("version")
        if pv is not None:
            observed.setdefault("patient_prompt_version", set()).add(pv)
        fv = (prompts.get("families") or {}).get("version")
        if fv is not None:
            observed.setdefault("families_version", set()).add(fv)
        gv = (meta.get("guard") or {}).get("version")
        if gv is not None:
            observed.setdefault("guard_version", set()).add(gv)
        jv = (((r or {}).get("judgment") or {}).get("judge_prompt") or {}).get("version")
        if jv is not None:
            observed.setdefault("judge_prompt_version", set()).add(jv)
        for t in (r or {}).get("turns") or []:
            if isinstance(t, dict) and t.get("speaker") == "patient" and t.get("model"):
                observed.setdefault("patient_model", set()).add(t["model"])
    problems = []
    for key, values in observed.items():
        want = lock.get(key)
        if want is None:
            continue
        if len(values) > 1:
            problems.append(f"{key}: records disagree ({sorted(values)!r}) — mixed-stack output file")
        elif next(iter(values)) != want:
            problems.append(f"{key}: locked={want!r} but records carry {next(iter(values))!r}")
    return {"ok": not problems, "problems": problems,
            "observed": {k: sorted(v) for k, v in observed.items()}}
