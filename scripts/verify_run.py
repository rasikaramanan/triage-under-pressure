"""Exhaustive completeness + integrity verification for a finished TUP run.

Checks come from two places, both on disk: values DERIVED from the run's own records and its
own instrument snapshot (``<run>/instrument/``, byte copies of the prompt/config/vignette files
taken at preflight), and the locked design terms asserted as literals in this file. (The
snapshot's own ``config/locked_stack.yaml`` — verified byte-true against the snapshot
manifest — is the binding statement of those terms; the literals here restate them so a
drifted record fails loudly. The one term read from the snapshot lock rather than restated is
``judge_prompt_version``: the rubric is the instrument file a finished run may legitimately be
re-scored under — ``scripts/rejudge.py`` — and the snapshot's judge files follow the records,
so the expected version is whatever that snapshot declares.) Nothing is taken from intent, docstrings, or what a
launcher was supposed to have passed: this is the executable form of the
"verify compliance from output records" rule.

Reading the snapshot rather than the working tree matters: it makes a finished run
verifiable from its own directory alone, forever -- editing a prompt file for the NEXT experiment
can no longer break the verification of the last one. For a run WITH a snapshot, the working tree appears only in an
informational note (has the current instrument diverged from this run's?), never in a check. A
snapshot-less run is LEGACY: the file-provenance checks are skipped with a note saying so, and
the grid inputs fall back to the working tree — the note says that too, because against a
moved-on tree those checks would prove nothing either way.

  python scripts/verify_run.py 2026-08-06__full_experiment     # both arms of a run in the store

Exits non-zero if any check fails, and prints every failure.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # repo root, when run directly

from tup.client.config import MODELS_YAML, load_config     # noqa: E402
from tup.data.prompts import load_families                 # noqa: E402
from tup.data.vignettes import load_vignettes              # noqa: E402
from tup.harness.invocation import ARM_CONTEXT             # noqa: E402
from tup.orchestration.instrument import verify_integrity, working_tree_divergence  # noqa: E402
from tup.store import RunNotFoundError, Store              # noqa: E402

FAILURES: list[str] = []
NOTES: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{label}: {detail}")


def load(path: Path):
    recs, bad = [], 0
    for i, line in enumerate(path.open(), 1):
        try:
            recs.append(json.loads(line))
        except Exception as e:  # noqa: BLE001
            bad += 1
            FAILURES.append(f"{path.name} line {i} unparseable: {e}")
    return recs, bad


def expected_judge_version(iroot: Path | None) -> int:
    """The rubric version every verdict must carry: the snapshot lock's ``judge_prompt_version``
    (a legacy, snapshot-less run falls back to the working tree's lock, with the same caveat as
    every other working-tree fallback)."""
    from tup.orchestration.stack_lock import load_lock  # noqa: PLC0415
    lock = load_lock(iroot / "config" / "locked_stack.yaml" if iroot is not None else None)
    return int(lock["judge_prompt_version"])


def expected_ids(vigs, fams, advisors, replicates):
    return {f"{v.id}__{f['name']}__{adv}__r{rep}"
            for v in vigs for adv in advisors for rep in range(replicates) for f in fams}


def verify(path: Path, arm: str, replicates: int, vigs, fams, advisors, cfg, iroot: Path | None):
    print(f"\n{'=' * 78}\n{arm}  ({path.name})\n{'=' * 78}")
    recs, bad = load(path)
    check(bad == 0, "every line parses as JSON", f"{bad} unparseable")

    # ---- completeness -------------------------------------------------------------------
    want = expected_ids(vigs, fams, advisors, replicates)
    have = [r["conversation_id"] for r in recs]
    have_set = set(have)
    dupes = [c for c, n in collections.Counter(have).items() if n > 1]
    check(len(recs) == len(want), "record count == full grid", f"{len(recs)} vs {len(want)}")
    check(not dupes, "no duplicate conversation_ids", f"{len(dupes)} dupes: {dupes[:5]}")
    missing, extra = sorted(want - have_set), sorted(have_set - want)
    check(not missing, "every grid cell present", f"{len(missing)} missing: {missing[:8]}")
    check(not extra, "no off-grid records", f"{len(extra)} extra: {extra[:8]}")

    fpath = path.parent / "failures.jsonl"
    if fpath.exists():
        fails, _ = load(fpath)
        unresolved = sorted({f.get("conversation_id") for f in fails} - have_set)
        check(not unresolved, "every recorded failure was backfilled",
              f"{len(unresolved)} still absent: {unresolved[:8]}")
    else:
        NOTES.append(f"{fpath.name} absent (no failures were ever logged)")

    # ---- judgment integrity -------------------------------------------------------------
    st = collections.Counter((r.get("judgment") or {}).get("status") for r in recs)
    check(set(st) == {"judged"}, "every record status == 'judged'", dict(st))
    nopanel = [r["conversation_id"] for r in recs if not ((r.get("judgment") or {}).get("panel"))]
    check(not nopanel, "every record carries a judge panel", f"{len(nopanel)}: {nopanel[:5]}")
    sizes = collections.Counter(len((r.get("judgment") or {}).get("panel") or []) for r in recs)
    check(set(sizes) == {3}, "every panel has 3 seats", dict(sizes))
    viol = [r["conversation_id"] for r in recs
            for v in ((r.get("judgment") or {}).get("panel") or [])
            if (v.get("provider") or v.get("judge_provider")) == r["advisor_provider"]]
    check(not viol, "leave-one-provider-out holds", f"{len(viol)}: {viol[:5]}")
    # median-of-2 is a DESIGNED fallback, not a defect (see
    # test_panel.py::test_median2_fallback_agreement): if one seat is still unparseable after its
    # corrective retry, the two survivors aggregate rather than voiding the conversation.
    agg = collections.Counter((r.get("judgment") or {}).get("aggregation") for r in recs)
    check(set(agg) <= {"median3_Tplus1", "median2_Tplus1_fallback"},
          "aggregation is median-of-3 or the sanctioned median-of-2 fallback", dict(agg))
    if agg.get("median2_Tplus1_fallback"):
        NOTES.append(f"{arm}: {agg['median2_Tplus1_fallback']} conversation(s) aggregated on 2 seats "
                     f"(one seat unparseable after its retry) -- sanctioned fallback")
    seat_st = collections.Counter(s.get("status") for r in recs
                                 for s in ((r.get("judgment") or {}).get("panel") or []))
    check(set(seat_st) <= {"judged", "unparseable"}, "every panel seat is judged or unparseable",
          dict(seat_st))
    thin = [r["conversation_id"] for r in recs
            if sum(1 for s in ((r.get("judgment") or {}).get("panel") or [])
                   if s.get("status") == "judged") < 2]
    check(not thin, "every aggregate rests on >= 2 judged seats", f"{len(thin)}: {thin[:5]}")
    jver = collections.Counter(((r.get("judgment") or {}).get("judge_prompt") or {}).get("version")
                               for r in recs)
    want_jver = expected_judge_version(iroot)
    check(set(jver) == {want_jver},
          f"judge prompt version == {want_jver} everywhere (the snapshot lock's judge_prompt_version)",
          dict(jver))

    # metric coherence: ToD is NA iff init_correct==0; otherwise int in [2, max_turns+1]
    # and strictly greater than init_response_number (the rubric defines ToD as a LATER response)
    bad_tod = []
    for r in recs:
        j = r.get("judgment") or {}
        ic, tod = j.get("init_correct"), j.get("ToD")
        mt = (r.get("metadata") or {}).get("max_turns")
        if ic == 0 and tod not in ("NA", None):
            bad_tod.append((r["conversation_id"], ic, tod))
        elif ic == 1 and not (isinstance(tod, int) and 2 <= tod <= (mt or 8) + 1
                              and (not isinstance(j.get("init_response_number"), int)
                                   or tod > j["init_response_number"])):
            bad_tod.append((r["conversation_id"], ic, tod))
        elif ic not in (0, 1):
            bad_tod.append((r["conversation_id"], ic, tod))
    check(not bad_tod, "init_correct/ToD coherent", f"{len(bad_tod)}: {bad_tod[:5]}")

    # ---- instrument compliance (locked stack, read off the records) ---------------------
    def meta_counter(key):
        return collections.Counter((r.get("metadata") or {}).get(key) for r in recs)

    check(set(meta_counter("patient_framing")) == {"single_message"},
          "patient_framing == single_message", dict(meta_counter("patient_framing")))
    # The arm's DIRECTORY NAME is the arm — never a filename substring test.
    want_arm = ARM_CONTEXT[path.parent.name]
    check(set(meta_counter("context_arm")) == {want_arm},
          f"context_arm == {want_arm}", dict(meta_counter("context_arm")))
    check(set(meta_counter("max_turns")) == {8}, "max_turns == 8", dict(meta_counter("max_turns")))
    check(set(meta_counter("complete")) == {True}, "no incomplete conversations",
          dict(meta_counter("complete")))
    check(set(meta_counter("response1_sampling")) == {"independent"},
          "response-1 sampling == independent", dict(meta_counter("response1_sampling")))

    turns = collections.Counter(sum(1 for t in r["turns"] if t["speaker"] == "advisor") for r in recs)
    check(set(turns) == {8}, "8 advisor turns in every conversation", dict(turns))
    empty = [r["conversation_id"] for r in recs
             for t in r["turns"] if not (t.get("text") or "").strip()]
    check(not empty, "no empty turns", f"{len(empty)}: {empty[:5]}")
    first_bad = [r["conversation_id"] for r in recs
                 if not (r["turns"][0]["speaker"] == "patient" and r["turns"][0].get("runner_authored"))]
    check(not first_bad, "every transcript opens with the runner-authored patient turn",
          f"{len(first_bad)}: {first_bad[:5]}")

    pm = {t["model"] for r in recs for t in r["turns"] if t["speaker"] == "patient" and t.get("model")}
    check(pm == {cfg.patient_model}, f"patient model == {cfg.patient_model}", sorted(pm))
    adv_models = {r["advisor_provider"]: r["advisor_model"] for r in recs}
    check(adv_models == {k: cfg.providers[k] for k in advisors},
          "advisor slugs match config", adv_models)

    check(len({r["condition_name"] for r in recs}) == 7, "7 conditions",
          sorted({r["condition_name"] for r in recs}))
    check(len({r["vignette_id"] for r in recs}) == 14, "14 vignettes")
    check(len({r["advisor_provider"] for r in recs}) == 5, "5 advisors")

    # ---- prompt provenance --------------------------------------------------------------
    # All file-backed provenance is checked against the run's INSTRUMENT SNAPSHOT, never the
    # working tree. A legacy run (no snapshot) skips these with a note: against today's files
    # they would prove nothing about what the run actually ran under.
    cells = collections.defaultdict(set)
    for r in recs:
        cells[(r["vignette_id"], r["condition_name"])].add(
            ((r.get("metadata") or {}).get("prompts") or {}).get("patient", {}).get("sha256"))
    multi = [k for k, v in cells.items() if len(v) > 1]
    check(not multi, "patient prompt hash is constant within each vignette x family cell", multi[:5])
    if iroot is None:
        NOTES.append(f"{arm}: LEGACY run (predates the instrument snapshot) -- file-backed "
                     f"provenance checks skipped; recorded hashes remain in the records")
    else:
        # families: a FILE hash, constant across the arm -> compare to the snapshot's copy.
        snap = hashlib.sha256((iroot / "prompts/patient/families.yaml").read_bytes()).hexdigest()
        recorded = {((r.get("metadata") or {}).get("prompts") or {}).get("families", {}).get("sha256")
                    for r in recs}
        check(recorded == {snap}, "families sha256 matches the instrument snapshot",
              f"recorded={sorted(x[:12] for x in recorded)} snapshot={snap[:12]}")

        # patient: the RENDERED per-cell prompt hash (vignette x family), NOT the template file.
        # The strong check is to re-render every cell from the snapshot and reproduce the recorded
        # hash -- proving the exact patient prompt each conversation ran under, pairing clauses
        # included, independent of anything the repo has done since.
        from tup.data.prompts import render_patient_system  # noqa: PLC0415
        fams_doc = load_families(root=iroot)
        famobj = {f["name"]: f for f in fams_doc["families"]}
        vmap = {v.id: v for v in load_vignettes(root=iroot)}
        bad = []
        for (vid, fname), hs in sorted(cells.items()):
            asset = render_patient_system(vmap[vid], famobj[fname], fams_doc, root=iroot)
            rendered = getattr(asset, "sha256", None) or hashlib.sha256(asset.text.encode()).hexdigest()
            if rendered not in hs:
                bad.append(f"{vid}x{fname}")
        check(not bad, f"all {len(cells)} rendered patient prompts reproduce from the snapshot",
              f"{len(bad)} mismatched: {bad[:5]}")

        # judge: the TEMPLATE-body hash every verdict recorded must be the snapshot's rubric.
        from tup.data.prompts import load_judge_prompt  # noqa: PLC0415
        jsha = {((r.get("judgment") or {}).get("judge_prompt") or {}).get("sha256") for r in recs}
        snap_judge = load_judge_prompt(root=iroot).sha256
        check(jsha == {snap_judge}, "judge template sha256 matches the snapshot rubric",
              f"recorded={sorted(str(x)[:12] for x in jsha)} snapshot={snap_judge[:12]}")

        # advisor context (context arm only): every recorded per-family profile hash must
        # re-render from the snapshot's context_profiles.yaml — a recorded hash nothing
        # re-derives is provenance in name only.
        if ARM_CONTEXT[path.parent.name] != "none":
            from tup.data.prompts import render_advisor_context  # noqa: PLC0415
            rec_ctx = {(r["condition_name"],
                        ((r.get("metadata") or {}).get("advisor_context") or {}).get("sha256"))
                       for r in recs}
            bad_ctx = []
            for fname, h in sorted(rec_ctx):
                asset = render_advisor_context(famobj[fname], "barrier", root=iroot)
                if asset is None or asset.sha256 != h:
                    bad_ctx.append(fname)
            check(not bad_ctx, "advisor context profiles reproduce from the snapshot",
                  f"{len(bad_ctx)} mismatched: {bad_ctx[:5]}")
    check(len(cells) == 98, "98 distinct patient prompts (14 vignettes x 7 conditions)", len(cells))
    pv = {((r.get("metadata") or {}).get("prompts") or {}).get("patient", {}).get("version") for r in recs}
    fv = {((r.get("metadata") or {}).get("prompts") or {}).get("families", {}).get("version") for r in recs}
    check(pv == {12}, "patient prompt version == 12", sorted(pv))
    check(fv == {16}, "families version == 16", sorted(fv))

    gv = {((r.get("metadata") or {}).get("guard") or {}).get("version") for r in recs}
    check(gv == {"1.5.0"} or gv == {None}, "guard version stamped 1.5.0 (or unstamped on every record)", sorted(map(str, gv)))

    # ---- manifest lock ------------------------------------------------------------------
    man = json.loads((path.parent / "manifest.json").read_text())
    lock = man.get("stack_lock") or {}
    check(bool(lock), "manifest carries a stack_lock record")
    check(lock.get("mismatches") == [], "stack_lock has zero mismatches", lock.get("mismatches"))
    check(lock.get("overridden") is False, "lock was not overridden", lock.get("overridden"))
    check((man.get("design") or {}).get("patient_framing") == "single_message",
          "manifest design records single_message framing", (man.get("design") or {}))
    return recs


def _replicates_from(run, override) -> dict:
    """Per-arm replicate counts, read from the run itself.

    Order of authority: an explicit override, then the run's write-once invocation.json (what it was
    COMMISSIONED with), then each arm's manifest (what it DID). Falls back to the locked design only
    when a run predates both — and says so, rather than silently assuming.
    """
    if override:
        return {"main": override, "context": 1}
    inv = run.invocation() or {}
    recorded = ((inv.get("grid") or {}).get("replicates") or {})
    out = {}
    for arm in ("main", "context"):
        if recorded.get(arm):
            out[arm] = int(recorded[arm])
            continue
        man = run.arm(arm).manifest() or {}
        r = ((man.get("grid") or {}).get("replicates"))
        if r:
            out[arm] = int(r)
        else:
            out[arm] = 3 if arm == "main" else 1
            NOTES.append(f"{arm} arm: no invocation.json and no manifest replicate count; "
                         f"assumed R={out[arm]} from the locked design")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_id", help="run id in the store, e.g. 2026-08-06__full_experiment")
    ap.add_argument("--replicates", type=int, default=None,
                    help="replicates in the main arm. Default: read from the run's own "
                         "invocation.json, else its main manifest; a run that predates both "
                         "falls back to the locked 3 (main) / 1 (context) and says so.")
    args = ap.parse_args()

    store = Store.from_env()
    try:
        run = store.require_run(args.run_id)
    except RunNotFoundError as e:
        print(f"error: {e}")
        return 2
    print(f"store: {run.path}")

    # ---- instrument snapshot: the source of every file-backed input below ----------------
    iroot = run.instrument_dir if run.has_instrument() else None
    if iroot is not None:
        print(f"instrument: {iroot} (grid inputs and provenance checks read the SNAPSHOT)")
        broken = verify_integrity(iroot)
        check(not broken, "instrument snapshot matches its own manifest",
              f"{len(broken)}: {broken[:5]}")
        drifted = working_tree_divergence(iroot)
        if drifted:
            NOTES.append("working tree has diverged from this run's instrument in: "
                         + ", ".join(drifted) + " -- informational; the snapshot is the authority")
        else:
            NOTES.append("working tree still byte-matches this run's instrument snapshot")
    else:
        print("instrument: NONE -- legacy run; grid inputs come from the working tree")

    cfg = load_config(iroot / "config/models.yaml" if iroot else MODELS_YAML)
    vigs = sorted(load_vignettes(root=iroot), key=lambda v: v.id)
    fams = load_families(root=iroot)["families"]
    advisors = list(cfg.advisors)
    print(f"grid inputs: {len(vigs)} vignettes x {len(fams)} conditions x {len(advisors)} advisors")

    # Replicate counts come from the RUN, not from a constant. An assumed count verifies exactly one run
    # and silently mis-verifies any other.
    reps = _replicates_from(run, args.replicates)
    print(f"replicates: main R={reps['main']}, context R={reps['context']} "
          f"({'--replicates override' if args.replicates else 'read from the run'})")

    m = verify(run.arm("main").records_path, f"MAIN ARM (no role prompt, R={reps['main']})",
               reps["main"], vigs, fams, advisors, cfg, iroot)
    c = verify(run.arm("context").records_path, f"CONTEXT ARM (barrier-as-context, R={reps['context']})",
               reps["context"], vigs, fams, advisors, cfg, iroot)

    print(f"\n{'=' * 78}\nCROSS-ARM\n{'=' * 78}")
    want_total = len(vigs) * len(fams) * len(advisors) * (reps["main"] + reps["context"])
    check(len(m) + len(c) == want_total, f"{want_total:,} conversations total (derived from the grid)",
          f"{len(m)} + {len(c)}")
    check({r["replicate"] for r in c} == set(range(reps["context"])),
          f"context arm has replicates 0..{reps['context'] - 1}", sorted({r["replicate"] for r in c}))
    check({r["replicate"] for r in m} == set(range(reps["main"])),
          f"main arm has replicates 0..{reps['main'] - 1}", sorted({r["replicate"] for r in m}))
    ctx_sys = {bool(((r.get("metadata") or {}).get("advisor_context"))) for r in c}
    main_sys = {bool(((r.get("metadata") or {}).get("advisor_context"))) for r in m}
    check(ctx_sys == {True}, "every context-arm record carries an advisor context block", ctx_sys)
    check(main_sys == {False}, "no main-arm record carries an advisor context block", main_sys)

    print(f"\n{'=' * 78}")
    for n in NOTES:
        print(f"  note: {n}")
    if FAILURES:
        print(f"\n*** {len(FAILURES)} CHECK(S) FAILED ***")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED -- the run is complete and internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
