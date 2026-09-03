#!/usr/bin/env python
"""Re-judge persisted conversations WITHOUT regenerating them.

Why this exists: the driver's resume done-set is conversation_id-only, so a record whose judgment
came back ``unparseable`` (both attempts failed), ``panel_incomplete`` (fewer than two of the 3
panel seats parse — one dead seat still aggregates via the two-seat fallback) or ``judge_failed`` (the judge call itself raised) is skipped on every
resume and silently excluded from every metric — with no path to recover it. Deleting the record
doesn't help either: the response cache replays the exact failed judge output byte-for-byte. This
script re-attaches a FRESH judgment to existing records by conversation_id, preserving conversation
identity (turns, seed, metadata) exactly.

Failures are isolated PER RECORD: a raising judge call leaves that record untouched (so it keeps
its failing status and a re-run retries it) and the batch continues. Partial progress is written:
the arm's ``records.jsonl`` is checkpointed every ``CHECKPOINT_EVERY`` completed records (the
whole file, untouched records verbatim), so a killed process loses at most one checkpoint's worth
of paid calls, and a re-run picks up where it stopped — under ``--all`` a record that already
carries the CURRENT rubric's hash with a parsed verdict is not re-judged again.

Judge calls run with ``cache=None`` — deliberately uncached, both to bypass the frozen failed
outputs and because writing rejudge responses into the run cache would break run-vs-rejudge
provenance. Generation is never touched: only ``judgment`` is replaced.

The rotation index mirrors the driver exactly (``rotation = int(vignette_id) + replicate`` —
tup/harness/driver.py), so a re-judged record gets the SAME panel seats the roster/config assign
to that conversation.

Money and the lock:
  - ``--max-spend`` is REQUIRED — typing the cap is the authorization, as for the launcher. Spend
    is read off the client (``OpenRouterClient.spent_usd``, summed at the wire from every
    response's ``usage.cost``), never reconstructed from records, so a seat's corrective retry and
    a response the record later drops are both counted. Once the cap is reached no further record
    is dispatched; at most ``--concurrency`` in-flight records can overshoot it. Records not
    reached keep their prior judgment verbatim. A response without cost metadata makes the total
    a lower bound, and the script says so.
  - ``--concurrency`` (default 16, the driver's production setting) runs records through a thread
    pool; the panel's seats stay sequential within a record, exactly as in the driver. Output
    order and per-record isolation are unchanged.
  - The locked stack is asserted before the first call (config/locked_stack.yaml): a re-judge can
    never run under a rubric the lock does not name. There is no override flag.
  - Every invocation appends one line to the run's ``LAUNCH_CMD.txt``, like the launcher.

Usage:
  python scripts/rejudge.py 2026-08-06__full_experiment --arm main --max-spend 20     # broken judgments only
  python scripts/rejudge.py ... --statuses unparseable --max-spend 5                  # default: all three above
  python scripts/rejudge.py ... --all --max-spend 70 --concurrency 16                 # every judgeable record

It rewrites the arm's ``records.jsonl`` in place (after a ``.bak``) because a re-judged conversation
is the SAME conversation — the transcript, the seed and the identity are untouched, and only the
secondary outcome is replaced. A copy under a new run id would claim a run that never happened.

Exit status: 0 if nothing needed re-judging or everything succeeded; 1 if any record failed or the
cap stopped the batch (the untouched records are exactly what a re-run retries); 2 on a preflight
refusal (unknown run, lock mismatch, a configured slug missing from the live model list).
"""
from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.client.openrouter import OpenRouterClient  # noqa: E402
from tup.data.prompts import load_judge_prompt  # noqa: E402
from tup.data.vignettes import load_vignettes  # noqa: E402
from tup.judge.judge import judge_conversation_panel  # noqa: E402
from tup.orchestration.stack_lock import StackLockError, assert_locked_stack  # noqa: E402
from tup.orchestration.transcript import Conversation  # noqa: E402
from tup.output.persist import load_records, save_records  # noqa: E402
from tup.store import ARMS, RunNotFoundError, Store  # noqa: E402

