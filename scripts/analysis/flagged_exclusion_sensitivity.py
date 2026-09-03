#!/usr/bin/env python
"""Flagged-exclusion sensitivity: does dropping every guard-flagged conversation move a verdict?

The write-up says the fidelity guard flagged 6.1% of conversations and that one corrected rewrite
cured almost all of those flags. The obvious reader question is whether the findings survive
throwing the flagged conversations away entirely. ``analyze_experiment.py`` already answers it for
ONE contrast (``sensitivity/dropping_any_guard_flagged_conversations``, the pooled structural-vs-
control Fisher test in each arm). This script answers it for the whole battery: it re-runs the
complete prespecified analysis on the records with every conversation carrying at least one guard
flag removed, then compares each test in the re-run against the same test in the statistics of
record.

Method
------
1. Re-run ``analyze_experiment`` unchanged — same quarantine, same seeds, same model fits — with
   its record loader wrapped so that rows with ``guard_flagged`` are dropped from both arms before
   anything is computed. Nothing is re-judged and no record is modified; the run of record's own
   ``stats.json`` is never written to.
2. Compare every p-value in the two files. A test "holds" when it lands on the same side of
   alpha = 0.05 in both; a test "flips" when it crosses. Effect estimates (risk differences and
   risk ratios) are compared for sign, so a test cannot be called unchanged while its direction
   reverses.
3. Report the write-up's own verdicts separately from the exhaustive sweep. The curated list is the
   set of significance calls the article actually makes: every p-value the article quotes, every
   qualitative significance statement it makes, and the five verdict families its claims fall into
   (the pooled contrast, the reason test, the per-obstacle Holm family, the per-advisor pattern and
   the context-arm comparison). Each entry carries the sentence it backs.

The exclusion is deliberately the WIDEST of the three guard cuts: any flag at all, cured or not,
enforcing or audit-only, rather than the accepted-uncured subset. A robustness claim is only worth
making against the most demanding cut a reader would ask for.

Writes ``<store>/analysis/sensitivity/<run-id>/flagged_exclusion.{json,md}``.

Run:  python scripts/analysis/flagged_exclusion_sensitivity.py 2026-08-06__full_experiment
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))

from tup.store import RunNotFoundError, Store   # noqa: E402

ALPHA = 0.05
RUN_DEFAULT = "2026-08-06__full_experiment"

#: leaf keys that hold a p-value
P_LEAVES = ("p", "p_wald", "fisher_p", "holm_p", "lrt_p", "mcnemar_exact_p")

#: The verdicts the article states, each as (stats path, the sentence or claim it backs).
#: Paths are "/"-separated into stats.json; a bracketed segment indexes nothing — the advisor
#: coefficient keys genuinely contain brackets.
VERDICTS: list[tuple[str, str]] = [
    # --- the pooled contrast (the headline) ---
    ("main_arm/primary_pooled/fisher_p",
     "the headline contrast: the structural barriers against the cooperative control"),
    ("main_arm/pooled_by_class/any_obstacle_vs_cooperative/fisher_p",
     "any obstacle against the cooperative control (post-hoc pooling)"),
    ("main_arm/pooled_by_class/nonstructural_vs_cooperative/fisher_p",
     "hospital fear against the cooperative control"),
    ("main_arm/models/mixed_glmm/p_wald",
     "the mixed-effects model behind the headline contrast"),
    ("main_arm/models/mixed_glmm/likelihood_ratio_test/p",
     "the likelihood-ratio companion to the mixed-effects model"),
    ("main_arm/models/gee/p",
     "the population-averaged companion model"),
    ("main_arm/models/logit_cluster/p",
     "the cluster-robust companion model"),
    ("main_arm/models/mixed_glmm_random_slope/lrt_vs_intercept_only/p",
     "the random-slope test: obstacle effects do not vary detectably across cases"),
    # --- the reason test (structural vs non-structural) ---
    ("main_arm/pooled_by_class/structural_vs_nonstructural/fisher_p",
     "the reason test, locked phrasing: the structural/fear difference is not statistically significant"),
    # --- the per-obstacle Holm family ---
    ("main_arm/per_family/caregiving/holm_p", "the per-obstacle Holm family: caregiving"),
    ("main_arm/per_family/transport_ambulance_cost/holm_p", "the per-obstacle Holm family: transport access"),
    ("main_arm/per_family/work/holm_p", "the per-obstacle Holm family: work"),
    ("main_arm/per_family/cost_medical_debt/holm_p", "the per-obstacle Holm family: cost/medical debt"),
    ("main_arm/per_family/no_insurance/holm_p", "the per-obstacle Holm family: no insurance"),
    ("main_arm/omnibus_barriers_only/p",
     "the five structural barriers are not distinguishable from each other"),
    ("main_arm/omnibus_family/p", "the seven groups differ overall"),
    # --- the per-advisor pattern ---
    ("main_arm/omnibus_advisor/p", "the model matters more than the obstacle: advisors differ"),
    ("main_arm/omnibus_vignette/p", "cases differ"),
    ("main_arm/barrier_effect_by_advisor/anthropic/holm_p", "the per-advisor pattern: Claude"),
    ("main_arm/barrier_effect_by_advisor/google/holm_p", "the per-advisor pattern: Gemini"),
    ("main_arm/barrier_effect_by_advisor/meta/holm_p", "the per-advisor pattern: Llama"),
    ("main_arm/barrier_effect_by_advisor/openai/holm_p", "the per-advisor pattern: GPT"),
    ("main_arm/barrier_effect_by_advisor/xai/holm_p", "the per-advisor pattern: Grok"),
    ("main_arm/models/mixed_glmm/advisor_coefficients/advisor[google]/p_wald",
     "the advisor terms in the mixed-effects model: Gemini"),
    ("main_arm/models/mixed_glmm/advisor_coefficients/advisor[meta]/p_wald",
     "the advisor terms in the mixed-effects model: Llama"),
    ("main_arm/sensitivity_drop_weakest_advisor/fisher_p",
     "the headline contrast with the weakest advisor removed"),
    # --- first-response accuracy: the design's built-in check ---
    ("main_arm/init_correct/pooled_barrier_vs_control/fisher_p",
     "the built-in check: first-response accuracy does not differ before the obstacle appears"),
    # --- the guard cuts the fine print already reports ---
    ("main_arm/sensitivity/dropping_accepted_uncured_conversations/fisher_p",
     "the fine print's accepted-uncured robustness cut"),
    ("main_arm/sensitivity/dropping_any_guard_flagged_conversations/fisher_p",
     "the fine print's any-flag robustness cut (the cut this analysis generalises)"),
    ("main_arm/sensitivity/degradation_within_any_flagged_vs_unflagged/fisher_p",
     "flagged conversations do not degrade more than unflagged ones"),
    # --- the context arm ---
    ("context_arm/primary_pooled/fisher_p",
     "the context arm: the structural barriers against that arm's own control"),
    ("context_arm/pooled_by_class/any_obstacle_vs_cooperative/fisher_p",
     "the context arm: any obstacle against that arm's own control"),
    ("context_arm/pooled_by_class/nonstructural_vs_cooperative/fisher_p",
     "the context arm: hospital fear against that arm's own control"),
    ("context_arm/per_family/caregiving/fisher_p", "the context arm's per-obstacle tests: caregiving"),
    ("context_arm/per_family/cost_medical_debt/fisher_p", "the context arm's per-obstacle tests: cost/medical debt"),
    ("context_arm/per_family/transport_ambulance_cost/fisher_p", "the context arm's per-obstacle tests: transport access"),
    ("context_arm/per_family/work/fisher_p", "the context arm's per-obstacle tests: work"),
    ("context_arm/per_family/no_insurance/fisher_p", "the context arm's per-obstacle tests: no insurance (not significant)"),
    # --- the cross-arm comparison ---
    ("cross_arm_descriptive/pooled_by_class/degradation_any_obstacle/fisher_p",
     "the cross-arm comparison: degradation under any obstacle"),
    ("cross_arm_descriptive/pooled_by_class/degradation_structural/fisher_p",
     "the cross-arm comparison: degradation under the structural barriers"),
    ("cross_arm_descriptive/pooled_by_class/init_correct_all_conditions/fisher_p",
     "the cross-arm first-response dip, locked phrasing: not significant"),
    ("cross_arm_descriptive/degradation/no_insurance/fisher_p",
     "no single obstacle's cross-arm difference is individually significant"),
]

#: Effect estimates whose SIGN must not reverse. (path, label)
DIRECTIONS: list[tuple[str, str]] = [
    ("main_arm/primary_pooled/risk_difference", "the headline risk difference"),
    ("main_arm/primary_pooled/risk_ratio", "the headline risk ratio"),
    ("main_arm/pooled_by_class/any_obstacle_vs_cooperative/risk_difference",
     "any obstacle against the cooperative control"),
    ("main_arm/pooled_by_class/nonstructural_vs_cooperative/risk_difference",
     "hospital fear against the cooperative control"),
    ("context_arm/primary_pooled/risk_difference", "the context arm's structural contrast"),
]


# --------------------------------------------------------------------------- reading helpers
def dig(doc, path: str):
    """Walk a '/'-separated path into a nested dict; None when any segment is missing."""
    cur = doc
    for seg in path.split("/"):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def walk_p_values(doc, prefix: str = ""):
    """Yield (path, value) for every p-value leaf in a statistics document."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            p = f"{prefix}/{k}" if prefix else k
            if k in P_LEAVES and not isinstance(v, (dict, list)):
                yield p, v
            else:
                yield from walk_p_values(v, p)
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from walk_p_values(v, f"{prefix}[{i}]")


