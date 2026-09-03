"""Human judge-agreement analysis: the author's blind verdicts vs the 3-judge panel.

Produces the citable figures for the write-up's human-check section ("Three judges and a human check") from the frozen audit
files (``results/analysis/human_audit/<run>/sample.json`` + ``verdicts.jsonl``) and the run of
record's judged records. The audit MEASURES agreement; nothing here feeds back into the frozen
results.

Method (matching the audit design in the sample README):
  - The sample is stratified by PANEL decision kind (degraded / init0 / held_firm) with the rare
    strata deliberately over-represented, so raw sample rates are NOT run-level estimates. Every
    run-level ("weighted") figure reweights each conversation by ``pop_s / (analyzable * n_s)`` —
    the run's own label distribution recorded in ``sample.json``.
  - Agreement outcomes:
      * init_correct        — binary, all 50.
      * decision kind       — 3-way label each rater implies: init0 (init=0), degraded
                              (init=1, ToD <= T), held_firm (init=1, ToD = T+1).
      * degraded-vs-survived — binary, conditioned on BOTH raters saying init=1.
      * ToD exact / ±1      — conditioned on BOTH raters saying degraded.
  - Cohen's kappa: unweighted on the raw sample (disclosed as composition-biased) and a
    population-weighted variant (observed and expected agreement both computed under the
    weights, so the panel marginals reproduce the run's label rates).
  - Uncertainty: stratified bootstrap (resample conversations with replacement WITHIN each panel
    stratum, preserving stratum sizes), percentile 95% CIs, fixed seed. Conditional metrics whose
    conditioning set can be empty in a resample are skipped in that replicate.

Run:  python scripts/analysis/human_audit_agreement.py
Writes ``agreement.json`` + ``agreement.md`` next to the audit files.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tup.output import human_audit as HA  # noqa: E402
from tup.output import metrics as M
from tup.store import Store

RUN_OF_RECORD = "2026-08-06__full_experiment"
ARM = "main"
BOOT_SEED = 20260626
BOOT_REPS = 10_000
STRATA = ("degraded", "init0", "held_firm")


def decision_kind(init: int, tod, T: int) -> str:
    if init == 0:
        return "init0"
    return "degraded" if isinstance(tod, int) and tod <= T else "held_firm"


def build_rows(store: Store, run_id: str, arm: str) -> tuple[list[dict], dict]:
    sample_doc = json.loads(HA.sample_path(store, run_id).read_text())
    verdicts = HA.load_verdicts(store, run_id)
    records = {}
    with store.run(run_id).arm(arm).records_path.open() as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                records[r["conversation_id"]] = r

    missing = [e["conversation_id"] for e in sample_doc["sample"]
               if e["conversation_id"] not in verdicts]
    if missing:
        raise SystemExit(f"audit incomplete: {len(missing)} conversations unjudged: {missing}")

    rows = []
    for e in sorted(sample_doc["sample"], key=lambda e: e["order"]):
        cid = e["conversation_id"]
        rec = records[cid]
        j, h = rec["judgment"], verdicts[cid]
        T = M.num_advisor_responses(rec)
        rows.append({
            "conversation_id": cid,
            "order": e["order"],
            "stratum": e["stratum"],
            "T": T,
            "panel": {"init_correct": j["init_correct"], "ToD": j["ToD"],
                      "kind": decision_kind(j["init_correct"], j["ToD"], T)},
            "human": {"init_correct": h["init_correct"], "ToD": h["ToD"],
                      "kind": decision_kind(h["init_correct"], h["ToD"], T)},
            "note": h.get("note") or "",
        })
    return rows, sample_doc


def weights(rows: list[dict], population: dict) -> dict:
    """Per-conversation weight w_s = pop_s / (analyzable * n_s); weights sum to 1."""
    n_s = {s: sum(1 for r in rows if r["stratum"] == s) for s in STRATA}
    total = population["analyzable"]
    return {s: population[s] / (total * n_s[s]) for s in STRATA if n_s[s]}


def agree_stats(rows: list[dict], population: dict) -> dict:
    """All agreement figures for one set of rows (used for the point estimate and each bootstrap
    replicate)."""
    w = weights(rows, population)

    def wsum(pred) -> float:
        return sum(w[r["stratum"]] for r in rows if pred(r))

    def kappa(label, universe, weighted: bool):
        """Cohen's kappa for rater label ``label(r, who)`` over categories ``universe``."""
        if weighted:
            tot = wsum(lambda r: True)
            po = wsum(lambda r: label(r, "panel") == label(r, "human")) / tot
            pe = sum((wsum(lambda r, k=k: label(r, "panel") == k) / tot)
                     * (wsum(lambda r, k=k: label(r, "human") == k) / tot) for k in universe)
        else:
            n = len(rows)
            po = sum(1 for r in rows if label(r, "panel") == label(r, "human")) / n
            pe = sum((sum(1 for r in rows if label(r, "panel") == k) / n)
                     * (sum(1 for r in rows if label(r, "human") == k) / n) for k in universe)
        return None if pe == 1 else (po - pe) / (1 - pe)

    init_label = lambda r, who: r[who]["init_correct"]
    kind_label = lambda r, who: r[who]["kind"]

    per_stratum = {}
    for s in STRATA:
        sub = [r for r in rows if r["stratum"] == s]
        if not sub:
            continue
        per_stratum[s] = {
            "n": len(sub),
            "init_agree": sum(1 for r in sub if init_label(r, "panel") == init_label(r, "human")) / len(sub),
            "kind_agree": sum(1 for r in sub if kind_label(r, "panel") == kind_label(r, "human")) / len(sub),
        }

    both_init1 = [r for r in rows if r["panel"]["init_correct"] == 1 and r["human"]["init_correct"] == 1]
    both_degraded = [r for r in rows if r["panel"]["kind"] == "degraded" and r["human"]["kind"] == "degraded"]
    deg_label = lambda r, who: r[who]["kind"] == "degraded"

    out = {
        "n": len(rows),
        "per_stratum": per_stratum,
        "init": {
            "raw_agree": sum(1 for r in rows if init_label(r, "panel") == init_label(r, "human")) / len(rows),
            "weighted_agree": wsum(lambda r: init_label(r, "panel") == init_label(r, "human")),
            "raw_kappa": kappa(init_label, (0, 1), weighted=False),
            "weighted_kappa": kappa(init_label, (0, 1), weighted=True),
        },
        "decision_kind": {
            "raw_agree": sum(1 for r in rows if kind_label(r, "panel") == kind_label(r, "human")) / len(rows),
            "weighted_agree": wsum(lambda r: kind_label(r, "panel") == kind_label(r, "human")),
            "raw_kappa": kappa(kind_label, STRATA, weighted=False),
            "weighted_kappa": kappa(kind_label, STRATA, weighted=True),
        },
        "degraded_vs_survived_given_both_init1": {
            "n": len(both_init1),
            "raw_agree": (sum(1 for r in both_init1 if deg_label(r, "panel") == deg_label(r, "human"))
                          / len(both_init1)) if both_init1 else None,
            "raw_kappa": None,  # filled below from the both_init1 subset only
        },
        "tod_given_both_degraded": {
            "n": len(both_degraded),
            "exact": (sum(1 for r in both_degraded if r["panel"]["ToD"] == r["human"]["ToD"])
                      / len(both_degraded)) if both_degraded else None,
            "within_1": (sum(1 for r in both_degraded
                             if abs(r["panel"]["ToD"] - r["human"]["ToD"]) <= 1)
                         / len(both_degraded)) if both_degraded else None,
        },
        "implied_degradation_share": {
            # Each rater's implied share of ALL analyzable conversations labelled degraded,
            # reweighting the sample to the run's label distribution. The panel's figure equals
            # the run's own degraded share by construction of the weights; the human figure is
            # what the run-level rate would have been under the human's labels — the
            # do-the-disagreements-cancel check.
            "panel_weighted": wsum(lambda r: kind_label(r, "panel") == "degraded"),
            "human_weighted": wsum(lambda r: kind_label(r, "human") == "degraded"),
        },
    }
    # the binary-conditional kappa above must only see both_init1 rows
    if both_init1:
        sub = both_init1
        n = len(sub)
        po = sum(1 for r in sub if deg_label(r, "panel") == deg_label(r, "human")) / n
        pe = sum((sum(1 for r in sub if deg_label(r, "panel") == k) / n)
                 * (sum(1 for r in sub if deg_label(r, "human") == k) / n) for k in (True, False))
        out["degraded_vs_survived_given_both_init1"]["raw_kappa"] = (
            None if pe == 1 else (po - pe) / (1 - pe))
    return out


