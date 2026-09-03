"""The experiment launcher — the entrypoint that generates the experiment's conversations (the other paid paths are rejudge.py and the fidelity study's launcher).

    python scripts/run_experiment.py --run-name full_experiment --max-spend 160 --max-turns 8 --dry-run
    python scripts/run_experiment.py --run-name full_experiment --max-spend 160 --max-turns 8
    python scripts/run_experiment.py --continue 2026-08-06__full_experiment --max-spend 160 --max-turns 8

Both arms run in ONE invocation, main first: if the cap or a crash bites, the primary estimand
survives and the descriptive arm is what gets sacrificed.

WHAT THIS LAUNCHER WILL NOT LET YOU DO, and why each rule exists:

  * **Choose where data goes.** There is no output-path flag. Paths belong to ``tup.store``,
    whose root is a property of the environment (``TUP_RESULTS_ROOT``) — a redirectable output
    flag would let one run's results land in a different checkout.
  * **Inherit a run's identity from a default.** ``--run-name`` is mandatory, and ``--run-name``
    and ``--continue`` are mutually exclusive: a resumed run's name is already inside its id, and
    accepting both invites the two to disagree. A defaulted name can point a fresh launch at a
    completed run's identity, "resuming" most of the new grid as already done and rewriting the
    manifest to claim the new instrument.
  * **Overwrite anything.** There is no ``--no-resume``. Re-running an existing date+run-name MINTS a
    new id rather than truncating; resuming is explicit, via ``--continue``.
  * **Spend without saying how much, or run without saying how long.** ``--max-spend`` and
    ``--max-turns`` are required. Typing the cap IS the authorization, so a preflight estimate is
    printed and a cap below it is refused outright.
  * **Silently change a resumed run's shape.** A slice passed with ``--continue`` that contradicts
    the recorded one is an error, not an override.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path when run directly

from tup.client.cache import ResponseCache
from tup.client.config import REPO_ROOT, load_config
from tup.client.openrouter import OpenRouterClient
from tup.client.top_p import effective_top_p_record, verify_top_p
from tup.harness import estimate as est
from tup.harness.driver import DEFAULT_CONCURRENCY, run_arm
from tup.harness.invocation import build_invocation, conflicting_slice, resolve_arms_to_continue
from tup.harness.mock import dry_run_client
from tup.orchestration.instrument import verify_integrity, working_tree_divergence, write_snapshot
from tup.orchestration.stack_lock import StackLockError, assert_locked_stack, resolve_current
from tup.output import html_viewer
from tup.store import ARM_ORDER, InvalidRunNameError, RunNotFoundError, Store, validate_run_name


def _progress(ev: dict) -> None:
    bar = f"[{ev['i'] + 1}/{ev['n']}]"
    if ev["status"] == "ok":
        flag = "" if ev.get("complete", True) else " INCOMPLETE"
        print(f"{bar} ok   {ev['id']}  judge={ev.get('judge')}{flag}  spent=${ev['spent']:.4f}")
    elif ev["status"] == "skip":
        print(f"{bar} skip {ev['id']}  (already done)")
    elif ev["status"] == "fail":
        print(f"{bar} FAIL {ev['id']}  {ev.get('error')}")


def _csvarg(v, *, flag: str = ""):
    """Comma-separated values, REJECTING duplicates and an all-empty list.

    A duplicate is never intentional and is not harmless: it puts the same cell in the grid twice,
    and because both copies are in flight at once under the default concurrency, the resume
    skip-if-done check cannot see the first before the second starts. Two records then land under
    one conversation_id, inflating every count computed from that arm.

    An all-empty value (``--arms " "``, ``--arms ,``) would silently resolve to "no arms at
    all" — a run that can do nothing yet reports success.
    """
    if v is None:
        return None
    items = [x.strip() for x in v.split(",") if x.strip()]
    if not items:
        raise ValueError(f"{flag} was given but resolved to nothing — drop the flag, or name values")
    dupes = sorted({x for x in items if items.count(x) > 1})
    if dupes:
        raise ValueError(f"{flag} lists {', '.join(repr(d) for d in dupes)} more than once; "
                         f"each value generates its own cells, so a repeat would produce two "
                         f"records under one conversation_id")
    return items


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="TUP experiment launcher.")
    ident = ap.add_mutually_exclusive_group(required=True)
    ident.add_argument("--run-name", default=None,
                       help="run identity: the store mints <today>__<run-name>. Lowercase alphanumeric "
                            "with single underscores; '__' is the run-id field separator and is "
                            "forbidden inside a run name. No default — a run must be named on purpose.")
    ident.add_argument("--continue", dest="continue_run", default=None, metavar="RUN_ID",
                       help="resume an existing run by id. Its recorded invocation.json supplies "
                            "the grid, the slice and the design; only --max-spend, --concurrency "
                            "and --arms may differ freely (a changed --max-turns is an instrument "
                            "change and is refused without --unlock-stack).")
    ap.add_argument("--arms", default=None,
                    help="comma-separated subset of " + ",".join(ARM_ORDER) + " to run. NARROWS "
                         "the arms; it can never add one the run was not commissioned with.")
    ap.add_argument("--dry-run", action="store_true",
                    help="offline mock SDK, $0, full grid; writes under the store's dry_runs/")
    ap.add_argument("--max-spend", type=float, required=True,
                    help="REQUIRED. Cumulative $ cap for the WHOLE RUN incl. judge calls, across "
                         "both arms. Typing this number is the authorization; there is no bypass.")
    ap.add_argument("--max-turns", type=int, required=True,
                    help="REQUIRED. Advisor turns per conversation (locked value: 8). Checked "
                         "against config/locked_stack.yaml before any spend.")
    # default=None so an EXPLICIT value is distinguishable from an unset one; the locked defaults
    # are applied below. Without that distinction --continue could not tell "operator asked for a
    # different replicate count" from "operator said nothing".
    ap.add_argument("--replicates-main", type=int, default=None,
                    help="replicates per cell in the main arm (locked N=3). With --continue it "
                         "must match the run's commissioned grid: a different value is refused.")
    ap.add_argument("--replicates-context", type=int, default=None,
                    help="replicates per cell in the barrier-as-context arm (descriptive, N=1). "
                         "With --continue it must match the run's commissioned grid.")
    ap.add_argument("--vignettes", default=None,
                    help="comma-separated vignette ids to include (default: all in the roster)")
    ap.add_argument("--families", default=None,
                    help="comma-separated condition names to include (default: all seven)")
    ap.add_argument("--advisors", default=None,
                    help="comma-separated advisor providers to include (default: the full slate)")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help=f"conversations in flight at once (default {DEFAULT_CONCURRENCY})")
    ap.add_argument("--unlock-stack", action="store_true",
                    help="proceed even if the resolved configuration contradicts "
                         "config/locked_stack.yaml (the deviation is recorded in every arm's "
                         "manifest). Use only for a deliberate instrument change.")
    return ap


def _write_run_readme(run, invocation, reports, arms, spent, args) -> None:
    """Write the run's README.md — refreshed after every invocation, never write-once.

    It exists for two reasons beyond being readable. Its ``status:`` line is what
    ``tup.store._read_status`` feeds into ``index.json`` and what the viewer uses to decide whether
    a run is a validation smoke; without this file every new run is statusless and unclassifiable.
    And it is the one artifact in the run directory a HUMAN is meant to edit — the status derived
    here is only what the machine can know (did it finish?), not what the run was FOR.

    Guarded: a presentation failure must never change a finished run's exit status.
    """
    try:
        arm_lines, complete = [], True
        for arm in ARM_ORDER:
            a = run.arm(arm)
            if not a.has_records():
                continue
            man = a.manifest() or {}
            done = man.get("complete")
            complete &= bool(done)
            lv = a.lock_verification() or {}
            lock_note = ("lock verified from records" if lv.get("ok")
                         else f"LOCK VERIFICATION FAILED: {'; '.join(lv.get('problems') or [])}"
                         if lv else "lock not verified")
            arm_lines.append(f"- `{arm}/` — {len(a.record_ids())} conversations, "
                             f"{'complete' if done else 'INCOMPLETE'}, {lock_note}")
        aborted = [r for r in reports if r.aborted]
        status = ("dry run (no spend, mock responses)" if args.dry_run else
                  "ABORTED — " + (aborted[0].abort_reason or "see LAUNCH_CMD.txt") if aborted else
                  "complete" if complete else "incomplete — resume with --continue")
        grid = (invocation.get("grid") or {})
        body = [
            f"# {run.run_id}", "",
            f"status: {status}", "",
            "<!-- The status line above is machine-derived: it says whether the run FINISHED, not",
            "     what it was for. Edit it to say what this run IS (e.g. 'EXPERIMENT — the reported",
            "     results', or 'validation smoke'); index.json and the viewer both read it. -->",
            "",
            "## Arms", "",
            *arm_lines,
            "",
            "## Grid", "",
            f"- {len(grid.get('vignettes') or [])} vignettes x {len(grid.get('families') or [])} "
            f"conditions x {len(grid.get('advisors') or [])} advisors",
            f"- replicates: {grid.get('replicates')}",
            f"- arms commissioned: {', '.join(invocation.get('arms') or [])}"
            + (f" (this invocation ran {', '.join(arms)})" if list(arms) != list(invocation.get("arms") or []) else ""),
            "",
            "## Provenance", "",
            "- `invocation.json` — what this run was COMMISSIONED with, written once before any spend.",
            "- `LAUNCH_CMD.txt` — every invocation that has touched it since.",
            "- `<arm>/manifest.json` — what each arm actually DID.",
            "- `<arm>/lock_verification.json` — whether the records themselves carry the locked values.",
            "",
            f"Spend so far: ${spent:,.4f} (cap ${args.max_spend:,.2f}).",
            "",
            "Layout contract: [results/README.md](../../README.md).",
        ]
        run.readme_path.write_text("\n".join(body) + "\n", encoding="utf-8")
        print(f"wrote:  {run.readme_path}")
    except Exception as e:  # noqa: BLE001
        print(f"warning: could not write run README ({type(e).__name__}: {e})", file=sys.stderr)


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    store = Store.from_env()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    framing = "single_message"   # the locked value; asserted against the lock at preflight below
    try:
        slice_filters = {"vignettes": _csvarg(args.vignettes, flag="--vignettes"),
                         "families": _csvarg(args.families, flag="--families"),
                         "advisors": _csvarg(args.advisors, flag="--advisors")}
        arms_requested = _csvarg(args.arms, flag="--arms")
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(2)

    # A replicate count below 1 yields a zero-cell arm that reports complete=True with an
    # empty audit sample — a run that does nothing and says it finished.
    for flag, val in (("--replicates-main", args.replicates_main),
                      ("--replicates-context", args.replicates_context)):
        if val is not None and val < 1:
            print(f"error: {flag} must be at least 1 (got {val}); a zero-cell arm would report "
                  f"itself complete having run nothing")
            sys.exit(2)

    config = load_config()

    # Preflight: the loaded vignette set must match the roster exactly — guards the
    # cohort-default class of bug (a filter silently shrinking the grid) before any money is spent.
    import csv as _csv
    from tup.data.vignettes import load_vignettes as _lv
    roster_path = REPO_ROOT / "config" / "roster.csv"
    with roster_path.open() as _f:
        roster_vids = sorted({r["vignette_id"] for r in _csv.DictReader(_f)})
    loaded_vids = sorted(v.id for v in _lv())
    if loaded_vids != roster_vids:
        print(f"error: loaded vignettes {loaded_vids} != roster vignettes {roster_vids} "
              f"({roster_path.name}); fix the loader filters or regenerate the roster.")
        sys.exit(2)

    # ------------------------------------------------------------------ identity + intent
    if args.continue_run:
        try:
            run = store.require_run(args.continue_run, dry_run=args.dry_run)
        except RunNotFoundError as e:
            print(f"error: {e}")
            sys.exit(2)
        invocation = run.invocation()
        if invocation is None:
            # A sliced grid CANNOT be reconstructed from partial records: "sliced to three advisors"
            # and "crashed before reaching advisors four and five" are byte-identical on disk.
            print(f"error: {run.run_id} has no invocation.json, so what it was commissioned with is "
                  f"unknown — a slice and a crash are indistinguishable from records alone.")
            print("Launch a new run with --run-name instead of guessing this one's grid.")
            sys.exit(2)
        conflicts = conflicting_slice(invocation, slice_filters)
        if conflicts:
            print(f"error: --continue {run.run_id} was commissioned with a different slice:")
            for c in conflicts:
                print(f"  - {c}")
            print("A slice is part of a run's identity, not a per-invocation override. Drop the "
                  "slice flags to resume as commissioned, or use --run-name for a new run.")
            sys.exit(2)

        # Checked HERE, alongside the slice, and NOT after the "nothing to do" early exit —
        # otherwise a run whose arms are already complete accepts a contradicting replicate count
        # and exits 0 without a word, the silence this guard exists to break.
        asked = {k: v for k, v in (("main", args.replicates_main),
                                   ("context", args.replicates_context)) if v is not None}
        recorded = dict(invocation["grid"]["replicates"])
        clashing = {k: (recorded.get(k), v) for k, v in asked.items() if recorded.get(k) != v}
        if clashing:
            print(f"error: --continue {run.run_id} was commissioned with replicates {recorded}, "
                  f"but this invocation asked for "
                  + ", ".join(f"{k}={v} (recorded {was})" for k, (was, v) in sorted(clashing.items())))
            print("Replicate count is part of a run's commissioned grid, not a per-invocation "
                  "override. Drop the flag to resume as commissioned, or use --run-name for a new run.")
            sys.exit(2)
        try:
            todo, states = resolve_arms_to_continue(run, invocation, arms_requested)
        except ValueError as e:
            print(f"error: {e}")
            sys.exit(2)
        # An arm can be complete BY RECORDS and still be missing the files written at arm end — a
        # crash between the last record and the manifest leaves exactly that; excluded from
        # `todo`, it would report "nothing to do" and stay permanently unmanifested.
        # Re-including it costs nothing (every cell is skipped)
        # and run_arm regenerates all three derived files on its way out.
        for arm in ARM_ORDER:
            st = states.get(arm) or {}
            if not st.get("in_invocation") or not st.get("complete") or arm in todo:
                continue
            a = run.arm(arm)
            absent = [n for n, pth in (("manifest.json", a.manifest_path),
                                       ("audit_sample.json", a.audit_sample_path),
                                       ("lock_verification.json", a.lock_verification_path))
                      if not pth.exists()]
            if absent and (arms_requested is None or arm in arms_requested):
                print(f"  {arm}: complete, but missing {', '.join(absent)} — regenerating "
                      f"(no conversations will be re-run)")
                todo.append(arm)
        todo = [a for a in ARM_ORDER if a in todo]      # keep main-first order
        for arm, st in states.items():
            if not st["in_invocation"]:
                continue
            tail = "complete" if st["complete"] else f"{len(st['missing'])} missing"
            print(f"  {arm}: {st['done']}/{st['expected']} done, {st['failed']} failed — {tail}")
        if not todo:
            print(f"{run.run_id}: every commissioned arm is already complete — nothing to do.")
            sys.exit(0)
        vig_ids = invocation["grid"]["vignettes"]
        fam_names = invocation["grid"]["families"]
        adv_names = invocation["grid"]["advisors"]
        replicates = dict(invocation["grid"]["replicates"])
        run_id = run.run_id
        # Estimate only what is actually LEFT — a resumed run that quotes the full grid's price
        # would demand a cap it cannot possibly spend, and the cap is the authorization.
        n_conversations = sum(len(states[a]["missing"]) for a in todo)
    else:
        try:
            run_name = validate_run_name(args.run_name)
        except InvalidRunNameError as e:
            print(f"error: {e}")
            sys.exit(2)
        run_id, notice = store.mint_run_id_with_notice(run_name, today, dry_run=args.dry_run)
        if notice:
            print(f"notice: {notice}")
        run = store.run(run_id, dry_run=args.dry_run)
        invocation = None
        todo = [a for a in ARM_ORDER if arms_requested is None or a in arms_requested]
        if arms_requested:
            unknown = [a for a in arms_requested if a not in ARM_ORDER]
            if unknown:
                print(f"error: unknown arm(s) {unknown}; the arms are {list(ARM_ORDER)}")
                sys.exit(2)
        vig_ids = slice_filters["vignettes"] or sorted(v.id for v in _lv())
        fam_names = slice_filters["families"]
        adv_names = slice_filters["advisors"] or list(config.advisors)
        replicates = {"main": 3 if args.replicates_main is None else args.replicates_main,
                      "context": 1 if args.replicates_context is None else args.replicates_context}

    # Resolve the slice names to the objects the driver wants, validating every one.
    from tup.data.prompts import get_family as _gf, load_families as _lf
    from tup.data.vignettes import load_vignettes as _lvs
    by_id = {v.id: v for v in _lvs()}
    missing = [x for x in vig_ids if x not in by_id]
    if missing:
        print(f"error: unknown vignette id(s) {missing}; known ids: {sorted(by_id)}")
        sys.exit(2)
    _fams = _lf()
    known_fams = [f["name"] for f in _fams["families"]]
    if fam_names is None:
        fam_names = known_fams
    unknown = [x for x in fam_names if x not in known_fams]
    if unknown:
        print(f"error: unknown condition name(s) {unknown}; known conditions: {known_fams}")
        sys.exit(2)
    # An advisor slug outside the configured slate must be refused before a run id is minted:
    # validate_models() checks the configured roster, not the subset this invocation asked for.
    known_advs = list(config.advisors)
    unknown_advs = [a for a in adv_names if a not in known_advs]
    if unknown_advs:
        print(f"error: unknown advisor(s) {unknown_advs}; the configured slate is {known_advs}")
        sys.exit(2)
    vig_objs = [by_id[x] for x in vig_ids]
    fam_objs = [_gf(_fams, x) for x in fam_names]

    if not args.continue_run:
        n_conversations = sum(len(vig_ids) * len(fam_names) * len(adv_names) * replicates[a]
                              for a in todo)

    # ------------------------------------------------------------------ budget preflight
    # --max-spend is CUMULATIVE over the run, so a resume must count what the run already spent.
    # Without this, a resume cap below what the run has already spent passes preflight and then
    # aborts on its first cell, reporting a total no-op as a successful invocation.
    already = 0.0
    if args.continue_run:
        from tup.output import cost as _costmod
        already = sum(_costmod.accumulate(a.records()).total_usd for a in run.arms())
        print(f"resume: this run has already spent ${already:,.4f}")
    estimate = est.estimate_usd(n_conversations)
    for line in est.format_preflight(estimate + already, args.max_spend,
                                     n_conversations=n_conversations):
        print(line)
    if est.exceeds_cap(estimate + already, args.max_spend):
        print(f"error: --max-spend ${args.max_spend:,.2f} is below the ${estimate + already:,.2f} "
              f"needed (${already:,.2f} already spent + ${estimate:,.2f} estimated for "
              f"{n_conversations:,} remaining conversations). The cap is cumulative over the run, so "
              f"this invocation would abort before its first cell. Raise the cap or narrow the grid.")
        sys.exit(2)

    # ------------------------------------------------------------------ instrument lock
    print("preflight: locked-stack check (config/locked_stack.yaml) ...")
    try:
        lock_record = assert_locked_stack({"patient_framing": framing, "max_turns": args.max_turns},
                                          allow_override=args.unlock_stack)
    except StackLockError as e:
        print(f"error: {e}")
        sys.exit(2)
    if lock_record["mismatches"]:
        print("  ⚠ OVERRIDDEN — this run deviates from the locked stack:")
        for m in lock_record["mismatches"]:
            print(f"    - {m}")
    else:
        print(f"  OK — matches lock '{lock_record['lock_name']}' "
              f"({', '.join(f'{k}={v}' for k, v in lock_record['checked'].items())})")

    # A resumed run's instrument must still match the one its earlier arms were written with —
    # two halves of one run produced by different prompt, families or guard versions are not one
    # experiment. (The resume guard operates per run.)
    if args.continue_run:
        prev = ((invocation.get("stack_lock") or {}).get("checked") or {})
        # Compare against THIS invocation's own resolved lock record, NOT resolve_current().
        # resolve_current() cannot see patient_framing at all — it reads terms out of files and the
        # code, and the framing is a property of the INVOCATION, reaching `checked` only via the
        # dict passed to assert_locked_stack above. So comparing against resolve_current()
        # intersected the framing away and let a framing drift resume unchallenged — the
        # recorded-but-never-compared defect class the lock exists to close.
        # (max_turns IS in resolve_current(), but from runner.DEFAULT_MAX_TURNS — the code default,
        # not this invocation's value. lock_record has the value actually passed, which is the one
        # a resume must be checked against.)
        now_checked = dict(lock_record.get("checked") or {})
        differing = {k: (prev.get(k), now_checked.get(k)) for k in prev
                     if k in now_checked and prev[k] != now_checked[k]}
        if differing and not args.unlock_stack:
            print(f"error: {run_id} was commissioned with a different instrument: "
                  + ", ".join(f"{k} was {a!r}, now {b!r}" for k, (a, b) in sorted(differing.items())))
            print("Resuming would mix instruments within one run — launch a new run with --run-name.")
            sys.exit(2)

    # ------------------------------------------------------------------ client + live gates
    if args.dry_run:
        client = dry_run_client(config)               # mock SDK, no cache
        cache_note = f"none (dry-run mock); live would use {store.cache_dir}"
    else:
        client = OpenRouterClient(config=config, cache=ResponseCache(cache_dir=store.cache_dir))
        cache_note = str(store.cache_dir)

    print(f"run:    {run_id}   arms: {', '.join(todo)}")
    print(f"store:  {run.path}")
    print(f"cache:  {cache_note}")
    print(f"grid:   {len(vig_ids)} vignettes x {len(fam_names)} conditions x {len(adv_names)} "
          f"advisors, replicates {replicates}")

    print(f"preflight: validate_models() {'(mock)' if args.dry_run else '(live)'} ...")
    slugs = client.validate_models()
    print(f"  OK — {len(slugs)} slugs reachable: {', '.join(slugs)}")

    # top_p reproducibility GATE (tup/client/top_p.py): offline for --dry-run, live for the real run.
    print(f"preflight: verify_top_p() {'(offline)' if args.dry_run else '(live)'} ...")
    ok, drift = verify_top_p(live=not args.dry_run)
    if not ok:
        print("  TOP_P DRIFT — aborting before any spend. Re-run scripts/check_top_p.py and update")
        print("  tup/client/top_p.py:EFFECTIVE_TOP_P to match before launching:")
        for d in drift:
            print(f"   - {d}")
        sys.exit(2)
    top_p_verified_at = datetime.now(timezone.utc).isoformat()
    print(f"  OK — top_p provenance verified ({top_p_verified_at})")
    reproducibility = {"effective_top_p": effective_top_p_record(),
                       "top_p_verified_at": top_p_verified_at}

    # ------------------------------------------------------------------ write-once intent record
    run.path.mkdir(parents=True, exist_ok=True)
    if invocation is None:
        invocation = build_invocation(
            run_id=run_id, started_at=datetime.now(timezone.utc).isoformat(), run_name=run_name,
            dry_run=args.dry_run, vignettes=vig_ids, families=fam_names, advisors=adv_names,
            replicates=replicates, arms=todo, seed=config.seed, concurrency=args.concurrency,
            max_spend=args.max_spend, estimate_usd=estimate, lock_record=lock_record,
            slice_filters=slice_filters, reproducibility=reproducibility)
        # EXCLUSIVE create — this write, not the earlier mint, is what reserves the identity.
        # mint_run_id_with_notice() only READS the disk, so two launches racing on the same new
        # date+run-name would both see "free", both take the id, and the second would overwrite
        # the first's write-once record. O_EXCL makes the loser lose loudly instead of silently.
        try:
            with open(run.invocation_path, "x", encoding="utf-8") as f:
                json.dump(invocation, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except FileExistsError:
            print(f"error: {run.invocation_path} appeared while this invocation was starting — "
                  f"another launcher took {run_id} first.")
            print("Nothing was written. Re-run: the store will mint the next free id.")
            sys.exit(2)
        print(f"wrote:  {run.invocation_path}")

    # ------------------------------------------------------------------ instrument snapshot
    # The run carries byte copies of the prompt/config/vignette files it runs under, so verifying
    # it later never depends on the working tree (tup/orchestration/instrument.py). Write-once: a
    # resume must run the SAME bytes, so it verifies instead of rewriting — a working tree that has
    # drifted from the snapshot would mix two instruments inside one run.
    if not run.has_instrument():
        note = None
        if args.continue_run:
            note = ("written at a resume, not at first launch — conversations recorded before "
                    "this point ran under bytes this snapshot cannot vouch for; their recorded "
                    "hashes are the authority there")
        manifest = write_snapshot(run.instrument_dir, note=note)
        print(f"wrote:  {run.instrument_manifest_path} ({len(manifest['files'])} files)")
    else:
        broken = verify_integrity(run.instrument_dir)
        if broken:
            print(f"error: {run_id}'s instrument snapshot fails its own manifest:")
            for b in broken:
                print(f"  - {b}")
            print("A snapshot is write-once; restore it from git rather than relaunching over it.")
            sys.exit(2)
        drifted = working_tree_divergence(run.instrument_dir)
        if drifted and not args.unlock_stack:
            print(f"error: the working tree no longer matches {run_id}'s instrument snapshot: "
                  + ", ".join(drifted))
            print("Resuming would mix instruments within one run — restore these files to the "
                  "snapshot's bytes, or launch a new run with --run-name.")
            sys.exit(2)
        if drifted:
            print(f"  ⚠ OVERRIDDEN — resuming despite instrument drift in: {', '.join(drifted)}")

    if not run.launch_cmd_path.exists():
        run.launch_cmd_path.write_text(
            "# one line per invocation; the first is the run as commissioned.\n"
            "# The INTENT is in invocation.json — this is the audit trail of who touched it since.\n",
            encoding="utf-8")
    with run.launch_cmd_path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}  "
                f"{shlex.join([sys.executable, 'scripts/run_experiment.py', *sys.argv[1:]])}\n")

    # ------------------------------------------------------------------ execute, main arm first
    prior_spend = 0.0
    reports = []
    for arm in todo:
        print(f"\n=== arm: {arm} ===")
        report = run_arm(
            client, run.arm(arm),
            max_spend=args.max_spend, max_turns=args.max_turns, replicates=replicates[arm],
            vignettes=vig_objs, families=fam_objs, advisors=adv_names,
            prior_spend=prior_spend, reproducibility=reproducibility, stack_lock=lock_record,
            concurrency=args.concurrency, progress=_progress,
        )
        print()
        print(report.summary())
        reports.append(report)
        prior_spend += report.cost.total_usd
        if report.aborted:
            print(f"** {arm} aborted; not starting the remaining arm(s) **")
            break

    print(f"\ntotal spend this run: ${prior_spend:,.4f} of ${args.max_spend:,.2f}")
    _write_run_readme(run, invocation, reports, todo, prior_spend, args)

    # Keep the catalogue and the viewer current so a finished run is browsable without a second
    # command. Guarded: a presentation failure must not change the run's exit status.
    if not args.dry_run:
        for label, fn in (("index", store.write_index), ("viewer", html_viewer.build)):
            try:
                print(f"{label} rebuilt: {fn()}")
            except Exception as e:  # noqa: BLE001
                print(f"warning: {label} rebuild failed ({type(e).__name__}: {e})", file=sys.stderr)

    sys.exit(1 if any(r.aborted or r.failed for r in reports) else 0)


if __name__ == "__main__":
    main()
