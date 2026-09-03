"""The invocation record — the fully resolved INTENT of a run, written once before any spend.

WHY IT EXISTS

The arm manifests record what an arm ACTUALLY DID, and they are rewritten every time the arm
is touched — so a resumed run's manifests describe only its LAST invocation, not what the run
was originally commissioned with.

``invocation.json`` closes that gap. It is written at preflight, BEFORE the first dollar, and never
rewritten. That makes it two things at once:

  * the provenance record of what was intended, independent of what happened; and
  * the only thing that makes a crashed run resumable — because a sliced grid CANNOT be
    reconstructed from partial records. "sliced to three advisors" and "crashed before reaching
    advisors four and five" are byte-identical on disk. Only the recorded intent tells them apart.

That is also why ``--continue`` refuses a run with no invocation.json rather than guessing.
"""
from __future__ import annotations

from typing import Iterable, Optional

from tup.store import ARM_ORDER, ARMS

SCHEMA = "tup-invocation/1"

#: The context condition each arm runs under. The arm name is the single source of this mapping —
#: deriving it from the arm name makes an arm/flag disagreement unrepresentable.
ARM_CONTEXT = {"main": "none", "context": "barrier"}


def cell_id(vignette_id: str, family_name: str, advisor: str, replicate: int) -> str:
    """Mirrors ``driver.cell_id`` / ``runner.run_conversation``'s conversation_id."""
    return f"{vignette_id}__{family_name}__{advisor}__r{replicate}"


def build_grid(vignettes: Iterable[str], families: Iterable[str], advisors: Iterable[str],
               replicates: int) -> list[str]:
    """The arm's cell ids, in the driver's nesting order (family innermost).

    Order matters for cache locality, and keeping ONE definition of it means the recorded grid and
    the executed grid cannot drift apart.
    """
    return [cell_id(v, f, a, r)
            for v in vignettes for a in advisors for r in range(replicates) for f in families]


def build_invocation(*, run_id: str, started_at: str, run_name: str, dry_run: bool,
                     vignettes: list[str], families: list[str], advisors: list[str],
                     replicates: dict, arms: list[str], seed, concurrency: int,
                     max_spend: float, estimate_usd: float, lock_record: Optional[dict],
                     slice_filters: dict, reproducibility: Optional[dict] = None) -> dict:
    """The write-once record. Everything needed to re-derive the grid, byte for byte."""
    grids = {arm: build_grid(vignettes, families, advisors, replicates[arm]) for arm in arms}
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "run_name": run_name,
        "started_at": started_at,
        "dry_run": bool(dry_run),
        "arms": list(arms),
        "grid": {
            "vignettes": list(vignettes),
            "families": list(families),
            "advisors": list(advisors),
            "replicates": dict(replicates),
            "arm_context": {a: ARM_CONTEXT[a] for a in arms},
            "cells": {a: len(g) for a, g in grids.items()},
            "cell_ids": {a: g for a, g in grids.items()},
        },
        # The slice AS REQUESTED, kept separately from the resolved grid: it is what distinguishes a
        # deliberate slice from a crash, and --continue refuses to let a later invocation change it.
        "slice": dict(slice_filters),
        "config": {"seed": seed, "concurrency": concurrency},
        "budget": {"max_spend_usd": max_spend, "estimate_usd": estimate_usd},
        "stack_lock": lock_record,
        "reproducibility": reproducibility,
    }


def expected_cell_ids(invocation: dict, arm: str) -> set:
    """The arm's full grid, taken from the RECORDED intent — never re-derived from today's roster.

    Re-deriving would silently repair a run whose roster has since changed, which is the
    "recorded but unchecked" failure class the lock exists to close.
    """
    cells = ((invocation.get("grid") or {}).get("cell_ids") or {}).get(arm)
    if cells is None:
        raise KeyError(f"invocation.json records no grid for arm {arm!r}")
    return set(cells)


def arm_state(run, invocation: dict, arm: str) -> dict:
    """Per-arm completion, derived FROM RECORDS (never from the manifest's existence).

    Returns ``{in_invocation, present, done, failed, expected, missing, complete}``.
    """
    a = run.arm(arm)
    if arm not in (invocation.get("arms") or []):
        return {"present": False, "in_invocation": False, "done": 0, "failed": 0,
                "expected": 0, "missing": set(), "complete": False}
    expected = expected_cell_ids(invocation, arm)
    done = a.record_ids()
    failed = a.failed_ids()
    missing = expected - done - failed
    return {
        "present": a.has_records(),
        "in_invocation": True,
        "done": len(done),
        "failed": len(failed),
        "expected": len(expected),
        "missing": missing,
        # The same comparison the driver uses: `complete = expected <= (done | failed_ids)`.
        "complete": expected <= (done | failed),
    }


def resolve_arms_to_continue(run, invocation: dict,
                             requested: Optional[list] = None) -> tuple[list, dict]:
    """Which arms a ``--continue`` invocation should run, and why.

    Resumes every INCOMPLETE arm of the recorded invocation, in main-then-context order.
    ``requested`` (from ``--arms``) NARROWS that set; it never widens it to a complete arm and never
    introduces an arm the invocation never had.
    """
    states = {a: arm_state(run, invocation, a) for a in ARM_ORDER}
    todo = [a for a in ARM_ORDER if states[a]["in_invocation"] and not states[a]["complete"]]
    if requested is not None:
        unknown = [a for a in requested if a not in ARMS]
        if unknown:
            raise ValueError(f"unknown arm(s) {unknown}; the arms are {list(ARMS)}")
        not_in_run = [a for a in requested if not states[a]["in_invocation"]]
        if not_in_run:
            raise ValueError(
                f"--arms names {not_in_run}, which this run's invocation.json never included "
                f"(it recorded {invocation.get('arms')}). --continue can only resume arms the run "
                f"was commissioned with."
            )
        todo = [a for a in todo if a in requested]
    return todo, states


def conflicting_slice(invocation: dict, requested: dict) -> list[str]:
    """Slice flags passed alongside ``--continue`` that contradict the recorded slice.

    An ERROR, never an override: silently honouring a new slice would make the run's own
    invocation.json a lie about the data beside it.
    """
    recorded = invocation.get("slice") or {}
    out = []
    for key, value in (requested or {}).items():
        if value is None:
            continue
        was = recorded.get(key)
        if was is None or list(was) != list(value):
            out.append(f"--{key}: run recorded {was!r}, this invocation passed {list(value)!r}")
    return out