#: (json-path, extractor) pairs bootstrapped for CIs.
CI_TARGETS = {
    "init.weighted_agree": lambda s: s["init"]["weighted_agree"],
    "init.raw_kappa": lambda s: s["init"]["raw_kappa"],
    "init.weighted_kappa": lambda s: s["init"]["weighted_kappa"],
    "decision_kind.weighted_agree": lambda s: s["decision_kind"]["weighted_agree"],
    "decision_kind.raw_kappa": lambda s: s["decision_kind"]["raw_kappa"],
    "decision_kind.weighted_kappa": lambda s: s["decision_kind"]["weighted_kappa"],
    "per_stratum.degraded.kind_agree": lambda s: s["per_stratum"]["degraded"]["kind_agree"],
    "per_stratum.held_firm.kind_agree": lambda s: s["per_stratum"]["held_firm"]["kind_agree"],
    "per_stratum.init0.kind_agree": lambda s: s["per_stratum"]["init0"]["kind_agree"],
    "tod_given_both_degraded.exact": lambda s: s["tod_given_both_degraded"]["exact"],
    "tod_given_both_degraded.within_1": lambda s: s["tod_given_both_degraded"]["within_1"],
    "implied_degradation_share.human_weighted":
        lambda s: s["implied_degradation_share"]["human_weighted"],
}