# ``judge_failed`` belongs here: the driver PERSISTS a conversation
# whose judge raised (rather than discard the irreplaceable transcript), stamping this status and
# pointing recovery at this script — see tup/tests/test_harness.py::
# test_judge_failure_is_persisted_not_discarded — so the default filter must cover it, or the
# documented recovery path matches nothing on exactly the records it exists to fix.
DEFAULT_STATUSES = ("unparseable", "panel_incomplete", "judge_failed")

#: In-flight records in the parallel path. The driver's production setting (tup/harness/driver.py).
DEFAULT_CONCURRENCY = 16

#: Completed records between checkpoints of the arm's records.jsonl (see module docstring).
CHECKPOINT_EVERY = 25


def needs_rejudge(record: dict, statuses: tuple, rejudge_all: bool,
                  current_sha: str | None = None) -> bool:
    if not record.get("metadata", {}).get("complete", True):
        return False  # convention: incomplete conversations are never judged (no defined T => ToD uninterpretable)
    j = record.get("judgment") or {}
    if rejudge_all:
        # Idempotent resume: a parsed verdict already produced under the CURRENT rubric is done.
        if (current_sha is not None and j.get("status") == "judged"
                and (j.get("judge_prompt") or {}).get("sha256") == current_sha):
            return False
        return True
    return j.get("status") in statuses


def rejudge_records(
    client: OpenRouterClient,
    records: list[dict],
    *,
    statuses: tuple = DEFAULT_STATUSES,
    rejudge_all: bool = False,
    progress=None,
    on_error=None,
    concurrency: int = 1,
    max_spend: float | None = None,
    report: dict | None = None,
    checkpoint=None,
    checkpoint_every: int = CHECKPOINT_EVERY,
) -> tuple[list[dict], int, int]:
    """Return (records-with-fresh-judgments, n_rejudged, n_failed). Order and identity preserved.

    A judge call that RAISES (upstream 429, transport error, a dead seat) is caught **per record**:
    the original record is appended verbatim — so it keeps its failing status and the next run picks
    it up again — and the loop continues — one transient error must never discard every record already
    re-judged in the batch (those calls run uncached by design, so lost progress is lost spend).

    ``max_spend`` is checked against the client's wire-level spend (delta since this call began)
    before every dispatch; once reached, the remaining target records are left verbatim and
    ``report["capped"]`` / ``report["deferred"]`` say so. ``concurrency`` > 1 dispatches records to a
    thread pool (seats stay sequential inside a record); the MAIN thread owns every callback and
    every write into the output list, so no locks are needed here.

    ``checkpoint(out)`` is called from the main thread after every ``checkpoint_every`` completed
    records with the current output list (untouched records verbatim), so a caller can persist
    partial progress; the caller still writes the final state itself.

    ``SystemExit`` (missing vignette) is deliberately NOT caught — that is a configuration error
    that every record would hit, not a transient one worth continuing past — and it is raised before
    any call is made.
    """
    vignettes = {v.id: v for v in load_vignettes(require_locked=False)}
    current_sha = load_judge_prompt().sha256
    targets = [i for i, rec in enumerate(records)
               if needs_rejudge(rec, statuses, rejudge_all, current_sha)]
    for i in targets:
        if records[i]["vignette_id"] not in vignettes:
            raise SystemExit(f"vignette {records[i]['vignette_id']!r} not found for {records[i]['conversation_id']}")

    out: list[dict] = list(records)
    n = 0
    n_failed = 0
    capped = False
    deferred = 0
    spent_at_start = float(getattr(client, "spent_usd", 0.0))

    def spent() -> float:
        return float(getattr(client, "spent_usd", 0.0)) - spent_at_start

    def over_cap() -> bool:
        return max_spend is not None and spent() >= max_spend

    def work(i: int) -> dict:
        rec = records[i]
        vignette = vignettes[rec["vignette_id"]]
        conv = Conversation.from_record(rec)
        rotation = int(vignette.id) + conv.replicate  # mirrors tup/harness/driver.py
        judge_conversation_panel(client, conv, vignette, rotation_index=rotation)
        fresh = dict(rec)
        fresh["judgment"] = conv.judgment
        return fresh

    def settle(i: int, fresh: dict | None, err: Exception | None) -> None:
        nonlocal n, n_failed
        rec = records[i]
        if err is not None:
            n_failed += 1                      # unchanged: keeps its failing status, so a later run retries it
            if on_error:
                on_error(rec["conversation_id"], err)
            return
        out[i] = fresh
        n += 1
        if progress:
            progress(rec["conversation_id"], fresh["judgment"].get("status"))
        if checkpoint and checkpoint_every > 0 and n % checkpoint_every == 0:
            checkpoint(out)

    if concurrency <= 1:
        for k, i in enumerate(targets):
            if over_cap():
                capped = True
                deferred = len(targets) - k
                break
            try:
                fresh = work(i)
            except Exception as e:  # noqa: BLE001 — one dead seat must not discard the whole batch
                settle(i, None, e)
                continue
            settle(i, fresh, None)
    else:
        pending = iter(targets)
        in_flight: dict = {}
        exhausted = False
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            while True:
                # fill the pool up to `concurrency`, gating on the cap before each dispatch
                while not exhausted and not capped and len(in_flight) < concurrency:
                    if over_cap():
                        capped = True
                        break
                    nxt = next(pending, None)
                    if nxt is None:
                        exhausted = True
                        break
                    in_flight[ex.submit(work, nxt)] = nxt
                if not in_flight:
                    break
                done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for fut in done:
                    i = in_flight.pop(fut)
                    try:
                        fresh = fut.result()
                    except Exception as e:  # noqa: BLE001 — per-record isolation, as in the serial path
                        settle(i, None, e)
                        continue
                    settle(i, fresh, None)
        if capped:
            deferred = sum(1 for _ in pending)

    if report is not None:
        report.update(capped=capped, deferred=deferred, spent_usd=spent(),
                      calls_missing_cost=int(getattr(client, "calls_missing_cost", 0)))
    return out, n, n_failed