def sig_class(p) -> str:
    """significant / not-significant / unavailable — the only three states a verdict has."""
    if p is None or not isinstance(p, (int, float)):
        return "unavailable"
    return "significant" if p < ALPHA else "not-significant"


# --------------------------------------------------------------------------- the re-run
def rerun_without_flagged(run_id: str, outdir: Path) -> tuple[dict, dict]:
    """Run the full analysis with every guard-flagged conversation dropped.

    Returns (statistics, dropped-counts). ``analyze_experiment`` is imported and driven rather than
    copied: a re-implementation of the model fits would answer a slightly different question than
    the one the write-up reports, which is the exact failure mode a sensitivity analysis exists to
    avoid.
    """
    import analyze_experiment as ae

    dropped: dict[str, dict] = {}
    original_load = ae.load
    original_stats_dir_for = Store.stats_dir_for

    def load_without_flagged(path: Path, arm: str):
        df = original_load(path, arm)
        kept = df[~df.guard_flagged].reset_index(drop=True)
        dropped[arm] = {"loaded": int(len(df)), "dropped": int(len(df) - len(kept)),
                        "kept": int(len(kept))}
        return kept

    ae.load = load_without_flagged
    Store.stats_dir_for = lambda self, rid: outdir            # every write lands here
    argv = sys.argv[:]
    sys.argv = ["analyze_experiment.py", run_id]
    md_error = None
    try:
        ae.main()
    except Exception as exc:                                   # noqa: BLE001
        # The human-readable digest formats the flagged-vs-unflagged comparison, which has an
        # empty numerator once the flagged conversations are gone. The machine file is written
        # before that step, so a failure here is expected and harmless — but only if the JSON
        # actually landed. Anything else is re-raised below.
        md_error = f"{type(exc).__name__}: {exc}"
    finally:
        ae.load = original_load
        Store.stats_dir_for = original_stats_dir_for
        sys.argv = argv

    produced = outdir / "stats.json"
    if not produced.exists():
        raise SystemExit(f"error: the re-run produced no statistics ({md_error or 'no exception'})")
    stats = json.loads(produced.read_text(encoding="utf-8"))
    if md_error:
        print(f"note: the digest step did not complete ({md_error}); the statistics were written first")
    return stats, dropped


