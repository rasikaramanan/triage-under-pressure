"""Batch driver for ONE ARM of one run.

Drives the locked grid (vignettes × families × advisors × replicates) and APPENDS each finished
record to the arm's ``records.jsonl``, keyed on the deterministic ``conversation_id``.

WHERE IT WRITES IS NOT ITS DECISION. The driver is handed an :class:`tup.store.ArmDir` and writes
the seven files inside it. It cannot be pointed at an arbitrary path: the store's path ownership
makes a redirected output location unrepresentable.

WHAT IT RUNS WITH IS NOT ITS DECISION EITHER. ``max_spend``, ``max_turns`` and ``replicates``
are REQUIRED keyword arguments with no defaults. A locked value that lives as an unpassed
function default is silently unasserted; a parameter with no default cannot be.

The arm's NAME determines its context condition (``ARM_CONTEXT``), so ``context_arm`` is derived
rather than passed — deriving it from the directory name makes an arm/flag disagreement
unrepresentable.

It is:

  - **resumable, always** — on restart it reads the existing records (tolerating a torn final line)
    and SKIPS any conversation_id already persisted, so an interrupted run continues where it
    stopped. There is no ``resume=False``: nothing here truncates. A fresh start is a NEW RUN ID,
    which the store mints rather than overwrites;
  - **isolated** — the fallible per-cell work (generate → judge, plus persist on the serial path) is under ``try/except``;
    on the parallel path a persistence error deliberately aborts the grid — a store that cannot be written is not a per-cell fault;
    a failing cell is logged to a failures manifest and the grid continues (one bad cell never aborts the
    rest of the grid). The failure handler and the progress callback are themselves guarded, so a broken stdout
    pipe or a manifest-write error can't take the run down or miscount a persisted cell;
  - **budget-capped** — a running real-dollar total INCLUDING the judge call is checked before
    each cell and the run hard-aborts at ``max_spend``. The serial path additionally FAILS CLOSED
    on missing cost metadata (``spent`` becomes a lower bound, so the cap can no longer be
    trusted); the parallel path (the production mode) records missing-cost cells and reports the
    total as a lower bound instead of aborting mid-flight.

Persistence uses ``append_record`` (NOT ``save_records`` — its ``'w'`` mode truncates). ``max_spend``
caps the CUMULATIVE cost of the whole RUN: ``prior_spend`` carries what the run's earlier arms
already spent, so two arms in one invocation share one ceiling instead of each getting a private
copy of it.
"""
from __future__ import annotations

import json
import sys
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from tup.client.openrouter import OpenRouterClient
from tup.client.top_p import effective_top_p_record
from tup.harness.invocation import ARM_CONTEXT
from tup.data.prompts import load_families
from tup.data.vignettes import load_vignettes
from tup.judge.judge import judge_conversation_panel
from tup.orchestration.runner import run_conversation
from tup.output import cost as costmod
from tup.output.audit_sample import select_audit_sample
from tup.output.persist import append_record, load_records

DEFAULT_CONCURRENCY = 16  # in-flight conversations for the parallel path — the production
#                           mode; concurrency=1 selects the serial path (used by tests and for
#                           replaying older serial data).


def _default_reproducibility() -> dict:
    """The PROJECT_SPEC.md section 14 reproducibility block for the manifest when the caller supplies none.

    ``top_p_verified_at`` is None here — the CLI overrides it with the timestamp of its live
    ``verify_top_p()`` preflight; a direct/test call records the provenance table unverified.
    """
    return {"effective_top_p": effective_top_p_record(), "top_p_verified_at": None}


def cell_id(vignette_id: str, family_name: str, advisor: str, replicate: int) -> str:
    """The deterministic conversation_id (mirrors ``runner.run_conversation``)."""
    return f"{vignette_id}__{family_name}__{advisor}__r{replicate}"


