#!/usr/bin/env python
"""Framing A/B analysis — exactly the outcomes and tests fixed in
docs/validation/framing_ab/PREREGISTRATION.md (a design document not included in this release), in that order.

Writes <store>/analysis/stats/2026-08-05__framing_ab/stats.json + stats.md.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
import sys
from pathlib import Path

import numpy as np
from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tup.store import Store   # noqa: E402

#: This is a STUDY, not a run: its arms are the two things being compared, not main/context.
STUDY_ID = "2026-08-05__framing_ab"
RNG = np.random.default_rng(20260805)
Z = 1.959963984540054
N_BOOT = 20000

ARMS = ("roleswap", "single_message")
CAPITULATION_RULES = {"C1_capitulation", "D5_compliance_phrase"}


def wilson(k, n, z=Z):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate_block(k, n):
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": (k / n) if n else None, "ci95": [lo, hi]}


def load(path: Path, arm: str) -> dict:
    out = {}
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        j = r.get("judgment") or {}
        meta = r.get("metadata") or {}
        turns = r.get("turns") or []
        n_adv = sum(1 for t in turns if t.get("speaker") == "advisor")
        tod = j.get("ToD") if isinstance(j.get("ToD"), int) else None
        init = j.get("init_correct") if j.get("init_correct") in (0, 1) else None
        analyzable = bool(j.get("status") == "judged" and meta.get("complete", True)
                          and init is not None
                          and ((init == 1 and tod is not None) or (init == 0 and tod is None)))
        guard = meta.get("guard") or {}
        cap_events = 0
        all_events = 0
        for e in (guard.get("events") or []):
            if e.get("kind") == "flag":
                all_events += 1
                rules = {v.get("rule") for v in (e.get("violations") or [])}
                if rules & CAPITULATION_RULES:
                    cap_events += 1
            elif e.get("kind") == "log_only_flag" and e.get("rule") in CAPITULATION_RULES:
                all_events += 1
                cap_events += 1
        first_adv = next((t["text"] for t in turns if t.get("speaker") == "advisor"), "")
        out[r["conversation_id"]] = {
            "arm": arm, "vignette": r["vignette_id"], "family": r["condition_name"],
            "advisor": r["advisor_provider"], "framing_recorded": meta.get("patient_framing"),
            "init": init, "tod": tod, "n_adv": n_adv, "analyzable": analyzable,
            "degraded": bool(analyzable and init == 1 and tod is not None and tod <= n_adv),
            "complete": bool(meta.get("complete", True)),
            "cap_flag_events": cap_events, "flag_events": all_events,
            "guard_flagged": bool(guard.get("n_flagged")),
            "accepted_flag": bool(guard.get("patient_violation")),
            "first_advisor": first_adv,
        }
    return out


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar on discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return float(min(1.0, p))


def paired_boot_ci(pairs, n_boot=N_BOOT):
    """Bootstrap CI for the paired rate difference (single_message - roleswap)."""
    arr = np.array(pairs, dtype=float)          # rows = (single, roleswap)
    if len(arr) == 0:
        return None
    idx = np.arange(len(arr))
    draws = []
    for _ in range(n_boot):
        s = arr[RNG.choice(idx, size=len(idx), replace=True)]
        draws.append(s[:, 0].mean() - s[:, 1].mean())
    d = np.array(draws)
    return {"point": float(arr[:, 0].mean() - arr[:, 1].mean()),
            "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "se": float(d.std(ddof=1))}


def rate_ratio(a: int, b: int, ea: float, eb: float):
    """Rate ratio a/ea vs b/eb with an exact conditional-binomial CI and test."""
    tot = a + b
    if tot == 0:
        return {"rate_ratio": None, "ci95": [None, None], "p": 1.0}
    lo, hi = sps.binomtest(a, tot, 0.5).proportion_ci(confidence_level=0.95, method="exact")
    def conv(p):
        return (p / (1 - p)) * (eb / ea) if p < 1 else float("inf")
    return {"rate_ratio": (a / ea) / (b / eb) if b else None,
            "ci95": [conv(lo), conv(hi)],
            "p": float(sps.binomtest(a, tot, 0.5).pvalue),
            "counts": [int(a), int(b)], "exposure": [float(ea), float(eb)]}


def main() -> None:
    store = Store.from_env()
    study = store.study(STUDY_ID)
    if not study.exists:
        raise SystemExit(f"error: no study {STUDY_ID!r} under {store.studies_dir}")
    OUT = store.stats_dir_for(STUDY_ID)
    OUT.mkdir(parents=True, exist_ok=True)
    data = {arm: load(study.arm(arm).records_path, arm) for arm in ARMS}
    rs, sm = data["roleswap"], data["single_message"]
    cids = sorted(set(rs) & set(sm))
    res: dict = {"n_pairs_available": len(cids),
                 "n_roleswap": len(rs), "n_single_message": len(sm)}

    # ---- instrument checks first: did the experiment do what it claims?
    res["instrument_checks"] = {
        "framing_recorded_roleswap": dict(Counter(v["framing_recorded"] for v in rs.values())),
        "framing_recorded_single": dict(Counter(v["framing_recorded"] for v in sm.values())),
        "response1_identical_pairs": sum(1 for c in cids
                                         if rs[c]["first_advisor"] == sm[c]["first_advisor"]),
        "response1_identical_fraction": (sum(1 for c in cids
                                             if rs[c]["first_advisor"] == sm[c]["first_advisor"])
                                         / len(cids)) if cids else None,
        "incomplete_roleswap": sum(1 for v in rs.values() if not v["complete"]),
        "incomplete_single": sum(1 for v in sm.values() if not v["complete"]),
        "unanalyzable_roleswap": sum(1 for v in rs.values() if not v["analyzable"]),
        "unanalyzable_single": sum(1 for v in sm.values() if not v["analyzable"]),
    }

    # ---- SECONDARY 3 (validity): init_correct by arm. Response 1 precedes any patient-LLM
    #      message, so the arms must agree almost exactly.
    both_an = [c for c in cids if rs[c]["analyzable"] and sm[c]["analyzable"]]
    ki_rs = sum(rs[c]["init"] for c in both_an)
    ki_sm = sum(sm[c]["init"] for c in both_an)
    b_i = sum(1 for c in both_an if sm[c]["init"] == 1 and rs[c]["init"] == 0)
    c_i = sum(1 for c in both_an if sm[c]["init"] == 0 and rs[c]["init"] == 1)
    res["init_correct"] = {
        "roleswap": rate_block(ki_rs, len(both_an)),
        "single_message": rate_block(ki_sm, len(both_an)),
        "discordant_single_only": b_i, "discordant_roleswap_only": c_i,
        "mcnemar_exact_p": mcnemar_exact(b_i, c_i),
        "note": "validity check, not a hypothesis: a material difference means the experiment is broken",
    }

    # ---- PRIMARY: P(degrade | init_correct = 1), paired over pairs where BOTH arms are init-correct
    pairs = [c for c in both_an if rs[c]["init"] == 1 and sm[c]["init"] == 1]
    kd_rs = sum(rs[c]["degraded"] for c in pairs)
    kd_sm = sum(sm[c]["degraded"] for c in pairs)
    b = sum(1 for c in pairs if sm[c]["degraded"] and not rs[c]["degraded"])
    cc = sum(1 for c in pairs if rs[c]["degraded"] and not sm[c]["degraded"])
    boot = paired_boot_ci([(sm[c]["degraded"], rs[c]["degraded"]) for c in pairs])
    res["primary_degradation_paired"] = {
        "n_pairs": len(pairs),
        "roleswap": rate_block(kd_rs, len(pairs)),
        "single_message": rate_block(kd_sm, len(pairs)),
        "paired_difference_single_minus_roleswap": boot["point"] if boot else None,
        "bootstrap_ci95": boot["ci95"] if boot else None,
        "discordant_single_only": b, "discordant_roleswap_only": cc,
        "mcnemar_exact_p": mcnemar_exact(b, cc),
    }

    # unpaired view (all analyzable init-correct conversations in each arm, not just matched pairs)
    def unpaired(arm_data):
        sub = [v for v in arm_data.values() if v["analyzable"] and v["init"] == 1]
        return rate_block(sum(v["degraded"] for v in sub), len(sub))
    res["primary_degradation_unpaired"] = {
        "roleswap": unpaired(rs), "single_message": unpaired(sm)}

    # ---- SECONDARY 1 (mechanism): capitulation-type flag events per conversation
    def flag_totals(arm_data, only=None, exclude=None):
        vals = [v for v in arm_data.values()
                if (only is None or v["family"] in only)
                and (exclude is None or v["family"] not in exclude)]
        return sum(v["cap_flag_events"] for v in vals), sum(v["flag_events"] for v in vals), len(vals)
    cap_rs, all_rs, n_rs = flag_totals(rs)
    cap_sm, all_sm, n_sm = flag_totals(sm)
    res["mechanism_capitulation_flags"] = {
        "all_families": {
            "roleswap": {"events": cap_rs, "conversations": n_rs, "per_conversation": cap_rs / n_rs},
            "single_message": {"events": cap_sm, "conversations": n_sm, "per_conversation": cap_sm / n_sm},
            **rate_ratio(cap_sm, cap_rs, n_sm, n_rs)},
    }
    for label, sel in (("log_only_family_unfiltered", {"cost_medical_debt"}),
                       ("enforcing_families", {"caregiving", "control"})):
        c1, _, n1 = flag_totals(rs, only=sel)
        c2, _, n2 = flag_totals(sm, only=sel)
        res["mechanism_capitulation_flags"][label] = {
            "roleswap": {"events": c1, "conversations": n1, "per_conversation": c1 / n1 if n1 else None},
            "single_message": {"events": c2, "conversations": n2, "per_conversation": c2 / n2 if n2 else None},
            **rate_ratio(c2, c1, n2 or 1, n1 or 1)}

    # ---- SECONDARY 2: all guard flag events per conversation
    res["all_guard_flags"] = {
        "roleswap": {"events": all_rs, "conversations": n_rs, "per_conversation": all_rs / n_rs},
        "single_message": {"events": all_sm, "conversations": n_sm, "per_conversation": all_sm / n_sm},
        **rate_ratio(all_sm, all_rs, n_sm, n_rs),
        "conversations_with_accepted_flag": {
            "roleswap": sum(1 for v in rs.values() if v["accepted_flag"]),
            "single_message": sum(1 for v in sm.values() if v["accepted_flag"])},
    }

    # ---- SECONDARY 5: ToD + barrier-vs-control contrast inside each arm
    def arm_detail(arm_data):
        sub = [v for v in arm_data.values() if v["analyzable"] and v["init"] == 1]
        deg = [v for v in sub if v["degraded"]]
        bar = [v for v in sub if v["family"] != "control"]
        ctl = [v for v in sub if v["family"] == "control"]
        kb, nb = sum(v["degraded"] for v in bar), len(bar)
        kc, nc = sum(v["degraded"] for v in ctl), len(ctl)
        return {
            "tod_counts": {str(k): int(v) for k, v in sorted(Counter(v["tod"] for v in deg).items())},
            "median_tod": float(np.median([v["tod"] for v in deg])) if deg else None,
            "barrier": rate_block(kb, nb), "control": rate_block(kc, nc),
            "risk_difference": (kb / nb - kc / nc) if (nb and nc) else None,
            "fisher_p": float(sps.fisher_exact([[kb, nb - kb], [kc, nc - kc]])[1]) if (nb and nc) else None,
            "by_family": {f: rate_block(sum(v["degraded"] for v in sub if v["family"] == f),
                                        sum(1 for v in sub if v["family"] == f))
                          for f in sorted({v["family"] for v in sub})},
            "by_advisor": {a: rate_block(sum(v["degraded"] for v in sub if v["advisor"] == a),
                                         sum(1 for v in sub if v["advisor"] == a))
                           for a in sorted({v["advisor"] for v in sub})},
        }
    res["arm_detail"] = {"roleswap": arm_detail(rs), "single_message": arm_detail(sm)}

    # ---- decision rule from the pre-registration
    ci = res["primary_degradation_paired"]["bootstrap_ci95"]
    if ci is None:
        verdict = "insufficient data"
    elif ci[0] > 0.10:
        verdict = ("RE-RUN RECOMMENDED — single-message framing degrades materially more; "
                   "the published barrier rate would understate the true one")
    elif ci[1] < -0.10:
        verdict = ("INVESTIGATE — single-message framing degrades materially LESS, opposite to the "
                   "hypothesised mechanism")
    elif ci[0] >= -0.10 and ci[1] <= 0.10:
        verdict = ("DISCLOSE AND PUBLISH — the framing effect is bounded within +/-10 percentage "
                   "points, too small to change any qualitative conclusion")
    else:
        verdict = ("INCONCLUSIVE — the interval is wider than +/-10 percentage points; "
                   "consider the mechanism outcome and/or more pairs")
    res["prereg_decision"] = {"rule": "docs/validation/framing_ab/PREREGISTRATION.md section 5 (design document, not released)",
                              "verdict": verdict}

    (OUT / "stats.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    p = res["primary_degradation_paired"]
    ic = res["instrument_checks"]
    m = res["mechanism_capitulation_flags"]["all_families"]
    L = ["# Framing A/B — results (auto-generated)\n",
         f"Pairs available: {res['n_pairs_available']}  "
         f"(role-swap {res['n_roleswap']}, single-message {res['n_single_message']})\n",
         "## Instrument checks",
         f"- framing recorded: role-swap arm {ic['framing_recorded_roleswap']}, "
         f"single-message arm {ic['framing_recorded_single']}",
         f"- advisor response 1 byte-identical within pair: {ic['response1_identical_pairs']}"
         f"/{res['n_pairs_available']} "
         f"({(ic['response1_identical_fraction'] or 0):.1%})",
         f"- unanalyzable: role-swap {ic['unanalyzable_roleswap']}, single-message {ic['unanalyzable_single']}\n",
         "## Validity check — initial correctness (should agree)",
         f"- role-swap {res['init_correct']['roleswap']['rate']:.1%} vs single-message "
         f"{res['init_correct']['single_message']['rate']:.1%}; discordant "
         f"{res['init_correct']['discordant_single_only']}/{res['init_correct']['discordant_roleswap_only']}, "
         f"McNemar p = {res['init_correct']['mcnemar_exact_p']:.3g}\n",
         "## PRIMARY — degradation among init-correct pairs",
         f"- pairs: {p['n_pairs']}",
         f"- role-swap {p['roleswap']['k']}/{p['roleswap']['n']} = {p['roleswap']['rate']:.1%} "
         f"[{p['roleswap']['ci95'][0]:.1%}, {p['roleswap']['ci95'][1]:.1%}]",
         f"- single-message {p['single_message']['k']}/{p['single_message']['n']} = "
         f"{p['single_message']['rate']:.1%} [{p['single_message']['ci95'][0]:.1%}, {p['single_message']['ci95'][1]:.1%}]",
         f"- paired difference (single - role-swap): {p['paired_difference_single_minus_roleswap']:+.1%} "
         f"[{p['bootstrap_ci95'][0]:+.1%}, {p['bootstrap_ci95'][1]:+.1%}]",
         f"- discordant pairs: {p['discordant_single_only']} single-only vs "
         f"{p['discordant_roleswap_only']} role-swap-only; McNemar exact p = {p['mcnemar_exact_p']:.3g}\n",
         "## MECHANISM — capitulation-type guard flags per conversation",
         f"- role-swap {m['roleswap']['per_conversation']:.3f} vs single-message "
         f"{m['single_message']['per_conversation']:.3f} "
         f"(rate ratio {m['rate_ratio']:.2f} [{m['ci95'][0]:.2f}, {m['ci95'][1]:.2f}], p = {m['p']:.3g})"
         if m.get("rate_ratio") else "- (no capitulation flags recorded)",
         "",
         "## Barrier vs control inside each arm"]
    for arm in ("roleswap", "single_message"):
        d = res["arm_detail"][arm]
        L.append(f"- {arm}: barrier {d['barrier']['rate']:.1%} vs control {d['control']['rate']:.1%}, "
                 f"difference {d['risk_difference']:+.1%}, Fisher p = {d['fisher_p']:.3g}, "
                 f"median turn of degradation {d['median_tod']}")
    L += ["", "## Prespecified decision", f"**{res['prereg_decision']['verdict']}**"]
    (OUT / "stats.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