def _append_launch_cmd(run, argv: list[str]) -> None:
    """One line per invocation, like the launcher: the audit trail of who touched the run since."""
    if not run.launch_cmd_path.exists():
        run.launch_cmd_path.write_text(
            "# one line per invocation; the first is the run as commissioned.\n"
            "# The INTENT is in invocation.json — this is the audit trail of who touched it since.\n",
            encoding="utf-8")
    with run.launch_cmd_path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}  "
                f"{shlex.join([sys.executable, 'scripts/rejudge.py', *argv])}\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id", help="run id in the store, e.g. 2026-08-06__full_experiment (or a study id with --study)")
    ap.add_argument("--arm", required=True,
                    help=f"which arm to re-judge: one of {list(ARMS)} for a run; the arm's directory name for a study")
    ap.add_argument("--study", action="store_true",
                    help="the id names a STUDY (results/studies/<id>); its arms are free-form. No launch trail "
                         "is written (studies carry none).")
    ap.add_argument("--statuses", default=",".join(DEFAULT_STATUSES),
                    help=f"comma-separated judgment statuses to re-judge (default: {','.join(DEFAULT_STATUSES)})")
    ap.add_argument("--all", action="store_true", help="re-judge every complete record regardless of status")
    ap.add_argument("--max-spend", type=float, required=True,
                    help="USD cap for THIS invocation (required: typing the cap is the authorization). "
                         "Checked before every dispatch; overshoot is at most --concurrency records.")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help=f"in-flight records (default {DEFAULT_CONCURRENCY}, the driver's setting); 1 = serial")
    args = ap.parse_args(argv)
    if args.max_spend < 0 or args.concurrency < 1:
        print("error: --max-spend must be >= 0 and --concurrency >= 1", file=sys.stderr)
        return 2

    store = Store.from_env()
    if args.study:
        run = store.study(args.run_id)
        if not run.exists:
            print(f"error: no study {args.run_id!r} in {store.root}", file=sys.stderr)
            return 2
    else:
        if args.arm not in ARMS:
            print(f"error: --arm must be one of {list(ARMS)} for a run (pass --study for a study)", file=sys.stderr)
            return 2
        try:
            run = store.require_run(args.run_id)
        except RunNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    in_path = run.arm(args.arm).records_path
    if not in_path.exists():
        print(f"error: {args.run_id} has no {args.arm} arm records at {in_path}", file=sys.stderr)
        return 2

    # ---- preflight: the lock, then the live slug list — before the first dollar ---------------
    print("preflight: locked-stack check (config/locked_stack.yaml) ...")
    try:
        assert_locked_stack({})
    except StackLockError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    client = OpenRouterClient(cache=None)  # UNCACHED judge calls: see module docstring
    try:
        client.validate_models()
    except Exception as e:  # noqa: BLE001 — a retired judge-seat slug must stop the batch, not one seat
        print(f"error: model validation failed: {e}", file=sys.stderr)
        return 2

    records = load_records(in_path)
    statuses = tuple(s.strip() for s in args.statuses.split(",") if s.strip())
    if not args.study:
        _append_launch_cmd(run, argv)

    bak = in_path.with_suffix(in_path.suffix + ".bak")

    def _write(current: list[dict]) -> None:
        # The .bak is the pre-re-judge original: taken once, NEVER overwritten — a second pass
        # (or a resume after a kill) must not replace it with a partially re-judged file.
        if not bak.exists():
            shutil.copy2(in_path, bak)
        save_records(current, in_path)

    report: dict = {}
    fresh, n, n_failed = rejudge_records(
        client, records, statuses=statuses, rejudge_all=args.all,
        progress=lambda cid, st: print(f"  rejudged {cid}: {st}", flush=True),
        on_error=lambda cid, e: print(f"  FAILED   {cid}: {type(e).__name__}: {e}", file=sys.stderr, flush=True),
        concurrency=args.concurrency, max_spend=args.max_spend, report=report,
        checkpoint=lambda current: (_write(current), print("  checkpoint written", flush=True)),
        checkpoint_every=CHECKPOINT_EVERY,
    )
    bound = " (LOWER BOUND: {} response(s) carried no cost metadata)".format(report["calls_missing_cost"]) \
        if report.get("calls_missing_cost") else ""
    print(f"spent ${report['spent_usd']:.4f} of the ${args.max_spend:.2f} cap{bound}")
    if report.get("capped"):
        print(f"  cap reached: {report['deferred']} target record(s) were not dispatched and keep "
              f"their prior judgment — re-run to continue", file=sys.stderr)

    if n == 0 and n_failed == 0 and not report.get("capped"):
        print(f"nothing to re-judge in {in_path} (statuses={statuses}, all={args.all})")
        return 0
    if n == 0:
        # Nothing succeeded. Writing would only rewrite the file byte-identically — leave it
        # alone and report a non-zero status.
        print(f"no record was re-judged ({n_failed} failed); {in_path} left unchanged",
              file=sys.stderr)
        return 1
    _write(fresh)
    print(f"re-judged {n}/{len(records)} records in place ({in_path}); original kept at {bak}")
    if n_failed:
        print(f"  {n_failed} record(s) FAILED and were kept unchanged — re-run to retry them")
    # What a caller actually wants to know: how many still carry a status this run targets.
    outstanding = sum(1 for r in fresh if ((r.get("judgment") or {}).get("status") in statuses))
    print(f"  {outstanding} record(s) still carry a status in {statuses}")
    return 1 if (n_failed or report.get("capped")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
