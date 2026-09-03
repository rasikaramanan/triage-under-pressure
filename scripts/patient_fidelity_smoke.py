#!/usr/bin/env python
"""Comparative patient-simulator fidelity smoke — five patient models over one matched cell set.

Design and analysis plan fixed in advance: docs/validation/patient_fidelity/PREREGISTRATION.md (a design document not included in this release).

At the time of this study the patient simulator was `meta-llama/llama-4-maverick`, which is also
an advisor under test; it was being moved off the advisor slate. This script picks the replacement
empirically: ONE fixed set of 32 cells (vignette x condition x advisor, replicate 0) is run under
each of five patient models, with identical seeds, so every difference is attributable to the
patient and nothing else.

Why the arms are matched. The per-conversation seed is derived from (base seed, replicate, family)
and does not depend on the patient model, so within a cell all five arms share one seed. The
advisor's response 1 precedes any patient-LLM message and has an identical cache key in every arm,
so the first arm generates it and the other four are served it byte-identically from the shared
cache: each arm starts every cell from exactly the same first advisor turn. Arms therefore run
SEQUENTIALLY (all of arm 1, then arm 2, ...) — interleaving races them into separate cache misses
and destroys the matching (observed in the framing A/B's 2-cell pilot).

Everything else is the locked stack as it stood for this study (recorded in the study's own
instrument snapshot): single-message framing, patient v11, families v11, advisor Option A, 8
turns, guard v1.5.0 (uniform enforcement), judge prompt v8, 3-judge panel. The patient model is
the ONE deviation: each candidate arm runs with an explicit unlock and its manifest records the
mismatch, while the incumbent arm matches the lock and records none — see `--unlock-stack`
below and section 4 of the pre-registration.

    python scripts/patient_fidelity_smoke.py --preflight-only   # validate slugs, $0
    python scripts/patient_fidelity_smoke.py --limit 2          # tiny live slice
    python scripts/patient_fidelity_smoke.py --unlock-stack     # the real thing
"""
from __future__ import annotations

import argparse
import dataclasses
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
from tup.client.top_p import effective_top_p_record, fetch_live_facts, verify_top_p
from tup.data.prompts import get_family, load_families
from tup.data.vignettes import load_vignette
from tup.harness.driver import _generate_and_judge, _guard_bookkeeping
from tup.judge.judge import judge_conversation_panel
from tup.orchestration.runner import run_conversation
from tup.orchestration.stack_lock import StackLockError, assert_locked_stack
from tup.output import cost as costmod
from tup.output.persist import append_record, load_records
from tup.store import Store