# --------------------------------------------------------------------------- the comparison
def compare(record: dict, noflag: dict) -> dict:
    sweep = []
    for path, before in walk_p_values(record):
        after = dig(noflag, path)
        sweep.append({
            "path": path, "record": before, "without_flagged": after,
            "record_class": sig_class(before), "without_flagged_class": sig_class(after),
            "holds": sig_class(before) == sig_class(after),
        })

    verdicts = []
    for path, sentence in VERDICTS:
        before, after = dig(record, path), dig(noflag, path)
        verdicts.append({
            "path": path, "backs": sentence,
            "record": before, "without_flagged": after,
            "record_class": sig_class(before), "without_flagged_class": sig_class(after),
            "holds": sig_class(before) == sig_class(after),
        })

    directions = []
    for path, label in DIRECTIONS:
        before, after = dig(record, path), dig(noflag, path)
        same = (before is not None and after is not None
                and (before > 0) == (after > 0))
        directions.append({"path": path, "label": label, "record": before,
                           "without_flagged": after, "same_sign": bool(same)})

    return {"verdicts": verdicts, "directions": directions, "sweep": sweep}


def digest(doc: dict) -> list[str]:
    L = ["# Flagged-exclusion sensitivity", "",
         f"Run: `{doc['run_id']}`  ·  generated {doc['generated']}", "",
         doc["question"], ""]
    acc = doc["accounting"]
    L.append(f"Dropped every conversation carrying at least one guard flag: "
             f"{acc['dropped_total']} of {acc['loaded_total']}, leaving {acc['kept_total']} "
             f"({acc['main']['dropped']} main arm, {acc['ctx']['dropped']} context arm).")
    L.append("")
    v = doc["summary"]
    L.append(f"**{v['verdicts_held']} of {v['verdicts_total']} write-up verdicts hold.** "
             f"Across every test in the statistics, {v['sweep_held']} of {v['sweep_comparable']} "
             f"comparable p-values keep their side of alpha = {doc['alpha']}.")
    L.append("")
    L.append("## The write-up's verdicts")
    L.append("")
    L.append("| verdict | record p | without flagged | holds |")
    L.append("|---|---|---|---|")
    for r in doc["comparison"]["verdicts"]:
        f = lambda x: "—" if x is None else (f"{x:.3g}" if isinstance(x, (int, float)) else str(x))
        L.append(f"| {r['backs']} | {f(r['record'])} ({r['record_class']}) | "
                 f"{f(r['without_flagged'])} ({r['without_flagged_class']}) | "
                 f"{'yes' if r['holds'] else 'NO'} |")
    L.append("")
    L.append("## Effect directions")
    L.append("")
    for r in doc["comparison"]["directions"]:
        L.append(f"- {r['label']}: {r['record']} → {r['without_flagged']} "
                 f"({'same sign' if r['same_sign'] else 'SIGN REVERSED'})")
    L.append("")
    moved = [r for r in doc["comparison"]["sweep"] if not r["holds"]]
    L.append(f"## Every other test that changed side ({len(moved)})")
    L.append("")
    if not moved:
        L.append("None.")
    for r in moved:
        L.append(f"- `{r['path']}`: {r['record']:.3g} ({r['record_class']}) → "
                 f"{r['without_flagged']:.3g} ({r['without_flagged_class']})"
                 if isinstance(r["record"], (int, float)) and isinstance(r["without_flagged"], (int, float))
                 else f"- `{r['path']}`: {r['record']} ({r['record_class']}) → "
                      f"{r['without_flagged']} ({r['without_flagged_class']})")
    L.append("")
    return L


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_id", nargs="?", default=RUN_DEFAULT)
    args = ap.parse_args()

    store = Store.from_env()
    try:
        run = store.require_run(args.run_id)
    except RunNotFoundError as e:
        raise SystemExit(f"error: {e}")

    record_path = store.stats_dir_for(run.run_id) / "stats.json"
    if not record_path.exists():
        raise SystemExit(f"error: no statistics of record at {record_path}; run "
                         f"scripts/analysis/analyze_experiment.py {run.run_id} first")
    record = json.loads(record_path.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        noflag, dropped = rerun_without_flagged(run.run_id, Path(tmp))

    comparison = compare(record, noflag)
    comparable = [r for r in comparison["sweep"] if r["record_class"] != "unavailable"
                  and r["without_flagged_class"] != "unavailable"]
    doc = {
        "schema": "tup-flagged-exclusion-sensitivity/1",
        "run_id": run.run_id,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alpha": ALPHA,
        "question": ("Does dropping every conversation the fidelity guard flagged — any flag at "
                     "all, cured or not — change any verdict the write-up states?"),
        "exclusion": "conversations with metadata.guard.n_flagged > 0, both arms",
        "accounting": {
            "main": dropped.get("main", {}), "ctx": dropped.get("ctx", {}),
            "loaded_total": sum(d["loaded"] for d in dropped.values()),
            "dropped_total": sum(d["dropped"] for d in dropped.values()),
            "kept_total": sum(d["kept"] for d in dropped.values()),
        },
        "summary": {
            "verdicts_total": len(comparison["verdicts"]),
            "verdicts_held": sum(1 for r in comparison["verdicts"] if r["holds"]),
            "directions_total": len(comparison["directions"]),
            "directions_same_sign": sum(1 for r in comparison["directions"] if r["same_sign"]),
            "sweep_total": len(comparison["sweep"]),
            "sweep_comparable": len(comparable),
            "sweep_held": sum(1 for r in comparable if r["holds"]),
        },
        "comparison": comparison,
        "statistics_without_flagged": noflag,
    }
    doc["all_writeup_verdicts_hold"] = bool(
        doc["summary"]["verdicts_held"] == doc["summary"]["verdicts_total"]
        and doc["summary"]["directions_same_sign"] == doc["summary"]["directions_total"])

    out = store.sensitivity_dir_for(run.run_id)
    out.mkdir(parents=True, exist_ok=True)
    (out / "flagged_exclusion.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    (out / "flagged_exclusion.md").write_text("\n".join(digest(doc)) + "\n", encoding="utf-8")
    print(f"wrote {out / 'flagged_exclusion.json'}")
    print(f"wrote {out / 'flagged_exclusion.md'}")
    print(f"all write-up verdicts hold: {doc['all_writeup_verdicts_hold']}")


if __name__ == "__main__":
    main()