@dataclass
class RunReport:
    n_cells: int                 # cells considered this invocation (after limit)
    completed: int
    skipped: int                 # already-done cells skipped on resume
    failed: int
    aborted: bool
    abort_reason: Optional[str]
    cost: costmod.CostReport     # CUMULATIVE cost of the whole output file (incl. judge)
    failures: list
    out_path: str
    failures_path: str
    manifest_path: str
    complete: bool = False       # every full-grid cell reached a terminal state (persisted or failed)
    audit_n: int = 0             # size of the frozen audit sample (0 unless complete)
    guard_flagged: int = 0       # conversations with >=1 guard flag this invocation (cured or accepted-with-flag)
    guard_violations: int = 0    # conversations with >=1 accepted-with-uncured-violation turn (flag-and-continue:
                                 # completed + judged, flagged for the post-run audit)

    def summary(self) -> str:
        lines = [
            f"Run report — {self.out_path}",
            f"  cells considered: {self.n_cells}  |  completed: {self.completed}  "
            f"skipped(resume): {self.skipped}  failed: {self.failed}",
        ]
        if self.aborted:
            lines.append(f"  ** ABORTED: {self.abort_reason} **")
        c = self.cost
        lb = "  ⚠ LOWER BOUND" if c.is_lower_bound else ""
        lines.append(
            f"  cost (incl. judge): ${c.total_usd:.4f}{lb}  "
            f"(turns ${c.turns_usd:.4f} + judge ${c.judge_usd:.4f} over {c.n_conversations} convos)"
        )
        if c.is_lower_bound:
            lines.append(
                f"    missing-cost turns: {c.missing_cost_turns}; "
                f"judge calls missing/incomplete cost: {c.judge_calls_missing_cost}"
            )
        if self.guard_flagged or self.guard_violations:
            lines.append(
                f"  patient guard: {self.guard_flagged} conversation(s) flagged "
                f"({self.guard_flagged - self.guard_violations} fully cured by resample, "
                f"{self.guard_violations} completed with an accepted-but-flagged turn — "
                f"retained + judged, listed for the post-run audit)"
            )
        if self.failed:
            lines.append(f"  failures manifest: {self.failures_path} ({self.failed} entr{'y' if self.failed == 1 else 'ies'})")
        lines.append(f"  run manifest: {self.manifest_path}")
        lines.append(f"  complete: {self.complete}" + (f"  |  audit sample: {self.audit_n}" if self.complete else ""))
        return "\n".join(lines)


def _families_in_order(families_doc: dict) -> list:
    return list(families_doc["families"])


def _append_failure(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _log_failure(failures: list, path: Path, now: Callable, cell: dict, exc: Exception) -> None:
    """Record a cell failure to the in-memory list + the on-disk manifest — GUARANTEED not to raise.

    The failure handler must be total: a manifest-write error (e.g. disk full — often the SAME fault
    that failed the cell) must NOT propagate and abort the other cells. Called inside the active
    ``except`` block, so ``traceback.format_exc()`` captures the cell's traceback.
    """
    try:
        ts = now()
    except Exception:  # noqa: BLE001 — a clock/sentinel error must not abort the grid
        ts = None
    payload = {**cell, "error": f"{type(exc).__name__}: {exc}",
               "traceback": traceback.format_exc(), "timestamp": ts}
    failures.append(payload)
    try:
        _append_failure(path, payload)
    except Exception:  # noqa: BLE001 — degrade to stderr; never abort the grid on a logging error
        print(f"warning: could not persist failure manifest entry for {cell.get('conversation_id')}",
              file=sys.stderr)


def _guard_bookkeeping(conv, guard_log_path: Path, now: Callable) -> tuple[bool, bool, float]:
    """Per-cell guard accounting on the success path (main thread only).

    Appends the conversation's guard section (full rejected drafts, corrections, verdicts — the
    full audit/undo record) to the arm's ``guard.jsonl`` sidecar when any event fired,
    and returns ``(flagged, patient_violation, extra_cost_usd)``. ``extra_cost_usd`` (classifier
    calls + rejected drafts — costs that never land on a Turn) is returned even for clean
    conversations so the budget cap sees ALL real spend. Never raises (same contract as _emit)."""
    g = (conv.metadata or {}).get("guard") or {}
    if not g.get("enabled"):
        return False, False, 0.0
    try:
        extra = float(g.get("extra_cost_usd") or 0.0)
    except (TypeError, ValueError):
        extra = 0.0
    if not g.get("events"):
        return False, False, extra
    try:
        guard_log_path.parent.mkdir(parents=True, exist_ok=True)
        with guard_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"conversation_id": conv.conversation_id, "logged_at": now(), **g},
                               ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — the guard section also lives on the main record; degrade to stderr
        print(f"warning: could not append guard log entry for {conv.conversation_id}", file=sys.stderr)
    return bool(g.get("n_flagged")), bool(g.get("patient_violation")), extra


