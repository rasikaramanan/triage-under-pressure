#!/usr/bin/env python
"""Patient-framing A/B — matched-pair test of role-swap vs single-message patient framing.

ARCHIVED LAUNCHER (one-shot; completed 2026-08-05). It is kept beside the study's records as
the execution record. It cannot be re-run against the current codebase: the role-swap patient
framing it exercised was removed from the runner after this study settled the question.

Design and analysis plan fixed in advance: docs/validation/framing_ab/PREREGISTRATION.md.

Every cell (vignette, family, advisor, replicate 0) is run TWICE — once per framing — against one
shared response cache. The per-conversation seed is framing-independent, so the advisor's response 1
(which precedes any patient-LLM message) has an identical cache key in both arms and is served
byte-identically to the second arm: the pair starts from exactly the same point and diverges only
because the patient simulator was constructed differently.

Writes one ARM per framing so conversation ids can collide across arms and still pair cleanly.
This is a STUDY, not a run: its arms are the two things being compared, so they are named for them
rather than forced into the run vocabulary of main/context.
  results/studies/<date>__framing_ab/{roleswap,single_message}/records.jsonl (+ sidecars)
"""
from __future__ import annotations

import json
import sys
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.client.cache import ResponseCache
from tup.client.config import REPO_ROOT, load_config
from tup.client.openrouter import OpenRouterClient
from tup.client.top_p import verify_top_p
from tup.data.prompts import get_family, load_families
from tup.data.vignettes import load_vignette
from tup.harness.driver import _generate_and_judge, _guard_bookkeeping
from tup.output.persist import append_record, load_records
from tup.store import Store

ADV = ["openai", "anthropic", "meta", "google", "xai"]
BARRIER_VIGNETTES = ["012", "011", "005", "001", "010", "009", "004", "003"]
BARRIER_FAMILIES = ["caregiving", "cost_medical_debt"]
CONTROL_VIGNETTES = ["012", "005", "001"]
FRAMINGS = ["roleswap", "single_message"]
MAX_SPEND = 20.0
CONCURRENCY = 12
STUDY_NAME = "framing_ab"