def bootstrap_cis(rows: list[dict], population: dict, *, reps: int, seed: int) -> dict:
    rng = random.Random(seed)
    by_stratum = {s: [r for r in rows if r["stratum"] == s] for s in STRATA}
    draws: dict = {k: [] for k in CI_TARGETS}
    for _ in range(reps):
        resample = []
        for s, sub in by_stratum.items():
            resample.extend(rng.choices(sub, k=len(sub)))
        stats = agree_stats(resample, population)
        for key, get in CI_TARGETS.items():
            try:
                val = get(stats)
            except (KeyError, TypeError):
                val = None
            if val is not None:
                draws[key].append(val)

    def pct(vals, q):
        vals = sorted(vals)
        return vals[min(len(vals) - 1, max(0, int(q * len(vals))))]

    return {key: {"lo": pct(vals, 0.025), "hi": pct(vals, 0.975), "n_reps_defined": len(vals)}
            for key, vals in draws.items() if vals}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=RUN_OF_RECORD)
    ap.add_argument("--arm", default=ARM)
    ap.add_argument("--reps", type=int, default=BOOT_REPS)
    args = ap.parse_args()

    store = Store.from_env()
    rows, sample_doc = build_rows(store, args.run, args.arm)
    population = sample_doc["population"]
    stats = agree_stats(rows, population)
    cis = bootstrap_cis(rows, population, reps=args.reps, seed=BOOT_SEED)

    disagreements = [r for r in rows if r["panel"]["kind"] != r["human"]["kind"]
                     or (r["panel"]["kind"] == "degraded" == r["human"]["kind"]
                         and r["panel"]["ToD"] != r["human"]["ToD"])]

    doc = {
        "schema": "tup-human-audit-agreement/1",
        "run_id": args.run,
        "arm": args.arm,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        # repo-relative so the artifact carries no machine-specific absolute path
        "inputs": {"sample": str(HA.sample_path(store, args.run).relative_to(store.root.parent)),
                   "verdicts": str(HA.verdicts_path(store, args.run).relative_to(store.root.parent)),
                   "n_judged": len(rows)},
        "method": {
            "weights": "pop_s / (analyzable * n_s) per conversation, from sample.json population",
            "bootstrap": {"kind": "stratified within panel stratum", "reps": args.reps,
                          "seed": BOOT_SEED, "ci": "percentile 95%"},
            "caveats": [
                "single rater (the author), with prior exposure to the run's aggregate results",
                "raw-sample figures are composition-biased by design (rare strata over-sampled); "
                "weighted figures are the run-level estimates",
                "conditional metrics (ToD given both-degraded) have small n; CIs are wide",
            ],
        },
        "stats": stats,
        "ci95": cis,
        "disagreements": disagreements,
    }

    out_dir = HA.audit_dir(store, args.run)
    (out_dir / "agreement.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = render_md(doc)
    (out_dir / "agreement.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {out_dir / 'agreement.json'} and agreement.md")


def fmt(x, pct=True):
    if x is None:
        return "—"
    return f"{100 * x:.1f}%" if pct else f"{x:.3f}"


def ci(doc, key, pct=True):
    c = doc["ci95"].get(key)
    if not c:
        return ""
    return f" (95% CI {fmt(c['lo'], pct)}–{fmt(c['hi'], pct)})"


def render_md(doc: dict) -> str:
    s = doc["stats"]
    L = []
    L.append(f"# Human–panel agreement — {doc['run_id']} ({doc['arm']} arm)\n")
    L.append(f"n = {s['n']} blind verdicts (single rater); weighted figures reweight the "
             f"stratified sample to the run's label distribution. Bootstrap: stratified, "
             f"{doc['method']['bootstrap']['reps']} reps, seed {doc['method']['bootstrap']['seed']}.\n")
    L.append("## Headline figures\n")
    L.append("| metric | raw sample | run-weighted |")
    L.append("|---|---|---|")
    L.append(f"| init_correct agreement | {fmt(s['init']['raw_agree'])} | "
             f"{fmt(s['init']['weighted_agree'])}{ci(doc, 'init.weighted_agree')} |")
    L.append(f"| init_correct Cohen's κ | {fmt(s['init']['raw_kappa'], pct=False)}"
             f"{ci(doc, 'init.raw_kappa', pct=False)} | "
             f"{fmt(s['init']['weighted_kappa'], pct=False)}{ci(doc, 'init.weighted_kappa', pct=False)} |")
    L.append(f"| decision-kind agreement (3-way) | {fmt(s['decision_kind']['raw_agree'])} | "
             f"{fmt(s['decision_kind']['weighted_agree'])}{ci(doc, 'decision_kind.weighted_agree')} |")
    L.append(f"| decision-kind Cohen's κ | {fmt(s['decision_kind']['raw_kappa'], pct=False)}"
             f"{ci(doc, 'decision_kind.raw_kappa', pct=False)} | "
             f"{fmt(s['decision_kind']['weighted_kappa'], pct=False)}"
             f"{ci(doc, 'decision_kind.weighted_kappa', pct=False)} |")
    L.append("")
    L.append("## Per-stratum decision-kind agreement\n")
    L.append("| panel stratum | n | agreement |")
    L.append("|---|---|---|")
    for st, d in s["per_stratum"].items():
        L.append(f"| {st} | {d['n']} | {fmt(d['kind_agree'])}"
                 f"{ci(doc, f'per_stratum.{st}.kind_agree')} |")
    L.append("")
    bd = s["tod_given_both_degraded"]
    bi = s["degraded_vs_survived_given_both_init1"]
    L.append("## Conditional metrics\n")
    L.append(f"- degraded-vs-survived agreement, given both raters say init=1 "
             f"(n={bi['n']}): {fmt(bi['raw_agree'])}, κ = {fmt(bi['raw_kappa'], pct=False)}")
    L.append(f"- ToD agreement, given both raters say degraded (n={bd['n']}): "
             f"exact {fmt(bd['exact'])}{ci(doc, 'tod_given_both_degraded.exact')}, "
             f"±1 turn {fmt(bd['within_1'])}{ci(doc, 'tod_given_both_degraded.within_1')}")
    im = s["implied_degradation_share"]
    hw, pw = im["human_weighted"], im["panel_weighted"]
    # State the comparison; only claim cancellation when the shares actually land close.
    gap_note = (" — the disagreements largely cancel at run level"
                if hw is not None and pw is not None and abs(hw - pw) <= 0.02 else "")
    L.append(f"- implied run-level degradation share of all analyzable main-arm conversations (weighted): human "
             f"{fmt(hw)}"
             f"{ci(doc, 'implied_degradation_share.human_weighted')} vs panel "
             f"{fmt(pw)}{gap_note}")
    L.append("")
    L.append("## Disagreements\n")
    L.append("| conversation | panel | human | note |")
    L.append("|---|---|---|---|")
    for r in doc["disagreements"]:
        p, h = r["panel"], r["human"]
        L.append(f"| {r['conversation_id']} | {p['kind']} (init {p['init_correct']}, "
                 f"ToD {p['ToD']}) | {h['kind']} (init {h['init_correct']}, ToD {h['ToD']}) | "
                 f"{r['note']} |")
    L.append("")
    for c in doc["method"]["caveats"]:
        L.append(f"*Caveat: {c}*  ")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    main()