#: A STUDY, not a run: its five arms are the five candidate patient models, so they are named for
#: them rather than forced into the run vocabulary of main/context.
STUDY_NAME = "patient_fidelity"
_STORE = Store.from_env()
STUDY = _STORE.study_for_run_name(STUDY_NAME, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
CACHE_DIR = _STORE.cache_dir

# --- the five arms (pre-registration section 2) ---------------------------------------------------------
# arm key -> OpenRouter slug. The incumbent is the REFERENCE baseline, not an eligible winner.
# No reasoning model is eligible: reasoning models leak reasoning into patient text (the
# ground on which the earlier patient-model choice rejected Haiku), so deepseek-chat-v3.1 /
# deepseek-v3.2 / glm-4.6 / mistral-small-2603 are excluded even though otherwise attractive.
ARMS: dict[str, str] = {
    "incumbent_maverick": "meta-llama/llama-4-maverick",
    "llama33_70b": "meta-llama/llama-3.3-70b-instruct",
    "mistral_small_32": "mistralai/mistral-small-3.2-24b-instruct",
    "deepseek_v3": "deepseek/deepseek-chat-v3-0324",
    "qwen3_235b": "qwen/qwen3-235b-a22b-2507",
}
INCUMBENT = "incumbent_maverick"

# --- the matched cell set (pre-registration section 3) ---------------------------------------------------
VIGNETTES = ["012", "011", "005", "003"]   # the three highest- and the lowest-degradation vignettes of the run available at selection time
FAMILIES = ["control", "caregiving", "work", "cost_medical_debt"]
ADVISORS = ["anthropic", "xai"]
REPLICATE = 0
MAX_TURNS = 8

MAX_SPEND = 25.0        # fail-closed cap (pre-registration header)
CONCURRENCY = 8


def build_cells() -> list[tuple[str, str, str, int]]:
    """The fixed cell list, in deterministic order. cell = (vignette, family, advisor, replicate)."""
    return [(v, f, a, REPLICATE) for v in VIGNETTES for f in FAMILIES for a in ADVISORS]


def cid_of(cell) -> str:
    return f"{cell[0]}__{cell[1]}__{cell[2]}__r{cell[3]}"


def _generate_soft_judge(client, vignette, family, advisor, replicate, **kw):
    """Generate the conversation, then judge it — but NEVER lose the conversation to a judge failure.

    `driver._generate_and_judge` raises if the judge panel raises, so the whole cell is discarded and
    the transcript never reaches disk. During this run Google's shared pool rate-limited the
    gemini-3.6-flash judge seat repeatedly, which threw away 16 completed conversations — i.e. a
    failure in the OPTIONAL secondary outcome was destroying the PRIMARY one (patient behaviour;
    pre-registration section 5). Here the transcript is kept and the judgment is marked failed, so the
    conversation still counts for every patient-fidelity metric and simply drops out of the
    judge-dependent secondary (the analysis already requires status == "judged" for those).
    """
    conv = run_conversation(client, vignette, family, advisor, replicate=replicate, **kw)
    try:
        judge_conversation_panel(client, conv, vignette,
                                 rotation_index=int(vignette.id) + replicate)
    except Exception as e:  # noqa: BLE001 — the judge is the optional secondary; never lose the record
        conv.judgment = {"status": "judge_failed", "error": f"{type(e).__name__}: {e}",
                         "init_correct": None, "init_response_number": None, "ToD": None,
                         "degraded_turn_quote": None, "rationale": None}
    return conv


def validate_candidates(client) -> dict:
    """Live gate on every candidate slug BEFORE any spend (pre-registration sections 2 and 4).

    `client.validate_models()` only covers the slugs in config/models.yaml, and `verify_top_p()`
    only gates the configured patient/guard slugs — neither sees a candidate. This is the equivalent
    explicit check: each candidate must be present on the live OpenRouter list and accept top_p
    UNANIMOUSLY across its served endpoints, which fixes its effective top_p at OpenRouter's
    injected 1.0 — the same value, for the same reason, as the incumbent. Returns the provenance
    dict written into every arm manifest; raises on any unreachable or split-endpoint slug.
    """
    slugs = sorted(set(ARMS.values()))
    facts = fetch_live_facts(slugs)
    prov, problems = {}, []
    for slug in slugs:
        f = facts.get(slug) or {"present": False}
        if not f.get("present"):
            problems.append(f"{slug}: NOT on the live OpenRouter model list — swap it (pre-registration section 2)")
            continue
        ep = f.get("endpoint_top_p") or set()
        if not f.get("models_accepts_top_p"):
            problems.append(f"{slug}: does not accept top_p; effective top_p would differ from the "
                            f"incumbent's injected 1.0 — not comparable, swap it")
        elif ep and ep != {True}:
            problems.append(f"{slug}: served endpoints DISAGREE on top_p support "
                            f"({sorted(ep)}) — effective top_p is not uniform across routing")
        prov[slug] = {
            "top_p": 1.0,
            "basis": ("accepts top_p on every served endpoint -> OpenRouter injects its documented "
                      "default top_p=1.0 for the omitted parameter before forwarding upstream "
                      "(same basis as the incumbent)"),
            "accepts_top_p": bool(f.get("models_accepts_top_p")),
            "endpoint_unanimous": (ep == {True}) if ep else None,
            "provider": sorted(f.get("providers") or []),
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    if problems:
        raise ValueError("candidate slug validation FAILED:\n  " + "\n  ".join(problems))
    return prov


def run_arm(arm: str, slug: str, cells, *, config, families_doc, state, args) -> None:
    """One complete pass over the cell set for a single patient model."""
    a = STUDY.arm(arm).mkdir()
    out_path, guard_path, fail_path = a.records_path, a.guard_path, a.failures_path
    done = {r.get("conversation_id") for r in (load_records(out_path) if out_path.exists() else [])}
    pending = [c for c in cells if cid_of(c) not in done]

    # The patient model is the one deviation from the locked stack: assert it explicitly so this arm
    # is self-identifying in its own manifest (pre-registration section 4). Every arm — the incumbent
    # included — records its lock check; only the four candidates carry a mismatch.
    arm_config = dataclasses.replace(config, patient_model=slug)
    try:
        lock_record = assert_locked_stack(
            {"patient_framing": "single_message", "max_turns": MAX_TURNS, "patient_model": slug},
            allow_override=args.unlock_stack)
    except StackLockError as e:
        print(f"error: {e}")
        sys.exit(2)

    print(f"\n=== arm {arm}  ({slug})  —  {len(pending)}/{len(cells)} conversations to run ===")
    if lock_record["mismatches"]:
        print("  locked-stack OVERRIDE (expected — this test varies the patient):")
        for m in lock_record["mismatches"]:
            print(f"    - {m}")
    else:
        print("  locked-stack: compliant (this is the reference arm)")
    if not pending:
        _write_manifest(arm, slug, cells, lock_record, state, args)
        return

    client = OpenRouterClient(config=arm_config, cache=ResponseCache(cache_dir=CACHE_DIR))
    assert client.resolve_model("patient") == slug, "patient slug override did not take effect"

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        in_flight, it = {}, iter(pending)

        def submit_next() -> bool:
            for cell in it:
                if state["stop"]:
                    return False
                # Same work either way; they differ only in whether a judge failure discards the
                # conversation. The two helpers name the families argument differently.
                if args.soft_judge:
                    fn, fams_kw = _generate_soft_judge, {"families": families_doc}
                else:
                    fn, fams_kw = _generate_and_judge, {"families_doc": families_doc}
                fut = ex.submit(fn, client, load_vignette(cell[0]),
                                get_family(families_doc, cell[1]), cell[2], cell[3],
                                max_turns=MAX_TURNS, context_arm="none",
                                **fams_kw)
                in_flight[fut] = cell
                return True
            return False

        for _ in range(min(args.concurrency, len(pending))):
            submit_next()

        while in_flight:
            got, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for fut in got:
                cell = in_flight.pop(fut)
                cid = cid_of(cell)
                try:
                    conv = fut.result()
                except Exception as e:   # noqa: BLE001 — per-cell isolation, as in the driver
                    state["failed"] += 1
                    payload = {"arm": arm, "conversation_id": cid, "error": f"{type(e).__name__}: {e}",
                               "traceback": traceback.format_exc()}
                    fail_path.parent.mkdir(parents=True, exist_ok=True)
                    with fail_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    print(f"  FAIL [{arm}] {cid}: {type(e).__name__}: {e}", file=sys.stderr)
                    submit_next()
                    continue
                append_record(conv, out_path)
                _f, _v, extra = _guard_bookkeeping(
                    conv, guard_path, lambda: datetime.now(timezone.utc).isoformat())
                rec = conv.to_dict()
                jc, _ = costmod.judge_cost(rec)
                state["spent"] += costmod.turns_cost(rec) + jc + extra
                state["completed"] += 1
                j = conv.judgment or {}
                print(f"[{state['completed']}] {arm:19s} {cid:34s} judge={j.get('status')} "
                      f"spent=${state['spent']:.4f}", flush=True)
                if state["spent"] >= MAX_SPEND:
                    state["stop"] = True
                    print(f"\nSTOP: ${MAX_SPEND} cap reached (${state['spent']:.4f}). Completed "
                          f"work is persisted; re-run to resume.", file=sys.stderr)
                    in_flight.clear()
                    break
                submit_next()

    _write_manifest(arm, slug, cells, lock_record, state, args)


def _write_manifest(arm, slug, cells, lock_record, state, args) -> None:
    out_path = STUDY.arm(arm).records_path
    recs = load_records(out_path) if out_path.exists() else []
    cost = costmod.accumulate(recs)
    guard_extra = sum(float(((r.get("metadata") or {}).get("guard") or {}).get("extra_cost_usd") or 0)
                      for r in recs)
    man = {
        "schema": "tup-patient-fidelity-arm-manifest/1",
        "test": "comparative patient-simulator fidelity smoke",
        "preregistration": "docs/validation/patient_fidelity/PREREGISTRATION.md (design document, not released)",
        "arm": arm, "patient_model": slug, "is_reference": arm == INCUMBENT,
        # The whole point of the unlock: this arm's deviation from config/locked_stack.yaml, on the
        # record, in the arm's own output.
        "stack_lock": lock_record,
        "design": {"cells": [cid_of(c) for c in cells], "n_cells": len(cells),
                   "vignettes": VIGNETTES, "families": FAMILIES, "advisors": ADVISORS,
                   "replicate": REPLICATE, "max_turns": MAX_TURNS,
                   "patient_framing": "single_message", "response1_sampling": "independent",
                   "context_arm": "none", "concurrency": args.concurrency},
        "reproducibility": {"effective_top_p": effective_top_p_record(),
                            "candidate_top_p": state["candidate_top_p"],
                            "top_p_verified_at": state["top_p_verified_at"]},
        "cache_dir": str(CACHE_DIR),
        "n_records": len(recs),
        "cost": cost.as_record() | {"guard_extra_usd": round(guard_extra, 6)},
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    p = STUDY.arm(arm).manifest_path
    p.write_text(json.dumps(man, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  manifest: {p.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cells per arm")
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY)
    ap.add_argument("--preflight-only", action="store_true", help="validate everything, spend $0")
    ap.add_argument("--soft-judge", action="store_true",
                    help="keep the conversation when the judge panel fails (marked judge_failed) "
                         "instead of discarding the cell. The judge is the OPTIONAL secondary "
                         "outcome here; a judge-seat rate limit must not destroy patient-fidelity "
                         "data. Judge-dependent metrics simply skip these conversations.")
    ap.add_argument("--unlock-stack", action="store_true",
                    help="required: this test deliberately varies the patient model, which the "
                         "locked stack pins. Each arm's manifest records the deviation.")
    args = ap.parse_args()

    cells = build_cells()
    if args.limit:
        cells = cells[:args.limit]
        print(f"LIMIT: first {args.limit} cells only")
    STUDY.path.mkdir(parents=True, exist_ok=True)

    config = load_config()
    families_doc = load_families()
    print(f"arms: {len(ARMS)}  cells/arm: {len(cells)}  ->  {len(ARMS) * len(cells)} conversations")
    print(f"advisors: {ADVISORS}  vignettes: {VIGNETTES}  families: {FAMILIES}")
    print(f"guard: {config.guard_model}  judge panel: {config.judge_panel}  cache: {CACHE_DIR}")

    print("preflight: validate_models() (configured slate, live) ...")
    print(f"  OK — {len(config.providers)} advisor/judge slugs reachable")
    probe = OpenRouterClient(config=config, cache=ResponseCache(cache_dir=CACHE_DIR))
    probe.validate_models()
    print("preflight: verify_top_p() for the configured slate (live) ...")
    ok, drift = verify_top_p(live=True, config=config)
    if not ok:
        for d in drift:
            print(f"  DRIFT: {d}")
        sys.exit(2)
    print("  OK")
    print("preflight: candidate slugs — live presence + unanimous top_p acceptance ...")
    candidate_top_p = validate_candidates(probe)
    for slug, p in sorted(candidate_top_p.items()):
        print(f"  OK  {slug:46s} endpoints={p['provider']}")

    state = {"spent": 0.0, "completed": 0, "failed": 0, "stop": False,
             "candidate_top_p": candidate_top_p,
             "top_p_verified_at": datetime.now(timezone.utc).isoformat()}
    for arm in ARMS:
        p = STUDY.arm(arm).records_path
        if p.exists():
            state["spent"] += costmod.accumulate(load_records(p)).total_usd
    print(f"prior spend in these files: ${state['spent']:.4f}")

    if args.preflight_only:
        print("\npreflight-only: everything validated, $0 spent.")
        return

    # Arms run SEQUENTIALLY so each one inherits the first arm's cached response 1 (see module
    # docstring) — the property that makes the arms matched.
    for arm, slug in ARMS.items():
        if state["stop"]:
            break
        run_arm(arm, slug, cells, config=config, families_doc=families_doc, state=state, args=args)

    print(f"\ndone: completed={state['completed']} failed={state['failed']} "
          f"spend=${state['spent']:.4f} of ${MAX_SPEND}")
    print(f"records: {STUDY.path}")


if __name__ == "__main__":
    main()