def build_cells() -> list[tuple[str, str, str, int]]:
    """Deterministic cell list; cell = (vignette, family, advisor, replicate)."""
    cells, seen = [], set()

    def add(vid, fam, adv):
        key = (vid, fam, adv, 0)
        if key not in seen:
            seen.add(key)
            cells.append(key)

    for vid in BARRIER_VIGNETTES:
        for fam in BARRIER_FAMILIES:
            for adv in ADV:
                add(vid, fam, adv)
    for vid in CONTROL_VIGNETTES:
        for adv in ADV:
            add(vid, "control", adv)
    return cells


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cells (pilot check)")
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY,
                    help="in-flight conversations (lower this on upstream 429s)")
    args = ap.parse_args()
    globals()["CONCURRENCY"] = args.concurrency
    cells = build_cells()
    if args.limit:
        cells = cells[:args.limit]
        print(f"LIMIT: first {args.limit} cells only")
    print(f"cells: {len(cells)}  ->  {len(cells) * len(FRAMINGS)} conversations "
          f"({len(cells)} matched pairs)")

    config = load_config()
    store = Store.from_env()
    cache_dir = store.cache_dir
    client = OpenRouterClient(config=config, cache=ResponseCache(cache_dir=cache_dir))
    families_doc = load_families()
    study = store.study_for_run_name(STUDY_NAME, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    arms = {fr: study.arm(fr).mkdir() for fr in FRAMINGS}

    print(f"cache: {cache_dir}")
    print(f"advisor models: {[client.resolve_model('advisor', provider=a) for a in ADV]}")
    print(f"patient: {client.resolve_model('patient')} · guard: {config.guard_model} · "
          f"judge panel: {config.judge_panel}")
    print("preflight: validate_models() ...")
    client.validate_models()
    print("preflight: verify_top_p() ...")
    ok, drift = verify_top_p(live=True, config=config)
    if not ok:
        for d in drift:
            print(f"  DRIFT: {d}")
        sys.exit(2)
    print("  OK")

    # resume: skip (arm, conversation_id) pairs already persisted
    done: dict[str, set] = {}
    for fr in FRAMINGS:
        p = arms[fr].records_path
        done[fr] = {r.get("conversation_id") for r in (load_records(p) if p.exists() else [])}

    todo = [(fr, c) for c in cells for fr in FRAMINGS
            if f"{c[0]}__{c[1]}__{c[2]}__r{c[3]}" not in done[fr]]
    print(f"todo: {len(todo)} conversations (skipping {len(cells) * len(FRAMINGS) - len(todo)} done)")

    from tup.output import cost as costmod
    spent = 0.0
    for fr in FRAMINGS:
        p = arms[fr].records_path
        if p.exists():
            spent += costmod.accumulate(load_records(p)).total_usd
    print(f"prior spend in these files: ${spent:.4f}")

    completed = failed = 0
    flagged = accepted_flag = 0
    started = datetime.now(timezone.utc).isoformat()
    spent_box = [spent]
    stop = [False]

    def run_arm(fr: str, arm_cells: list) -> None:
        """One complete pass over the cells for a single framing.

        The arms run SEQUENTIALLY (all of role-swap, then all of single-message) rather than
        interleaved: response 1 precedes any patient-LLM message and has the same cache key in both
        arms, so the second arm reads the first arm's cached response 1 and every pair starts from a
        byte-identical first advisor turn. Interleaving races the two arms into separate cache misses
        and destroys the pairing (observed in the 2-cell pilot).
        """
        nonlocal completed, failed, flagged, accepted_flag
        pending = [c for c in arm_cells
                   if f"{c[0]}__{c[1]}__{c[2]}__r{c[3]}" not in done[fr]]
        if not pending:
            return
        print(f"\n=== arm: {fr} ({len(pending)} conversations) ===", flush=True)
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
            in_flight = {}
            it = iter(pending)

            def submit_next() -> bool:
                for vid, fam, adv, rep in it:
                    if stop[0]:
                        return False
                    fut = ex.submit(_generate_and_judge, client, load_vignette(vid),
                                    get_family(families_doc, fam), adv, rep,
                                    families_doc=families_doc, max_turns=8,
                                    independent_response1=True, context_arm="none",
                                    patient_framing=fr)      # <-- the whole point of this test
                    in_flight[fut] = (vid, fam, adv, rep)
                    return True
                return False

            for _ in range(min(CONCURRENCY, len(pending))):
                submit_next()

            while in_flight:
                got, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for fut in got:
                    vid, fam, adv, rep = in_flight.pop(fut)
                    cid = f"{vid}__{fam}__{adv}__r{rep}"
                    try:
                        conv = fut.result()
                    except Exception as e:  # noqa: BLE001 — per-cell isolation
                        failed += 1
                        print(f"  FAIL [{fr}] {cid}: {type(e).__name__}: {e}", file=sys.stderr)
                        traceback.print_exc(file=sys.stderr)
                        submit_next()
                        continue
                    append_record(conv, arms[fr].records_path)
                    f_, v_, extra = _guard_bookkeeping(
                        conv, arms[fr].guard_path,
                        lambda: datetime.now(timezone.utc).isoformat())
                    flagged += int(f_)
                    accepted_flag += int(v_)
                    cost = extra + sum((t.usage or {}).get("cost") or 0 for t in conv.turns)
                    j = conv.judgment or {}
                    for seat in (j.get("panel") or []):
                        cost += ((seat.get("judge_usage") or {}).get("cost") or 0)
                    spent_box[0] += cost
                    completed += 1
                    print(f"[{completed}/{len(todo)}] {fr:15s} {cid:38s} "
                          f"judge={j.get('status')}  spent=${spent_box[0]:.4f}", flush=True)
                    if spent_box[0] >= MAX_SPEND:
                        stop[0] = True
                        print(f"\nSTOP: spend cap ${MAX_SPEND} reached (${spent_box[0]:.4f}). "
                              f"Re-run to resume; completed work is persisted.", file=sys.stderr)
                        in_flight.clear()
                        break
                    submit_next()

    for fr in FRAMINGS:                 # role-swap fully, THEN single-message
        if stop[0]:
            break
        run_arm(fr, cells)
    spent = spent_box[0]

    print(f"\ndone: completed={completed} failed={failed} spend=${spent:.4f}")
    print(f"guard: {flagged} conversation(s) flagged, {accepted_flag} with an accepted-but-flagged turn")
    manifest = {
        "test": "patient-framing A/B (role-swap vs single-message)",
        "preregistration": "docs/validation/framing_ab/PREREGISTRATION.md",
        "started": started, "ended": datetime.now(timezone.utc).isoformat(),
        "cells": len(cells), "conversations": completed, "failed": failed,
        "spend_usd": round(spent, 6), "cap_usd": MAX_SPEND,
        "cache_dir": str(cache_dir), "concurrency": CONCURRENCY,
        "design": {"max_turns": 8, "independent_response1": True, "replicate": 0,
                   "barrier_vignettes": BARRIER_VIGNETTES, "barrier_families": BARRIER_FAMILIES,
                   "control_vignettes": CONTROL_VIGNETTES, "advisors": ADV},
    }
    (study.path / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"manifest: {study.path / 'manifest.json'}")


if __name__ == "__main__":
    main()