def _emit(progress: Optional[Callable], event: dict, log_path: Optional[Path] = None) -> None:
    """Call the progress callback defensively — a sink error must NEVER abort the grid.

    The real CLI sink writes to stdout, which raises BrokenPipeError on a closed pipe (routine when a
    long serial run is tailed via ``| head`` / a dead ``tee``). Swallowing that here keeps per-cell
    isolation intact and stops a broken pipe from miscounting an already-persisted cell.

    The same event is appended to the arm's ``run.log``, so per-cell progress survives the terminal
    it was printed to — a multi-hour run must leave an on-disk record of which cell failed when,
    not just scrollback.
    """
    if log_path is not None:
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — a logging error must not abort the grid
            pass
    if progress is None:
        return
    try:
        progress(event)
    except Exception:  # noqa: BLE001 — untrusted sink; isolation requires swallowing its errors
        pass


def _write_manifest(path: Path, *, client, vigs, fams, advs, replicates, max_turns, max_spend,
                    reproducibility, started_at, ended_at, report_fields, cost,
                    context_arm="none", concurrency=1,
                    complete=False, audit_sample=None,
                    stack_lock=None, arm=None) -> None:
    """Write the run-level PROJECT_SPEC.md section 14 metadata manifest (one JSON object; the top_p contract lives here).

    The run's single reproducibility block: model IDs, per-role sampling
    (temperature / max_tokens), seed, the grid, timestamps, the cost summary,
    and ``reproducibility.effective_top_p`` + ``reproducibility.top_p_verified_at``.
    """
    cfg = client.config
    cache = getattr(client, "cache", None)
    cache_dir = str(cache.cache_dir) if cache is not None else None
    manifest = {
        "schema": "tup-run-manifest/1",
        "arm": arm,
        "out_path": report_fields["out_path"],
        # Experimental design (PROJECT_SPEC section 11): the arm's context condition, the locked
        # response-1 sampling and patient framing, and the execution concurrency.
        "design": {"context_arm": context_arm,
                   "response1_sampling": "independent",
                   "patient_framing": "single_message",
                   "concurrency": concurrency},
        "grid": {
            "vignettes": [v.id for v in vigs],
            "families": [f["name"] for f in fams],
            "advisors": list(advs),
            "replicates": replicates,
            "cells_this_invocation": report_fields["n_cells"],
        },
        "config": {
            "providers": dict(cfg.providers),
            "advisors": list(cfg.advisors),
            "patient": cfg.patient,
            "seed": cfg.seed,
            "sampling": {role: {"temperature": s.temperature, "max_tokens": s.max_tokens}
                         for role, s in cfg.sampling.items()},
            "max_turns": max_turns,
            "max_spend": max_spend,
            "cache_dir": cache_dir,   # which response cache produced this run (independent runs use their own)
        },
        # PROJECT_SPEC.md section 14 reproducibility: model IDs + sampling above; top_p provenance + verification here.
        # (Per-conversation prompt versions/sha + routing live on each record in the JSONL.)
        "reproducibility": reproducibility,
        # The launcher's fail-closed locked-stack check (tup/orchestration/stack_lock.py). Recorded
        # so a deliberately unlocked run is permanently self-identifying in its own output rather
        # than visible only in the launcher's stdout.
        "stack_lock": stack_lock,
        "run": {
            "started_at": started_at,
            "ended_at": ended_at,
            "completed": report_fields["completed"],
            "skipped": report_fields["skipped"],
            "failed": report_fields["failed"],
            "aborted": report_fields["aborted"],
            "abort_reason": report_fields["abort_reason"],
        },
        # Whole-grid completion + the frozen representative audit sample (for the post-run judge-decision audit). The viewer
        # reads these to gate the "audit sample" checkbox; canonical conversation_ids, [] until complete.
        "complete": bool(complete),
        "audit_sample": list(audit_sample or []),
        "cost": cost.as_record(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_lock_verification(arm_dir, records: list, stack_lock, now: Callable) -> Optional[dict]:
    """Write the arm's ``lock_verification.json``: did the run OBSERVABLY execute under the lock?

    Derived entirely from the persisted records — never from what the launcher intended: the
    records are the only witness to what actually executed.

    Never raises. A verification failure is a FINDING TO RECORD, not a reason to lose a finished
    run's data — the run has already been paid for by the time this executes.
    """
    try:
        from tup.orchestration.stack_lock import verify_records
        result = verify_records(records)
        doc = {
            "schema": "tup-lock-verification/1",
            "arm": arm_dir.arm,
            "verified_at": now(),
            "n_records": len(records),
            # What the launcher ASSERTED before spending, kept beside what the records SHOW, so the
            # two can be compared without going and finding the manifest.
            "preflight": {"lock_name": (stack_lock or {}).get("lock_name"),
                          "mismatches": (stack_lock or {}).get("mismatches"),
                          "overridden": (stack_lock or {}).get("overridden")},
            "ok": result["ok"],
            "problems": result["problems"],
            "observed": result["observed"],
        }
        arm_dir.lock_verification_path.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not result["ok"]:
            print(f"  ** LOCK VERIFICATION FAILED for arm {arm_dir.arm} — the records do NOT carry "
                  f"the locked values: {'; '.join(result['problems'])}", file=sys.stderr)
        return doc
    except Exception as e:  # noqa: BLE001 — must never cost a finished run its data
        print(f"warning: could not write lock verification for arm {arm_dir.arm} "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return None


def _generate_and_judge(client, vignette, family, advisor, replicate, *, families_doc, max_turns,
                        context_arm="none"):
    """The fallible per-cell network work: run the conversation, then judge it (judgment attached).

    Pure with respect to the run's shared bookkeeping — it touches only the response cache, whose keys are
    disjoint across cells and whose writes are atomic, so MANY worker threads can call
    this at once. Persistence + counters are the caller's job (the main thread), keeping the parallel path
    lock-free. Raises on a generation-side failure so the caller can isolate it; a judge-side failure is
    recorded as ``judge_failed`` and never raised (SOFT JUDGE).
    """
    conv = run_conversation(client, vignette, family, advisor, families=families_doc,
                            replicate=replicate, max_turns=max_turns, context_arm=context_arm)
    try:
        # 3-judge panel; the rotation index (vignette ordinal + replicate) balances which
        # eligible provider sits out (the roster's seating convention — config/roster.csv).
        rotation = int(vignette.id) + replicate
        judge_conversation_panel(client, conv, vignette, rotation_index=rotation)
    except Exception as e:  # noqa: BLE001
        # SOFT JUDGE. Judging happens after generation, so a judge-side failure — a 429 on one
        # panel seat, say — must never discard the fully-generated conversation: that would be a
        # failure in the SECONDARY outcome destroying the PRIMARY one, and re-running it costs
        # the turns again. The transcript is the expensive, irreplaceable
        # artifact; a judgment is re-derivable from it at any time by scripts/rejudge.py. So keep the
        # conversation, mark it, and let the caller decide.
        conv.judgment = {"status": "judge_failed", "error": f"{type(e).__name__}: {e}"}
    return conv


def run_arm(
    client: OpenRouterClient,
    arm_dir,
    *,
    # --- no defaults, deliberately: see the module docstring -------------------------------------
    max_spend: float,
    max_turns: int,
    replicates: int,
    # --- genuinely optional ---------------------------------------------------------------------
    vignettes: Optional[list] = None,
    families: Optional[list] = None,
    advisors: Optional[list] = None,
    prior_spend: float = 0.0,
    reproducibility: Optional[dict] = None,
    stack_lock: Optional[dict] = None,   # the launcher's assert_locked_stack() record, for the manifest
    concurrency: int = 1,
    progress: Optional[Callable] = None,
    now: Optional[Callable] = None,
) -> RunReport:
    """Run one arm's grid; append + judge + cost-cap; write its manifest; return a RunReport.

    ``arm_dir`` is a :class:`tup.store.ArmDir`. Its NAME picks the arm's context condition, so the
    two arms of a run cannot disagree with where they are written.

    ``prior_spend`` is what the run's EARLIER arms already cost. ``max_spend`` is a whole-run cap, so
    the context arm must start its accounting from where the main arm left off — otherwise a $150 cap
    silently authorises $300 across two arms.

    ``concurrency`` > 1 runs conversations through a thread pool (workers do generate+judge; the MAIN
    thread owns all persistence + bookkeeping, so the path is lock-free aside from the atomic, key-disjoint
    cache). The parallel path is best-effort on
    budget ("flag & continue" on missing cost; overshoot is at most ``concurrency`` in-flight cells when
    the cap trips); the serial path (``concurrency=1``, default) keeps its strict fail-closed behavior.
    """
    context_arm = ARM_CONTEXT[arm_dir.arm]
    arm_dir.mkdir()
    out_path = arm_dir.records_path
    failures_path = arm_dir.failures_path
    manifest_path = arm_dir.manifest_path
    guard_log_path = arm_dir.guard_path
    log_path = arm_dir.log_path

    def emit(event: dict) -> None:
        """Progress to the caller's sink AND to the arm's run.log — see _emit."""
        _emit(progress, event, log_path)
    now = now or (lambda: datetime.now(timezone.utc).isoformat())
    started_at = now()
    if reproducibility is None:
        reproducibility = _default_reproducibility()

    families_doc = load_families()
    fams = families if families is not None else _families_in_order(families_doc)
    vigs = vignettes if vignettes is not None else load_vignettes()
    advs = advisors if advisors is not None else list(client.config.advisors)

    # Resume is unconditional — nothing here truncates. Which conversation_ids are already persisted,
    # and what has this arm already cost? `spent` starts from the run's earlier arms so one cap
    # covers the whole run.
    existing = load_records(out_path) if out_path.exists() else []
    done = {r.get("conversation_id") for r in existing}
    spent = prior_spend + costmod.accumulate(existing).total_usd

    # Order family INNERMOST so all conditions of one (vignette, advisor, replicate) run
    # adjacently: identical vignette prefixes stay adjacent for provider-side prompt caching.
    cells = [
        (v, fam, adv, rep)
        for v in vigs
        for adv in advs
        for rep in range(replicates)
        for fam in fams
    ]
    completed = skipped = failed = 0
    guard_flagged = guard_violations = 0
    failures: list = []
    aborted = False
    abort_reason: Optional[str] = None
    cost_untrusted = False   # set once any completed cell reports a missing cost (spent under-counts)

    if concurrency <= 1:
        # SERIAL (default): strict fail-closed budget cap (cap reached OR cost data missing → abort).
        for idx, (v, fam, adv, rep) in enumerate(cells):
            cid = cell_id(v.id, fam["name"], adv, rep)
            if cid in done:
                skipped += 1
                emit({"i": idx, "n": len(cells), "id": cid, "status": "skip", "spent": spent})
                continue
            # FAIL CLOSED before launching a cell: when the cap is reached, OR once cost data has gone
            # missing (then `spent` is only a lower bound and the cap can no longer be trusted — halt
            # rather than sail past it; the run is resumable, so no completed work is lost).
            if spent >= max_spend or cost_untrusted:
                aborted = True
                why = (f"--max-spend ${max_spend:.2f} reached" if spent >= max_spend
                       else "cost data missing — spend can no longer be capped reliably")
                lb = " LOWER BOUND" if cost_untrusted else ""
                abort_reason = f"{why} (spent ${spent:.4f}{lb}) before {cid}"
                break

            # The try wraps ONLY the fallible per-cell work (generate → judge → persist). The success
            # bookkeeping + progress callback are OUTSIDE it, so a progress-sink error (e.g. a broken
            # stdout pipe) can't mislabel an already-persisted cell as a failure, and a post-persist
            # error can't roll a durable record back.
            try:
                conv = _generate_and_judge(client, v, fam, adv, rep, families_doc=families_doc,
                                           max_turns=max_turns, context_arm=context_arm)
                append_record(conv, out_path)
            except Exception as e:   # per-cell isolation: one bad cell never aborts the rest of the grid
                failed += 1
                _log_failure(failures, failures_path, now,
                             {"conversation_id": cid, "vignette_id": v.id, "family": fam["name"],
                              "advisor": adv, "replicate": rep}, e)
                emit({"i": idx, "n": len(cells), "id": cid, "status": "fail",
                                 "spent": spent, "error": f"{type(e).__name__}: {e}"})
                continue

            # success path — the record is durably persisted; nothing below can fail the cell
            done.add(cid)
            rec = conv.to_dict()
            c_judge, judge_missing = costmod.judge_cost(rec)
            if costmod.missing_cost_turns(rec) > 0 or judge_missing:
                cost_untrusted = True
            g_flag, g_viol, g_cost = _guard_bookkeeping(conv, guard_log_path, now)
            guard_flagged += g_flag
            guard_violations += g_viol
            spent += costmod.turns_cost(rec) + c_judge + g_cost
            completed += 1
            emit({"i": idx, "n": len(cells), "id": cid, "status": "ok", "spent": spent,
                             "judge": (conv.judgment or {}).get("status"),
                             "complete": conv.metadata.get("complete"), "cost_lower_bound": cost_untrusted})
    else:
        # PARALLEL (independent mode only): workers run generate+judge concurrently; the MAIN thread owns
        # ALL persistence + bookkeeping as futures complete, so no locks are needed (the only worker-shared
        # resource is the key-disjoint, atomic response cache). Budget is best-effort — checked before each
        # submission and "flag & continue" on missing cost (the finite grid bounds true spend) — so the
        # overshoot is at most `concurrency` in-flight cells when the cap trips.
        to_run = []
        for idx, (v, fam, adv, rep) in enumerate(cells):
            cid = cell_id(v.id, fam["name"], adv, rep)
            if cid in done:
                skipped += 1
                emit({"i": idx, "n": len(cells), "id": cid, "status": "skip", "spent": spent})
            else:
                to_run.append((idx, v, fam, adv, rep))

        pending_it = iter(to_run)
        in_flight: dict = {}      # future -> (idx, v, fam, adv, rep)
        exhausted = False
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            while True:
                # fill the pool up to `concurrency`, gating on the (best-effort) cap
                while not exhausted and not aborted and len(in_flight) < concurrency:
                    if spent >= max_spend:
                        aborted = True
                        abort_reason = f"--max-spend ${max_spend:.2f} reached (spent ${spent:.4f})"
                        break
                    nxt = next(pending_it, None)
                    if nxt is None:
                        exhausted = True
                        break
                    idx, v, fam, adv, rep = nxt
                    fut = ex.submit(_generate_and_judge, client, v, fam, adv, rep,
                                    families_doc=families_doc, max_turns=max_turns,
                                    context_arm=context_arm)
                    in_flight[fut] = (idx, v, fam, adv, rep)
                if not in_flight:
                    break   # nothing running and nothing left to submit (exhausted or aborted) => done
                done_futs, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for fut in done_futs:
                    idx, v, fam, adv, rep = in_flight.pop(fut)
                    cid = cell_id(v.id, fam["name"], adv, rep)
                    try:
                        conv = fut.result()
                    except Exception as e:   # per-cell isolation: one bad cell never aborts the others
                        failed += 1
                        _log_failure(failures, failures_path, now,
                                     {"conversation_id": cid, "vignette_id": v.id, "family": fam["name"],
                                      "advisor": adv, "replicate": rep}, e)
                        emit({"i": idx, "n": len(cells), "id": cid, "status": "fail",
                                         "spent": spent, "error": f"{type(e).__name__}: {e}"})
                        continue
                    # main-thread persistence + bookkeeping (single-threaded ⇒ no lock needed)
                    append_record(conv, out_path)
                    done.add(cid)
                    rec = conv.to_dict()
                    c_judge, judge_missing = costmod.judge_cost(rec)
                    if costmod.missing_cost_turns(rec) > 0 or judge_missing:
                        cost_untrusted = True   # FLAG & CONTINUE: parallel does NOT fail-closed on missing cost
                    g_flag, g_viol, g_cost = _guard_bookkeeping(conv, guard_log_path, now)
                    guard_flagged += g_flag
                    guard_violations += g_viol
                    spent += costmod.turns_cost(rec) + c_judge + g_cost
                    completed += 1
                    emit({"i": idx, "n": len(cells), "id": cid, "status": "ok", "spent": spent,
                                     "judge": (conv.judgment or {}).get("status"),
                                     "complete": conv.metadata.get("complete"), "cost_lower_bound": cost_untrusted})

    final_records = load_records(out_path) if out_path.exists() else []
    final_cost = costmod.accumulate(final_records)

    # Arm COMPLETE = every FULL-grid cell reached a terminal state (persisted OR recorded in failures.jsonl).
    # Tolerant by design: a few permanently-failed cells don't block completion; a budget abort
    # does (its unattempted cells are in neither set). Robust across resumes — `done` and the failures
    # file both accumulate. When complete, freeze a deterministic audit sample.
    expected = {cell_id(v.id, fam["name"], adv, rep)
                for v in vigs for adv in advs for rep in range(replicates) for fam in fams}
    failed_ids = ({r.get("conversation_id") for r in load_records(failures_path)}
                  if failures_path.exists() else set())
    complete = expected <= (done | failed_ids)
    audit_sample: list = []
    if complete:
        try:
            audit_sample = select_audit_sample(final_records, seed=client.config.seed)
        except Exception:  # noqa: BLE001 — a sampling bug must NEVER crash a finished run
            print("warning: audit-sample computation failed; manifest carries an empty sample",
                  file=sys.stderr)
            audit_sample = []

    report_fields = {
        "out_path": str(out_path), "n_cells": len(cells), "completed": completed,
        "skipped": skipped, "failed": failed, "aborted": aborted, "abort_reason": abort_reason,
    }
    _write_manifest(
        manifest_path, client=client, vigs=vigs, fams=fams, advs=advs, replicates=replicates,
        max_turns=max_turns, max_spend=max_spend, reproducibility=reproducibility,
        started_at=started_at, ended_at=now(), report_fields=report_fields, cost=final_cost,
        context_arm=context_arm,
        concurrency=concurrency, complete=complete, audit_sample=audit_sample, stack_lock=stack_lock,
        arm=arm_dir.arm,
    )
    # Also as its own file: the sample is RECOMPUTABLE from the records, and an auditor asking "what
    # was sampled?" should not have to parse a 9KB run manifest to find out. The manifest keeps its
    # copy so migrated arms and the viewer keep working (tup.store.ArmDir.audit_sample reads both).
    if complete:
        arm_dir.audit_sample_path.write_text(
            json.dumps({"schema": "tup-audit-sample/1", "arm": arm_dir.arm,
                        "n": len(audit_sample), "conversation_ids": list(audit_sample)},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # POST-HOC LOCK VERIFICATION — read off the RECORDS, not off intent.
    #
    # The preflight asserts what the run was CONFIGURED with. This asserts what it actually DID.
    # A check nobody runs is a comment: every arm leaves stack_lock.verify_records' verdict on
    # disk beside its records, so the question "did this run execute under the lock?" is
    # answered by a file rather than by trusting the launcher.
    _write_lock_verification(arm_dir, final_records, stack_lock, now)
    return RunReport(
        n_cells=len(cells), completed=completed, skipped=skipped, failed=failed,
        aborted=aborted, abort_reason=abort_reason, cost=final_cost,
        failures=failures, out_path=str(out_path), failures_path=str(failures_path),
        manifest_path=str(manifest_path), complete=complete, audit_n=len(audit_sample),
        guard_flagged=guard_flagged, guard_violations=guard_violations,
    )
