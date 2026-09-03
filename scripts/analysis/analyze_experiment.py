#!/usr/bin/env python
"""Run-1 analysis — every statistic the write-up reports, computed in one deterministic pass.

Implements the prespecified analysis exactly:
  - mixed-effects logistic regression on degradation among init-correct conversations,
    fixed effects barrier-vs-control (primary) / family (secondary) / advisor, vignette random
    intercepts (maximum likelihood via Gauss-Hermite quadrature — scripts/analysis/glmm.py);
    population-averaged (GEE, vignette-clustered) and cluster-robust logistic as companions;
  - all five barrier families tested identically against control in ONE Holm family of five;
  - Resistance curves P(ToD > t) descriptively per family and per advisor;
  - init_correct reported separately as its own secondary outcome;
  - bootstrap CIs clustered by vignette as robustness.

Plus the prespecified decisive-invention quarantine, sensitivity analyses (quarantine on/off,
guard-flagged conversations dropped), instrument-validity statistics (panel agreement, judge-seat
heterogeneity), and the context arm read descriptively.

Writes <store>/analysis/stats/<run-id>/stats.json (machine) + stats.md (human).
"""
from __future__ import annotations

import json
import math
import argparse
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tup.store import RunNotFoundError, Store   # noqa: E402

RNG = np.random.default_rng(20260805)
N_BOOT = 5000
PEN_SD = 5.0   # weakly-informative ridge SD (log-odds): the pooled model applies it only where separation occurs; the per-family models apply it throughout

# Decisive-invention quarantine (the convention documented in the run's exclusions/README.md, adopted before launch). Populated from the
# post-run audit's adjudicated verdicts via --quarantine; the literal below is the fallback only
# when no file is supplied. Empty by default so a missing file can never silently re-apply a
# PREVIOUS run's quarantine set to a different run's records.
QUARANTINE = {"main": set(), "ctx": set()}
UNQUARANTINED_MODE = False   # set by main() for the --unquarantined sensitivity pass


def load_quarantine(path):
    """Replace QUARANTINE from an adjudicated audit file.

    Accepts the context arm under EITHER ``ctx`` (what the adjudicated files say, and what this
    module's own keys are) or ``context`` (what the store's arm directory is named). Reading only
    one spelling silently yields an empty exclusion set for the other — and an exclusion set that is
    quietly dropped still produces a number, which is the dangerous kind of wrong.
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    QUARANTINE["main"] = set(doc.get("main") or [])
    QUARANTINE["ctx"] = set(doc.get("ctx") or []) | set(doc.get("context") or [])
    return QUARANTINE

# Family CLASSES. Pooling "everything that isn't control" would be wrong here: the seventh
# condition carries the same resistance directive WITHOUT a structural obstacle, so each
# family's class is declared explicitly rather than inferred from "!= control".
#   cooperative   — no obstacle and no resistance directive (the Run-1 control)
#   nonstructural — resistance directive, obstacle is dread rather than money/transport/dependents/job
#   structural    — resistance directive + a structural obstacle (the five barrier families)
FAMILY_CLASS = {
    "control":                  "cooperative",
    "hospital_fear":            "nonstructural",
    "caregiving":               "structural",
    "transport_ambulance_cost": "structural",
    "work":                     "structural",
    "cost_medical_debt":        "structural",
    "no_insurance":             "structural",
}
FAMILIES = list(FAMILY_CLASS)
STRUCTURAL = [f for f, c in FAMILY_CLASS.items() if c == "structural"]
NONSTRUCTURAL = [f for f, c in FAMILY_CLASS.items() if c == "nonstructural"]
CONTROL = "control"
# Back-compat alias: Run-1 outputs and the per-family Holm table both mean "the five structural
# families tested against control", which is what BARRIERS denotes.
BARRIERS = STRUCTURAL
LABEL = {
    "control": "control",
    "hospital_fear": "hospital fear (non-structural)",
    "caregiving": "caregiving",
    "transport_ambulance_cost": "transport / ambulance cost",
    "work": "work",
    "cost_medical_debt": "cost / medical debt",
    "no_insurance": "no insurance",
}
ADVISOR_LABEL = {
    "openai": "GPT-5.6-terra", "anthropic": "Claude-Sonnet-5", "meta": "Llama-4-Maverick",
    "google": "Gemini-3.6-flash", "xai": "Grok-4.3",
}

Z = 1.959963984540054


# --------------------------------------------------------------------------- loading
def load(path: Path, arm: str) -> pd.DataFrame:
    rows = []
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        j = r.get("judgment") or {}
        meta = r.get("metadata") or {}
        turns = r.get("turns") or []
        n_adv = sum(1 for t in turns if t.get("speaker") == "advisor")
        tod_raw = j.get("ToD")
        tod = tod_raw if isinstance(tod_raw, int) else None
        init = j.get("init_correct") if j.get("init_correct") in (0, 1) else None
        judged = j.get("status") == "judged"
        complete = bool(meta.get("complete", True))
        analyzable = bool(
            judged and complete and init is not None
            and ((init == 1 and tod is not None) or (init == 0 and tod is None))
        )
        panel = j.get("panel") or []
        guard = meta.get("guard") or {}
        rows.append({
            "cid": r["conversation_id"], "arm": arm,
            "vignette": r["vignette_id"], "family": r["condition_name"],
            "advisor": r["advisor_provider"], "advisor_model": r.get("advisor_model"),
            "replicate": r.get("replicate"), "seed": r.get("seed"),
            "n_adv": n_adv, "n_turns": n_adv,
            "init": init, "tod": tod, "tod_raw": tod_raw,
            "irn": j.get("init_response_number"),
            "analyzable": analyzable, "status": j.get("status"),
            "degraded": bool(analyzable and init == 1 and tod is not None and tod <= n_adv),
            "quote": j.get("degraded_turn_quote") or "",
            "aggregation": j.get("aggregation"),
            "panel_providers": [m.get("judge_provider") for m in panel],
            "panel_init": [m.get("init_correct") for m in panel],
            "panel_tod": [m.get("ToD") for m in panel],
            "panel_status": [m.get("status") for m in panel],
            "complete": complete,
            "guard_flagged": bool(guard.get("n_flagged")),
            "guard_accepted_flag": bool(guard.get("patient_violation")),
            "guard_n_flagged": int(guard.get("n_flagged") or 0),
            "guard_n_cured": int(guard.get("n_cured") or 0),
            "quarantined": r["conversation_id"] in QUARANTINE[arm],
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- basic stats
def wilson(k: int, n: int, z: float = Z) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe_rd(k1: int, n1: int, k0: int, n0: int, z: float = Z):
    """Newcombe method-10 CI for a difference of proportions (p1 - p0)."""
    l1, u1 = wilson(k1, n1, z)
    l0, u0 = wilson(k0, n0, z)
    d = k1 / n1 - k0 / n0
    lo = d - math.sqrt((k1 / n1 - l1) ** 2 + (u0 - k0 / n0) ** 2)
    hi = d + math.sqrt((u1 - k1 / n1) ** 2 + (k0 / n0 - l0) ** 2)
    return d, max(-1.0, lo), min(1.0, hi)


def or_ci(a: int, b: int, c: int, d: int):
    """Odds ratio with Woolf CI; Haldane-Anscombe 0.5 correction when any cell is 0."""
    corrected = min(a, b, c, d) == 0
    A, B, C, D = (a + .5, b + .5, c + .5, d + .5) if corrected else (a, b, c, d)
    orv = (A * D) / (B * C)
    se = math.sqrt(1 / A + 1 / B + 1 / C + 1 / D)
    return orv, orv * math.exp(-Z * se), orv * math.exp(Z * se), corrected


def mde_two_proportion(n1, n0, p0, alpha=0.05, power=0.80):
    """Bisection MDE: smallest risk difference detectable at the given alpha/power
    under the two-proportion normal approximation."""
    za, zb = sps.norm.isf(alpha / 2), sps.norm.isf(1 - power)
    lo, hi = 0.0, 1.0 - p0
    for _ in range(200):
        mid = (lo + hi) / 2
        p1 = p0 + mid
        se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
        if (mid / se) >= (za + zb):
            hi = mid
        else:
            lo = mid
    return hi


def fisher(a: int, b: int, c: int, d: int) -> float:
    return float(sps.fisher_exact([[a, b], [c, d]], alternative="two-sided")[1])


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        val = min(1.0, (m - i) * p)
        running = max(running, val)          # enforce monotonicity
        adj[k] = running
    return adj


def rate_block(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": (k / n) if n else None, "ci95": [lo, hi]}


def contrast(df: pd.DataFrame, fam: str, outcome: str = "degraded", base: str = "control") -> dict:
    """One family vs control on `outcome`, among the relevant denominator."""
    sub = df[df.family.isin([fam, base])]
    t = sub[sub.family == fam]
    c = sub[sub.family == base]
    kt, nt = int(t[outcome].sum()), len(t)
    kc, nc = int(c[outcome].sum()), len(c)
    rd, rdlo, rdhi = newcombe_rd(kt, nt, kc, nc)
    orv, orlo, orhi, corrected = or_ci(kt, nt - kt, kc, nc - kc)
    return {
        "family": fam, "label": LABEL[fam],
        "treated": rate_block(kt, nt), "control": rate_block(kc, nc),
        "risk_difference": rd, "rd_ci95": [rdlo, rdhi],
        "risk_ratio": (kt / nt) / (kc / nc) if kc else None,
        "odds_ratio": orv, "or_ci95": [orlo, orhi], "or_zero_cell_corrected": corrected,
        "fisher_p": fisher(kt, nt - kt, kc, nc - kc),
    }


# --------------------------------------------------------------------------- models
def fit_models(d: pd.DataFrame, label: str) -> dict:
    """Prespecified mixed-effects logistic regression + companions, on init-correct rows."""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    d = d.copy()
    d["y"] = d.degraded.astype(int)
    # "barrier" here means STRUCTURAL barrier: the fear comparator carries the same resistance
    # directive but no structural obstacle, so pooling it in would contaminate the estimand.
    d["barrier"] = d.family.isin(STRUCTURAL).astype(int)
    d["advisor_c"] = pd.Categorical(d.advisor, categories=["anthropic", "google", "meta", "openai", "xai"])
    d["vig"] = pd.Categorical(d.vignette)
    # The POOLED treated-vs-reference models estimate the prespecified structural-vs-cooperative
    # contrast, so their ESTIMATION SAMPLE must exclude the non-structural comparator entirely.
    # Marking fear's rows barrier=0 is not enough: that silently pools them into the REFERENCE
    # group, and because fear degrades at least as much as the structural families it drags the
    # baseline up and collapses the odds ratio by an order of magnitude. Fear is analysed in
    # pooled_by_class and, as its own
    # dummy, in the all-conditions per-family model below — never inside the primary reference.
    dpool = d[d.family.isin(STRUCTURAL + [CONTROL])].copy()
    pool_events_ref = int(dpool.loc[dpool.barrier == 0, "y"].sum())
    pool_events_treated = int(dpool.loc[dpool.barrier == 1, "y"].sum())
    pooled_zero_cell = (pool_events_ref == 0) or (pool_events_treated == 0)
    pool_note = ("estimation sample = five structural conditions + cooperative control "
                 "(the non-structural comparator is excluded by design)")
    out: dict = {"label": label, "n": int(len(d)), "events": int(d.y.sum()),
                 "n_pooled_estimation_sample": int(len(dpool)),
                 "events_pooled_estimation_sample": int(dpool.y.sum()),
                 "pooled_estimation_sample_note": pool_note,
                 "n_vignettes": int(d.vignette.nunique())}

    # (1) PRIMARY (pre-specified): mixed-effects logistic regression, vignette random intercept,
    #     fitted by maximum likelihood with Gauss-Hermite quadrature (scripts/analysis/glmm.py
    #     explains why statsmodels' variational fit is unusable here).
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import glmm

        adv_levels = ["google", "meta", "openai", "xai"]          # anthropic = reference
        cols = ["intercept", "barrier"] + [f"advisor[{a}]" for a in adv_levels]
        Xm = np.column_stack([np.ones(len(dpool)), dpool.barrier.to_numpy(float)]
                             + [(dpool.advisor == a).to_numpy(float) for a in adv_levels])
        yv = dpool.y.to_numpy(float)
        gv = dpool.vignette.to_numpy()
        # A zero-event cell (e.g. the context arm's cooperative control, 0/56) sends the unpenalized
        # contrast to infinity; fall back to the same disclosed weakly-informative ridge the
        # per-family fits use, and say so in the output.
        pen = PEN_SD if pooled_zero_cell else None
        fit, _par = glmm.fit_random_intercept(Xm, yv, gv, names=cols, penalty_sd=pen)
        lrt = glmm.lrt_drop(Xm, yv, gv, drop_idx=1, penalty_sd=pen)
        b = fit["coef"]["barrier"]
        out["mixed_glmm"] = {
            "spec": "y ~ barrier + advisor + (1 | vignette); ML via Gauss-Hermite quadrature; " + pool_note,
            "PRESPECIFIED_PRIMARY": True,
            "zero_event_cell": bool(pooled_zero_cell),
            "penalty_sd": pen,
            "barrier_logodds": b["logodds"], "se": b["se"],
            "odds_ratio": b["odds_ratio"], "or_ci95": b["or_ci95"],
            "z": b["z"], "p_wald": b["p_wald"],
            "likelihood_ratio_test": lrt,
            "sigma_vignette": fit["sigma_vignette"],
            "loglik": fit["loglik"], "converged": fit["converged"],
            "n": fit["n"], "n_clusters": fit["n_clusters"],
            "advisor_coefficients": {k: v for k, v in fit["coef"].items() if k.startswith("advisor")},
        }
        try:
            rs = glmm.fit_random_slope(Xm, yv, dpool.barrier.to_numpy(float), gv, names=cols,
                                       penalty_sd=pen)  # same ridge as the intercept fit -> the LRT below is like-for-like
            out["mixed_glmm_random_slope"] = {
                "spec": "y ~ barrier + advisor + (1 + barrier | vignette); ML quadrature",
                "odds_ratio": rs["coef"]["barrier"]["odds_ratio"],
                "or_ci95": rs["coef"]["barrier"]["or_ci95"],
                "p_wald": rs["coef"]["barrier"]["p_wald"],
                "hessian_singular": rs.get("hessian_singular", False),
                **({"note": rs["note"]} if rs.get("note") else {}),
                "sigma_intercept": rs["sigma_intercept"], "sigma_slope": rs["sigma_slope"],
                "corr_intercept_slope": rs["corr"], "loglik": rs["loglik"],
                "lrt_vs_intercept_only": {
                    "chi2": 2 * (rs["loglik"] - fit["loglik"]), "df": 2,
                    "p": float(sps.chi2.sf(max(0.0, 2 * (rs["loglik"] - fit["loglik"])), 2))},
            }
        except Exception as e:  # noqa: BLE001
            out["mixed_glmm_random_slope"] = {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:  # noqa: BLE001
        out["mixed_glmm"] = {"error": f"{type(e).__name__}: {e}"}

    # (2) population-averaged GEE, exchangeable within vignette (robust SEs)
    try:
        g = smf.gee("y ~ barrier + C(advisor_c)", groups="vig", data=dpool,
                    family=sm.families.Binomial(),
                    cov_struct=sm.cov_struct.Exchangeable()).fit()
        b, se = float(g.params["barrier"]), float(g.bse["barrier"])
        out["gee"] = {
            "spec": "y ~ barrier + advisor, GEE exchangeable, clustered on vignette; " + pool_note,
            "zero_event_cell": bool(pooled_zero_cell),
            "barrier_logodds": b, "se": se, "odds_ratio": math.exp(b),
            "or_ci95": [math.exp(b - Z * se), math.exp(b + Z * se)],
            "z": b / se, "p": float(g.pvalues["barrier"]),
            "alpha_exchangeable": float(g.cov_struct.dep_params),
        }
    except Exception as e:  # noqa: BLE001
        out["gee"] = {"error": f"{type(e).__name__}: {e}"}

    # (3) cluster-robust logistic (vignette clusters) — sparse-data robustness
    try:
        lg = smf.logit("y ~ barrier + C(advisor_c)", data=dpool).fit(
            disp=False, cov_type="cluster", cov_kwds={"groups": dpool["vig"]})
        b, se = float(lg.params["barrier"]), float(lg.bse["barrier"])
        out["logit_cluster"] = {
            "spec": "y ~ barrier + advisor, logistic, vignette cluster-robust SEs; " + pool_note,
            "zero_event_cell": bool(pooled_zero_cell),
            "barrier_logodds": b, "se": se, "odds_ratio": math.exp(b),
            "or_ci95": [math.exp(b - Z * se), math.exp(b + Z * se)],
            "z": b / se, "p": float(lg.pvalues["barrier"]),
            "pseudo_r2": float(lg.prsquared),
        }
    except Exception as e:  # noqa: BLE001
        out["logit_cluster"] = {"error": f"{type(e).__name__}: {e}"}

    # (4) per-family model coefficients (single model, control = reference)
    try:
        d["fam_c"] = pd.Categorical(d.family, categories=FAMILIES)
        g2 = smf.gee("y ~ C(fam_c) + C(advisor_c)", groups="vig", data=d,
                     family=sm.families.Binomial(),
                     cov_struct=sm.cov_struct.Exchangeable()).fit()
        per = {}
        for fam in BARRIERS:
            key = f"C(fam_c)[T.{fam}]"
            if key in g2.params:
                b, se = float(g2.params[key]), float(g2.bse[key])
                per[fam] = {"logodds": b, "se": se, "odds_ratio": math.exp(b),
                            "or_ci95": [math.exp(b - Z * se), math.exp(b + Z * se)],
                            "z": b / se, "p": float(g2.pvalues[key])}
        out["gee_per_family"] = {
            "spec": "y ~ family + advisor, GEE exchangeable on vignette (control reference); "
                    "estimation sample = ALL conditions — the non-structural comparator enters as "
                    "its own dummy, so it never sits in the reference group",
            "families": per,
            "holm_p": holm({k: v["p"] for k, v in per.items()}) if per else {},
        }
    except Exception as e:  # noqa: BLE001
        out["gee_per_family"] = {"error": f"{type(e).__name__}: {e}"}

    # (4b) per-family under the prespecified mixed model: five identical tests, one Holm family
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import glmm as _glmm
        adv_levels = ["google", "meta", "openai", "xai"]
        per_glmm, praw = {}, {}
        for fam in BARRIERS:
            sub = d[d.family.isin([fam, "control"])]
            cols = ["intercept", "family"] + [f"advisor[{a}]" for a in adv_levels]
            Xf = np.column_stack([np.ones(len(sub)), (sub.family == fam).to_numpy(float)]
                                 + [(sub.advisor == a).to_numpy(float) for a in adv_levels])
            yf, gf = sub.y.to_numpy(float), sub.vignette.to_numpy()
            f_, _ = _glmm.fit_random_intercept(Xf, yf, gf, names=cols, penalty_sd=PEN_SD)
            l_ = _glmm.lrt_drop(Xf, yf, gf, drop_idx=1, penalty_sd=PEN_SD)
            c_ = f_["coef"]["family"]
            per_glmm[fam] = {"odds_ratio": c_["odds_ratio"], "or_ci95": c_["or_ci95"],
                             "se": c_["se"], "p_wald": c_["p_wald"],
                             "lrt_chi2": l_["chi2"], "lrt_p": l_["p"],
                             "sigma_vignette": f_["sigma_vignette"]}
            praw[fam] = l_["p"]
        hp = holm(praw)
        for fam in BARRIERS:
            per_glmm[fam]["holm_p_lrt"] = hp[fam]
            per_glmm[fam]["significant_holm_05"] = hp[fam] < 0.05
        # robustness: same model without advisor terms and without any penalty
        per_plain = {}
        for fam in BARRIERS:
            sub = d[d.family.isin([fam, "control"])]
            Xf = np.column_stack([np.ones(len(sub)), (sub.family == fam).to_numpy(float)])
            yf, gf = sub.y.to_numpy(float), sub.vignette.to_numpy()
            f2, _ = _glmm.fit_random_intercept(Xf, yf, gf, names=["intercept", "family"])
            l2 = _glmm.lrt_drop(Xf, yf, gf, drop_idx=1)
            per_plain[fam] = {"odds_ratio": f2["coef"]["family"]["odds_ratio"],
                              "or_ci95": f2["coef"]["family"]["or_ci95"],
                              "lrt_chi2": l2["chi2"], "lrt_p": l2["p"]}
        hp2 = holm({f: per_plain[f]["lrt_p"] for f in BARRIERS})
        for fam in BARRIERS:
            per_plain[fam]["holm_p_lrt"] = hp2[fam]
        out["glmm_per_family"] = {
            "spec": "per family: y ~ family + advisor + (1 | vignette) vs control; LRT on the family term",
            "penalty_note": f"weakly-informative N(0,{PEN_SD}^2) ridge on non-intercept fixed effects "
                            "(several advisor x control cells have zero degradation events, which "
                            "sends unpenalized advisor coefficients to infinity); identical penalty "
                            "in both LRT fits",
            "holm_family_size": len(BARRIERS), "families": per_glmm,
            "robustness_no_advisor_unpenalized": {"families": per_plain}}
    except Exception as e:  # noqa: BLE001
        out["glmm_per_family"] = {"error": f"{type(e).__name__}: {e}"}

    # (5) advisor fixed effects: a separate GEE (y ~ barrier + advisor, clustered by vignette),
    #     control-referenced
    try:
        g3 = smf.gee("y ~ barrier + C(advisor_c)", groups="vig", data=dpool,
                     family=sm.families.Binomial(),
                     cov_struct=sm.cov_struct.Exchangeable()).fit()
        adv = {}
        for a in ["google", "meta", "openai", "xai"]:
            key = f"C(advisor_c)[T.{a}]"
            if key in g3.params:
                b, se = float(g3.params[key]), float(g3.bse[key])
                adv[a] = {"odds_ratio": math.exp(b), "or_ci95": [math.exp(b - Z * se), math.exp(b + Z * se)],
                          "p": float(g3.pvalues[key])}
        out["advisor_effects_vs_anthropic"] = adv
    except Exception as e:  # noqa: BLE001
        out["advisor_effects_vs_anthropic"] = {"error": f"{type(e).__name__}: {e}"}

    return out


def cluster_bootstrap_rd(d: pd.DataFrame, n_boot: int = N_BOOT) -> dict:
    """Bootstrap the pooled barrier-vs-control risk difference, resampling VIGNETTES."""
    vigs = d.vignette.unique()
    by_v = {v: d[d.vignette == v] for v in vigs}
    obs_b = d[d.family.isin(STRUCTURAL)]
    obs_c = d[d.family == "control"]
    point = obs_b.degraded.mean() - obs_c.degraded.mean()
    draws = []
    for _ in range(n_boot):
        pick = RNG.choice(vigs, size=len(vigs), replace=True)
        s = pd.concat([by_v[v] for v in pick], ignore_index=True)
        b, c = s[s.family.isin(STRUCTURAL)], s[s.family == "control"]
        if len(b) and len(c):
            draws.append(b.degraded.mean() - c.degraded.mean())
    arr = np.array(draws)
    return {"point": float(point), "n_boot": int(len(arr)),
            "ci95": [float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))],
            "se": float(arr.std(ddof=1)),
            "p_two_sided_gt0": float(2 * min((arr <= 0).mean(), (arr >= 0).mean()))}


def resistance(d: pd.DataFrame, T: int = 8) -> dict:
    """P(ToD > t) among init-correct conversations, t = 1..T (t=T is the survived-to-end rate)."""
    out = {}
    for t in range(1, T + 1):
        surv = (d.tod > t).mean() if len(d) else None
        k = int((d.tod > t).sum())
        lo, hi = wilson(k, len(d))
        out[str(t)] = {"survival": float(surv) if surv is not None else None,
                       "k": k, "n": int(len(d)), "ci95": [lo, hi]}
    return out


# --------------------------------------------------------------------------- main
def analyze_arm(df: pd.DataFrame, arm: str, run_models: bool = True) -> dict:
    res: dict = {"arm": arm}
    res["accounting"] = {
        "conversations": int(len(df)),
        "judged": int((df.status == "judged").sum()),
        "analyzable": int(df.analyzable.sum()),
        "excluded": int((~df.analyzable).sum()),
        "quarantined": int(df.quarantined.sum()),
        "quarantined_ids": sorted(df[df.quarantined].cid.tolist()),
        "complete_transcripts": int(df.complete.sum()),
        "advisor_responses_per_conversation": int(df.n_adv.mode().iloc[0]),
        "by_family": {f: int((df.family == f).sum()) for f in FAMILIES},
        "by_advisor": {a: int((df.advisor == a).sum()) for a in sorted(df.advisor.unique())},
        "by_vignette": {v: int((df.vignette == v).sum()) for v in sorted(df.vignette.unique())},
        "replicates": sorted(df.replicate.unique().tolist()),
    }

    ana = df[df.analyzable & ~df.quarantined].copy()

    # --- secondary outcome: init_correct
    init = {"overall": rate_block(int(ana.init.sum()), len(ana)),
            "by_family": {}, "by_advisor": {}, "by_vignette": {}, "contrasts_vs_control": {}}
    for f in FAMILIES:
        s = ana[ana.family == f]
        init["by_family"][f] = rate_block(int(s.init.sum()), len(s))
    for a in sorted(ana.advisor.unique()):
        s = ana[ana.advisor == a]
        init["by_advisor"][a] = rate_block(int(s.init.sum()), len(s))
    for v in sorted(ana.vignette.unique()):
        s = ana[ana.vignette == v]
        init["by_vignette"][v] = rate_block(int(s.init.sum()), len(s))
    tmp = ana.copy()
    tmp["init_b"] = tmp.init.astype(int)
    for f in BARRIERS:
        init["contrasts_vs_control"][f] = contrast(tmp.rename(columns={"init_b": "outcome"}),
                                                   f, outcome="outcome")
    kb = int(tmp[tmp.family.isin(STRUCTURAL)].init.sum()); nb = int((tmp.family.isin(STRUCTURAL)).sum())
    kc = int(tmp[tmp.family == "control"].init.sum()); nc = int((tmp.family == "control").sum())
    rd, lo, hi = newcombe_rd(kb, nb, kc, nc)
    init["pooled_barrier_vs_control"] = {
        "barrier": rate_block(kb, nb), "control": rate_block(kc, nc),
        "risk_difference": rd, "rd_ci95": [lo, hi],
        "fisher_p": fisher(kb, nb - kb, kc, nc - kc)}
    res["init_correct"] = init

    # --- primary outcome: degradation among init-correct
    dd = ana[ana.init == 1].copy()
    res["degradation"] = {
        "denominator_note": "init_correct == 1, analyzable, quarantine applied",
        "overall": rate_block(int(dd.degraded.sum()), len(dd)),
        "by_family": {f: rate_block(int(dd[dd.family == f].degraded.sum()),
                                    int((dd.family == f).sum())) for f in FAMILIES},
        "by_advisor": {a: rate_block(int(dd[dd.advisor == a].degraded.sum()),
                                     int((dd.advisor == a).sum()))
                       for a in sorted(dd.advisor.unique())},
        "by_vignette": {v: rate_block(int(dd[dd.vignette == v].degraded.sum()),
                                      int((dd.vignette == v).sum()))
                        for v in sorted(dd.vignette.unique())},
        "by_replicate": {str(r): rate_block(int(dd[dd.replicate == r].degraded.sum()),
                                            int((dd.replicate == r).sum()))
                         for r in sorted(dd.replicate.unique())},
    }

    kb = int(dd[dd.family.isin(STRUCTURAL)].degraded.sum()); nb = int((dd.family.isin(STRUCTURAL)).sum())
    kc = int(dd[dd.family == "control"].degraded.sum()); nc = int((dd.family == "control").sum())
    rd, lo, hi = newcombe_rd(kb, nb, kc, nc)
    orv, orlo, orhi, corrected = or_ci(kb, nb - kb, kc, nc - kc)
    res["primary_pooled"] = {
        "barrier": rate_block(kb, nb), "control": rate_block(kc, nc),
        "risk_difference": rd, "rd_ci95": [lo, hi],
        "risk_ratio": (kb / nb) / (kc / nc) if kc else None,
        "odds_ratio": orv, "or_ci95": [orlo, orhi], "or_zero_cell_corrected": corrected,
        "fisher_p": fisher(kb, nb - kb, kc, nc - kc),
        "chi2": (lambda r: {"chi2": float(r[0]), "p": float(r[1]), "df": int(r[2])})(
            sps.chi2_contingency([[kb, nb - kb], [kc, nc - kc]], correction=False)),
    }

    # --- pooled contrasts by family CLASS. Reporting all of these, not just the first;
    #     the third is what separates the obstacle from the pushback, and is the reason the
    #     non-structural comparator exists.
    def _pool(names):
        sub = dd[dd.family.isin(names)]
        return int(sub.degraded.sum()), int(len(sub))

    pooled = {}
    for label, a_names, b_names in (
        ("structural_vs_cooperative", STRUCTURAL, [CONTROL]),        # the Run-1 estimate, kept for continuity
        ("nonstructural_vs_cooperative", NONSTRUCTURAL, [CONTROL]),  # effect of persistent pushback alone
        ("structural_vs_nonstructural", STRUCTURAL, NONSTRUCTURAL),  # effect of the obstacle, pushback held constant
        # POST-HOC (not among the pre-specified contrasts; flagged as such in the output):
        # all six obstacle conditions pooled. An average of two prespecified arms, reported for
        # the write-up's "any obstacle" framing — labelled post-hoc wherever it appears.
        ("any_obstacle_vs_cooperative", STRUCTURAL + NONSTRUCTURAL, [CONTROL]),
    ):
        ka, na = _pool(a_names)
        kb, nb = _pool(b_names)
        if not (na and nb):
            continue
        rd_, lo_, hi_ = newcombe_rd(ka, na, kb, nb)
        orv_, orlo_, orhi_, corr_ = or_ci(ka, na - ka, kb, nb - kb)
        pooled[label] = {
            "post_hoc": label == "any_obstacle_vs_cooperative",
            "treated": rate_block(ka, na), "reference": rate_block(kb, nb),
            "risk_difference": rd_, "rd_ci95": [lo_, hi_],
            "risk_ratio": (ka / na) / (kb / nb) if kb else None,
            "odds_ratio": orv_, "or_ci95": [orlo_, orhi_], "or_zero_cell_corrected": corr_,
            "fisher_p": fisher(ka, na - ka, kb, nb - kb),
        }
    res["pooled_by_class"] = pooled

    # --- per-family, identical test, one Holm family of five
    per = {f: contrast(dd, f) for f in BARRIERS if int((dd.family == f).sum()) > 0}
    hp = holm({f: per[f]["fisher_p"] for f in per})
    for f in per:
        per[f]["holm_p"] = hp[f]
        per[f]["significant_holm_05"] = hp[f] < 0.05
    res["per_family"] = per

    # --- omnibus across every condition present
    present = [f for f in FAMILIES if int((dd.family == f).sum()) > 0]
    present_barriers = [f for f in BARRIERS if int((dd.family == f).sum()) > 0]
    tbl = [[int(dd[dd.family == f].degraded.sum()),
            int((dd.family == f).sum()) - int(dd[dd.family == f].degraded.sum())] for f in present]
    c2 = sps.chi2_contingency(tbl, correction=False)
    res["omnibus_family"] = {"chi2": float(c2[0]), "p": float(c2[1]), "df": int(c2[2]),
                             "min_expected": float(np.min(c2[3]))}
    tblb = [[int(dd[dd.family == f].degraded.sum()),
             int((dd.family == f).sum()) - int(dd[dd.family == f].degraded.sum())] for f in present_barriers]
    c2b = sps.chi2_contingency(tblb, correction=False)
    res["omnibus_barriers_only"] = {"chi2": float(c2b[0]), "p": float(c2b[1]), "df": int(c2b[2])}

    # --- advisor heterogeneity
    tbla = [[int(dd[dd.advisor == a].degraded.sum()),
             int((dd.advisor == a).sum()) - int(dd[dd.advisor == a].degraded.sum())]
            for a in sorted(dd.advisor.unique())]
    c2a = sps.chi2_contingency(tbla, correction=False)
    res["omnibus_advisor"] = {"chi2": float(c2a[0]), "p": float(c2a[1]), "df": int(c2a[2])}
    ddb = dd[dd.family.isin(STRUCTURAL)]
    res["advisor_barrier_only"] = {
        a: rate_block(int(ddb[ddb.advisor == a].degraded.sum()), int((ddb.advisor == a).sum()))
        for a in sorted(ddb.advisor.unique())}
    res["advisor_control_only"] = {
        a: rate_block(int(dd[(dd.advisor == a) & (dd.family == "control")].degraded.sum()),
                      int(((dd.advisor == a) & (dd.family == "control")).sum()))
        for a in sorted(dd.advisor.unique())}

    # --- vignette heterogeneity
    tblv = [[int(dd[dd.vignette == v].degraded.sum()),
             int((dd.vignette == v).sum()) - int(dd[dd.vignette == v].degraded.sum())]
            for v in sorted(dd.vignette.unique())]
    c2v = sps.chi2_contingency(tblv, correction=False)
    res["omnibus_vignette"] = {"chi2": float(c2v[0]), "p": float(c2v[1]), "df": int(c2v[2])}

    # --- family x advisor and family x vignette cell matrices
    res["family_by_advisor"] = {
        f: {a: rate_block(int(dd[(dd.family == f) & (dd.advisor == a)].degraded.sum()),
                          int(((dd.family == f) & (dd.advisor == a)).sum()))
            for a in sorted(dd.advisor.unique())} for f in FAMILIES}
    res["family_by_vignette"] = {
        f: {v: rate_block(int(dd[(dd.family == f) & (dd.vignette == v)].degraded.sum()),
                          int(((dd.family == f) & (dd.vignette == v)).sum()))
            for v in sorted(dd.vignette.unique())} for f in FAMILIES}

    # --- ToD distribution + resistance curves
    res["tod_distribution"] = {
        "overall": {str(k): int(v) for k, v in sorted(Counter(dd[dd.degraded].tod).items())},
        "by_family": {f: {str(k): int(v) for k, v in
                          sorted(Counter(dd[(dd.family == f) & dd.degraded].tod).items())}
                      for f in FAMILIES},
        "median_tod_degraded": float(dd[dd.degraded].tod.median()) if dd.degraded.any() else None,
        "median_tod_degraded_by_family": {
            f: (float(dd[(dd.family == f) & dd.degraded].tod.median())
                if (dd[(dd.family == f) & dd.degraded]).shape[0] else None) for f in FAMILIES},
        "iqr_tod_degraded": [float(dd[dd.degraded].tod.quantile(.25)),
                             float(dd[dd.degraded].tod.quantile(.75))] if dd.degraded.any() else None,
    }
    res["resistance"] = {"by_family": {f: resistance(dd[dd.family == f]) for f in FAMILIES},
                         "by_advisor": {a: resistance(dd[dd.advisor == a])
                                        for a in sorted(dd.advisor.unique())},
                         "pooled_barrier": resistance(dd[dd.family.isin(STRUCTURAL)]),
                         "control": resistance(dd[dd.family == "control"])}
    # discrete-time hazard: P(degrade at t | survived past t-1)
    haz = {}
    for f in FAMILIES:
        s = dd[dd.family == f]
        h = {}
        for t in range(2, 9):
            at_risk = int((s.tod >= t).sum())
            ev = int((s.tod == t).sum())
            h[str(t)] = {"at_risk": at_risk, "events": ev,
                         "hazard": (ev / at_risk) if at_risk else None}
        haz[f] = h
    res["hazard_by_family"] = haz

    # --- models + bootstrap
    if run_models:
        res["models"] = fit_models(dd, f"{arm}: degradation | init_correct=1")
        res["bootstrap_cluster_vignette"] = cluster_bootstrap_rd(dd)

    # --- sensitivity analyses
    sens = {}
    dd_all = ana[ana.init == 1]                                   # quarantine already applied above
    raw = df[df.analyzable & (df.init == 1)]                      # quarantine NOT applied
    kb0 = int(raw[raw.family.isin(STRUCTURAL)].degraded.sum()); nb0 = int((raw.family.isin(STRUCTURAL)).sum())
    kc0 = int(raw[raw.family == "control"].degraded.sum()); nc0 = int((raw.family == "control").sum())
    rd0, lo0, hi0 = newcombe_rd(kb0, nb0, kc0, nc0)
    sens["without_quarantine"] = {
        "barrier": rate_block(kb0, nb0), "control": rate_block(kc0, nc0),
        "risk_difference": rd0, "rd_ci95": [lo0, hi0],
        "fisher_p": fisher(kb0, nb0 - kb0, kc0, nc0 - kc0),
        "per_family": {f: contrast(raw, f) for f in BARRIERS}}
    # Two DIFFERENT guard cuts, named for what they actually drop: a single key whose name
    # says "flagged" while it drops only the accepted-uncured subset would contradict the guard
    # block's own flag counts, so each cut names its exact population.
    ng = dd_all[~dd_all.guard_accepted_flag]
    kb1 = int(ng[ng.family.isin(STRUCTURAL)].degraded.sum()); nb1 = int((ng.family.isin(STRUCTURAL)).sum())
    kc1 = int(ng[ng.family == "control"].degraded.sum()); nc1 = int((ng.family == "control").sum())
    rd1, lo1, hi1 = newcombe_rd(kb1, nb1, kc1, nc1)
    sens["dropping_accepted_uncured_conversations"] = {
        "dropped": int(dd_all.guard_accepted_flag.sum()),
        "barrier": rate_block(kb1, nb1), "control": rate_block(kc1, nc1),
        "risk_difference": rd1, "rd_ci95": [lo1, hi1],
        "fisher_p": fisher(kb1, nb1 - kb1, kc1, nc1 - kc1),
        "per_family": {f: contrast(ng, f) for f in BARRIERS}}
    nf_ = dd_all[~dd_all.guard_flagged]
    kb2 = int(nf_[nf_.family.isin(STRUCTURAL)].degraded.sum()); nb2 = int((nf_.family.isin(STRUCTURAL)).sum())
    kc2 = int(nf_[nf_.family == "control"].degraded.sum()); nc2 = int((nf_.family == "control").sum())
    rd2, lo2, hi2 = newcombe_rd(kb2, nb2, kc2, nc2)
    sens["dropping_any_guard_flagged_conversations"] = {
        "dropped": int(dd_all.guard_flagged.sum()),
        "barrier": rate_block(kb2, nb2), "control": rate_block(kc2, nc2),
        "risk_difference": rd2, "rd_ci95": [lo2, hi2],
        "fisher_p": fisher(kb2, nb2 - kb2, kc2, nc2 - kc2)}
    fl = dd_all[dd_all.guard_accepted_flag]
    sens["degradation_within_accepted_uncured_vs_rest"] = {
        "accepted_uncured": rate_block(int(fl.degraded.sum()), len(fl)),
        "rest": rate_block(int(ng.degraded.sum()), len(ng)),
        "fisher_p": fisher(int(fl.degraded.sum()), len(fl) - int(fl.degraded.sum()),
                           int(ng.degraded.sum()), len(ng) - int(ng.degraded.sum()))}
    fl2 = dd_all[dd_all.guard_flagged]
    sens["degradation_within_any_flagged_vs_unflagged"] = {
        "flagged": rate_block(int(fl2.degraded.sum()), len(fl2)),
        "unflagged": rate_block(int(nf_.degraded.sum()), len(nf_)),
        "fisher_p": fisher(int(fl2.degraded.sum()), len(fl2) - int(fl2.degraded.sum()),
                           int(nf_.degraded.sum()), len(nf_) - int(nf_.degraded.sum()))}
    res["sensitivity"] = sens

    # --- barrier effect WITHIN each advisor (does the effect hold model by model?)
    per_adv = {}
    for adv in sorted(dd.advisor.unique()):
        sa = dd[dd.advisor == adv]
        kb_ = int(sa[sa.family.isin(STRUCTURAL)].degraded.sum()); nb_ = int((sa.family.isin(STRUCTURAL)).sum())
        kc_ = int(sa[sa.family == "control"].degraded.sum()); nc_ = int((sa.family == "control").sum())
        rd_, lo_, hi_ = newcombe_rd(kb_, nb_, kc_, nc_)
        orv_, orlo_, orhi_, corr_ = or_ci(kb_, nb_ - kb_, kc_, nc_ - kc_)
        per_adv[adv] = {
            "label": ADVISOR_LABEL.get(adv, adv),
            "barrier": rate_block(kb_, nb_), "control": rate_block(kc_, nc_),
            "risk_difference": rd_, "rd_ci95": [lo_, hi_],
            "odds_ratio": orv_, "or_ci95": [orlo_, orhi_], "or_zero_cell_corrected": corr_,
            "fisher_p": fisher(kb_, nb_ - kb_, kc_, nc_ - kc_),
            "init_correct": rate_block(int(ana[ana.advisor == adv].init.sum()),
                                       int((ana.advisor == adv).sum())),
        }
    hp_adv = holm({k: v["fisher_p"] for k, v in per_adv.items()})
    for k in per_adv:
        per_adv[k]["holm_p"] = hp_adv[k]
    res["barrier_effect_by_advisor"] = per_adv

    # --- the same within-advisor cuts for the non-structural comparator (exploratory).
    #     One condition against five leaves per-model contrasts underpowered, so these
    #     carry intervals and no significance claims; the fear-vs-structural Holm family is
    #     post-hoc besides. Recorded here so the write-up's tables read from stats.json
    #     rather than from a hand computation.
    fear_adv = {}
    for adv in sorted(dd.advisor.unique()):
        sa = dd[dd.advisor == adv]
        kf = int(sa[sa.family.isin(NONSTRUCTURAL)].degraded.sum())
        nf2 = int((sa.family.isin(NONSTRUCTURAL)).sum())
        kc_ = int(sa[sa.family == CONTROL].degraded.sum()); nc_ = int((sa.family == CONTROL).sum())
        kb_ = int(sa[sa.family.isin(STRUCTURAL)].degraded.sum()); nb_ = int((sa.family.isin(STRUCTURAL)).sum())
        rdc, lc, hc = newcombe_rd(kf, nf2, kc_, nc_)
        rds, ls, hs = newcombe_rd(kf, nf2, kb_, nb_)
        fear_adv[adv] = {
            "label": ADVISOR_LABEL.get(adv, adv),
            "fear": rate_block(kf, nf2), "control": rate_block(kc_, nc_),
            "structural": rate_block(kb_, nb_),
            "rd_fear_minus_control": rdc, "rd_fear_minus_control_ci95": [lc, hc],
            "rd_fear_minus_structural": rds, "rd_fear_minus_structural_ci95": [ls, hs],
            "fisher_p_fear_vs_structural": fisher(kf, nf2 - kf, kb_, nb_ - kb_),
        }
    hp_fear = holm({k: v["fisher_p_fear_vs_structural"] for k, v in fear_adv.items()})
    for k in fear_adv:
        fear_adv[k]["holm_p_fear_vs_structural"] = hp_fear[k]
    res["fear_effect_by_advisor"] = fear_adv

    # --- sensitivity: drop the weakest advisor (lowest initial-correctness) entirely
    weakest = min(res["init_correct"]["by_advisor"], key=lambda a: res["init_correct"]["by_advisor"][a]["rate"])
    dw = dd[dd.advisor != weakest]
    kbw = int(dw[dw.family.isin(STRUCTURAL)].degraded.sum()); nbw = int((dw.family.isin(STRUCTURAL)).sum())
    kcw = int(dw[dw.family == "control"].degraded.sum()); ncw = int((dw.family == "control").sum())
    rdw, low, hiw = newcombe_rd(kbw, nbw, kcw, ncw)
    res["sensitivity_drop_weakest_advisor"] = {
        "dropped_advisor": weakest, "label": ADVISOR_LABEL.get(weakest, weakest),
        "barrier": rate_block(kbw, nbw), "control": rate_block(kcw, ncw),
        "risk_difference": rdw, "rd_ci95": [low, hiw],
        "fisher_p": fisher(kbw, nbw - kbw, kcw, ncw - kcw),
        "per_family": {f: contrast(dw, f) for f in BARRIERS}}

    # --- instrument: judge panel behaviour
    pan = {"aggregation_rules": dict(Counter(str(x) for x in df.aggregation)),
           "seat_status": dict(Counter(s for row in df.panel_status for s in row))}
    unan_init, unan_tod, split_tod, single_tod, spreads = 0, 0, 0, 0, []
    seat_init, seat_deg, seat_n = defaultdict(int), defaultdict(int), defaultdict(int)
    for _, r in df.iterrows():
        inits = [x for x in r.panel_init if x in (0, 1)]
        tods = [x for x in r.panel_tod if isinstance(x, int)]
        if inits and len(set(inits)) == 1:
            unan_init += 1
        # Unanimity is only meaningful when at least two seats actually cast an integer ToD vote
        # (a seat that scored init_correct=0 casts 'NA'); counting a single cast vote as
        # "unanimous" would quietly inflate the agreement rate with vacuous cases.
        if len(tods) >= 2:
            if len(set(tods)) == 1:
                unan_tod += 1
            else:
                split_tod += 1
                spreads.append(max(tods) - min(tods))
        elif len(tods) == 1:
            single_tod += 1
        for prov, i, t in zip(r.panel_providers, r.panel_init, r.panel_tod):
            if prov is None:
                continue
            seat_n[prov] += 1
            if i == 1:
                seat_init[prov] += 1
                if isinstance(t, int) and t <= r.n_turns:
                    seat_deg[prov] += 1
    pan["unanimous_init"] = rate_block(unan_init, len(df))
    pan["unanimous_tod_among_all_int"] = {"unanimous": unan_tod, "split": split_tod,
                                          "single_vote_excluded": single_tod,
                                          "rate": unan_tod / (unan_tod + split_tod) if (unan_tod + split_tod) else None}
    pan["tod_spread_when_split"] = {"mean": float(np.mean(spreads)) if spreads else None,
                                    "median": float(np.median(spreads)) if spreads else None,
                                    "max": int(max(spreads)) if spreads else None}
    pan["per_seat_marginals"] = {
        p: {"seats": seat_n[p], "init_correct_rate": seat_init[p] / seat_n[p] if seat_n[p] else None,
            "degradation_rate_among_own_init1": seat_deg[p] / seat_init[p] if seat_init[p] else None}
        for p in sorted(seat_n)}
    res["judge_panel"] = pan

    # --- instrument: guard
    res["guard"] = {
        "conversations_with_any_flag": rate_block(int(df.guard_flagged.sum()), len(df)),
        "conversations_fully_cured": int((df.guard_flagged & ~df.guard_accepted_flag).sum()),
        "conversations_with_accepted_flag": int(df.guard_accepted_flag.sum()),
        "total_flag_events": int(df.guard_n_flagged.sum()),
        # computed, not asserted: a conversation the guard aborted would be metadata.complete=False
        "aborted_conversations": int((~df.complete).sum()),
        "by_family_accepted_flag": {f: rate_block(int(df[df.family == f].guard_accepted_flag.sum()),
                                                  int((df.family == f).sum())) for f in FAMILIES},
    }
    return res


def _json_safe(o):
    """NaN/inf -> None throughout. ``json.dumps`` would otherwise write the literal tokens NaN
    and Infinity, which are not JSON and which every strict reader (and the figure pipeline's
    formatters) rejects. A non-estimable quantity is null, with the fitter's own flag beside it."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


def _fmt(x, spec: str) -> str:
    """Format a number, or an em dash for a non-estimable (None/NaN) value."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return format(x, spec)


def main() -> None:
    ap = argparse.ArgumentParser(description="TUP confirmatory analysis.")
    ap.add_argument("run_id", help="run id in the store, e.g. 2026-08-06__full_experiment")
    ap.add_argument("--quarantine", default=None,
                    help='adjudicated quarantine JSON: {"main": [ids], "ctx": [ids]} ("context" is accepted as an alias). Defaults '
                         "to the run's own exclusions/quarantine.json; pass --unquarantined for a "
                         "deliberately unquarantined pass.")
    ap.add_argument("--unquarantined", action="store_true",
                    help="run with NO quarantine at all (exploratory sensitivity pass only)")
    args = ap.parse_args()

    store = Store.from_env()
    try:
        run = store.require_run(args.run_id)
    except RunNotFoundError as e:
        raise SystemExit(f"error: {e}")
    OUT = store.stats_dir_for(run.run_id)
    OUT.mkdir(parents=True, exist_ok=True)
    # The sensitivity pass gets its OWN filenames: were it to write stats.json, running the
    # exploratory unquarantined pass would silently overwrite the quarantined statistics of
    # record with a file that answers a different question.
    global UNQUARANTINED_MODE
    args.main = str(run.arm("main").records_path)
    args.ctx = str(run.arm("context").records_path)
    # An ABSENT quarantine file is not the same as an empty one: the post-run audit quarantined
    # zero conversations, and that is a finding. Defaulting to the run's own file means the
    # analysis can never silently inherit a DIFFERENT run's exclusion set.
    if not args.quarantine and not args.unquarantined and run.quarantine_path.exists():
        args.quarantine = str(run.quarantine_path)

    # the OUTCOME decides the filename and the stamp, never the flag alone: a pass that found no
    # quarantine file is unquarantined whether or not --unquarantined was passed
    UNQUARANTINED_MODE = bool(args.unquarantined) or not args.quarantine
    STEM = "stats_unquarantined" if UNQUARANTINED_MODE else "stats"
    if args.quarantine:
        load_quarantine(args.quarantine)
        print(f"quarantine loaded: {len(QUARANTINE['main'])} main + {len(QUARANTINE['ctx'])} ctx")
    else:
        print("WARNING: no --quarantine file; running UNQUARANTINED (exploratory only)")

    main_df = load(Path(args.main), "main")
    ctx_df = load(Path(args.ctx), "ctx")

    out = {
        # Identify the RUN, not absolute machine paths: paths differ per checkout, leak a home
        # directory into a tracked artifact, and go stale the moment a run is renamed.
        "generated_from": {"run_id": run.run_id,
                           "quarantine_applied": not UNQUARANTINED_MODE,
                           "quarantine_source": ("the run's own exclusions/quarantine.json"
                                                 if args.quarantine == str(run.quarantine_path)
                                                 else "explicit --quarantine" if args.quarantine
                                                 else "none (unquarantined sensitivity pass)")},
        "design": {
            "vignettes": int(main_df.vignette.nunique()),
            "families": FAMILIES,
            "advisors": {a: ADVISOR_LABEL.get(a, a) for a in sorted(main_df.advisor.unique())},
            "advisor_models": sorted(main_df.advisor_model.dropna().unique().tolist()),
            "replicates_main": int(main_df.replicate.nunique()),
            "replicates_ctx": int(ctx_df.replicate.nunique()),
            "advisor_turns_per_conversation": int(main_df.n_adv.mode().iloc[0]),
            "total_conversations": int(len(main_df) + len(ctx_df)),
            "quarantine_convention_applied": not UNQUARANTINED_MODE,
            "quarantined_total": len(QUARANTINE["main"]) + len(QUARANTINE["ctx"]),
        },
        "main_arm": analyze_arm(main_df, "main", run_models=True),
        "context_arm": analyze_arm(ctx_df, "ctx", run_models=True),
    }

    # cross-arm descriptive comparison (NOT confirmatory - different estimand)
    ma = main_df[main_df.analyzable & ~main_df.quarantined]
    ca = ctx_df[ctx_df.analyzable & ~ctx_df.quarantined]
    cross = {"note": "descriptive only; the context arm has a different estimand (barrier known to the advisor from turn 1)"}
    for name, col, sub_m, sub_c in [
        ("init_correct", "init", ma, ca),
        ("degradation", "degraded", ma[ma.init == 1], ca[ca.init == 1]),
    ]:
        blk = {}
        for f in FAMILIES:
            m, c = sub_m[sub_m.family == f], sub_c[sub_c.family == f]
            km, nm = int(m[col].sum()), len(m)
            kc, nc = int(c[col].sum()), len(c)
            if not (nm and nc):
                continue          # family absent from one arm (possible on sliced/partial data)
            rd, lo, hi = newcombe_rd(kc, nc, km, nm)   # ctx minus main
            blk[f] = {"main": rate_block(km, nm), "ctx": rate_block(kc, nc),
                      "rd_ctx_minus_main": rd, "rd_ci95": [lo, hi],
                      "fisher_p": fisher(kc, nc - kc, km, nm - km)}
        cross[name] = blk
    # Pooled cross-arm contrasts by class — the write-up's context-arm table. Exploratory by
    # design (the arms differ in estimand), but computed here so no number lives outside stats.json.
    md = ma[ma.init == 1]
    cdg = ca[ca.init == 1]
    pooled_cross = {}
    for label, names in (
        ("degradation_any_obstacle", STRUCTURAL + NONSTRUCTURAL),
        ("degradation_structural", STRUCTURAL),
        ("degradation_nonstructural", NONSTRUCTURAL),
        ("degradation_cooperative", [CONTROL]),
    ):
        m_, c_ = md[md.family.isin(names)], cdg[cdg.family.isin(names)]
        km, nm = int(m_.degraded.sum()), len(m_)
        kc2, nc2 = int(c_.degraded.sum()), len(c_)
        if not (nm and nc2):
            continue
        rd, lo, hi = newcombe_rd(kc2, nc2, km, nm)
        pooled_cross[label] = {"main": rate_block(km, nm), "ctx": rate_block(kc2, nc2),
                               "rd_ctx_minus_main": rd, "rd_ci95": [lo, hi],
                               "fisher_p": fisher(kc2, nc2 - kc2, km, nm - km)}
    km, nm = int(ma.init.sum()), len(ma)
    kc2, nc2 = int(ca.init.sum()), len(ca)
    rd, lo, hi = newcombe_rd(kc2, nc2, km, nm)
    pooled_cross["init_correct_all_conditions"] = {
        "main": rate_block(km, nm), "ctx": rate_block(kc2, nc2),
        "rd_ctx_minus_main": rd, "rd_ci95": [lo, hi],
        "fisher_p": fisher(kc2, nc2 - kc2, km, nm - km)}
    cross["pooled_by_class"] = pooled_cross
    out["cross_arm_descriptive"] = cross

    # ---- cost + power context
    def manifest(run_path):
        # Two manifest filenames are accepted beside the records file: `manifest.json` (the store
        # layout) and `<records-name>.manifest.json`. A run with NEITHER fails loudly — silently
        # degrading to an empty cost block would ship a stats file that quietly reports no cost.
        d = Path(run_path).parent
        for f in (d / "manifest.json", d / (Path(run_path).stem + ".manifest.json")):
            if f.exists():
                return json.loads(f.read_text())
        raise FileNotFoundError(
            f"no arm manifest found beside {run_path} (tried manifest.json and "
            f"{Path(run_path).stem}.manifest.json)")
    mm, mc = manifest(args.main), manifest(args.ctx)

    def records_cost(path):
        """Sum spend from the records themselves — the records are authoritative for cost; an
        arm manifest's frozen cost block can lag them (the released manifests still claim
        missing judge-cost metadata the records since carry)."""
        turns = judge = guard = 0.0
        m_turns = m_judge = 0
        for line in Path(path).open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            for t in r.get("turns") or []:
                if t.get("runner_authored"):
                    continue
                c = (t.get("usage") or {}).get("cost")
                if c is None:
                    m_turns += 1
                else:
                    turns += c
            for mem in ((r.get("judgment") or {}).get("panel") or []):
                c = (mem.get("judge_usage") or mem.get("usage") or {}).get("cost")
                if c is None:
                    m_judge += 1
                else:
                    judge += c
            guard += float(((r.get("metadata") or {}).get("guard") or {}).get("extra_cost_usd") or 0.0)
        return {"turns_usd": round(turns, 6), "judge_usd": round(judge, 6),
                "guard_usd": round(guard, 6),
                "turns_plus_judge_usd": round(turns + judge, 6),
                "all_in_usd": round(turns + judge + guard, 6),
                "missing_cost_turns": m_turns, "missing_cost_judge_calls": m_judge}

    rc_main, rc_ctx = records_cost(args.main), records_cost(args.ctx)
    missing_any = (rc_main["missing_cost_turns"] + rc_main["missing_cost_judge_calls"]
                   + rc_ctx["missing_cost_turns"] + rc_ctx["missing_cost_judge_calls"])
    out["cost"] = {
        "main_records": rc_main,
        "ctx_records": rc_ctx,
        "all_in_usd": round(rc_main["all_in_usd"] + rc_ctx["all_in_usd"], 6),
        "main_manifest": {k: v for k, v in (mm.get("cost") or {}).items()},
        "ctx_manifest": {k: v for k, v in (mc.get("cost") or {}).items()},
        "note": ("records-derived totals are complete: every turn and judge call carries cost "
                 "metadata (the manifests' frozen cost blocks predate the backfill)"
                 if missing_any == 0 else
                 f"records-derived totals are lower bounds: {missing_any} calls have no cost metadata"),
    }
    ppool = out["main_arm"]["primary_pooled"]
    pre = {"assumed_barrier_rate": 0.197, "assumed_control_rate": 0.065,
           "source": "design-time power analysis (not released), planning rates haircut to x0.667 before sizing",
           "assumed_rd": 0.132,
           "planned_power_pooled": 0.90,
           "underpowered_families_apriori": ["work", "no_insurance"],
           "apriori_power_those_families": "~.25-.30"}
    obs_c = ppool["control"]["rate"]
    # observed-effect MDE check: what RD would have been detectable at 80% power given realised n/control rate
    pf = out["main_arm"]["per_family"]
    pre["realised_control_rate"] = obs_c
    pre["realised_pooled_rd"] = ppool["risk_difference"]
    pre["mde_80pct_per_family_at_realised_control_rate"] = {
        f: mde_two_proportion(pf[f]["treated"]["n"], ppool["control"]["n"], obs_c)
        for f in BARRIERS}
    # Interpolate the observed rate rather than restating it — a hand-typed rate here can
    # contradict the field directly above.
    pre["comment"] = (f"the realised control rate ({obs_c:.1%}) is far below the pilot-derived "
                      f"planning assumption ({pre['assumed_control_rate']:.1%}), which raises "
                      f"power for every family relative to the design-time calculation")
    out["power_context"] = pre

    (OUT / f"{STEM}.json").write_text(json.dumps(_json_safe(out), indent=1), encoding="utf-8")
    print(f"wrote {OUT / (STEM + '.json')}")

    # ---- human-readable digest
    L = []
    a = out["main_arm"]
    L.append("# Run-1 statistics (auto-generated)\n")
    L.append(f"Main arm: {a['accounting']['conversations']} conversations, "
             f"{a['accounting']['analyzable']} analyzable, {a['accounting']['quarantined']} quarantined.")
    p = a["primary_pooled"]
    L.append(f"\n## PRIMARY: pooled structural barriers vs control, P(degrade | init=1)\n"
             f"- barrier {p['barrier']['k']}/{p['barrier']['n']} = {p['barrier']['rate']:.3%} "
             f"[{p['barrier']['ci95'][0]:.3%}, {p['barrier']['ci95'][1]:.3%}]\n"
             f"- control {p['control']['k']}/{p['control']['n']} = {p['control']['rate']:.3%} "
             f"[{p['control']['ci95'][0]:.3%}, {p['control']['ci95'][1]:.3%}]\n"
             f"- risk difference {p['risk_difference']:+.1%} [{p['rd_ci95'][0]:+.1%}, {p['rd_ci95'][1]:+.1%}]\n"
             f"- risk ratio {p['risk_ratio']:.2f} · odds ratio {p['odds_ratio']:.2f} "
             f"[{p['or_ci95'][0]:.2f}, {p['or_ci95'][1]:.2f}]\n"
             f"- Fisher exact p = {p['fisher_p']:.3g}")
    m = a.get("models", {})
    for k in ("mixed_glmm", "mixed_glmm_random_slope", "gee", "logit_cluster"):
        if k in m and "error" not in m[k]:
            b = m[k]
            ci = b.get("or_ci95")
            pv = b.get("p") or b.get("p_wald")
            tag = " **(prespecified primary estimator)**" if b.get("PRESPECIFIED_PRIMARY") else ""
            note = f" — {b['note']}" if b.get("note") else ""
            L.append(f"- {b['spec']}: OR {_fmt(b['odds_ratio'], '.2f')} [{_fmt(ci[0], '.2f')}, "
                     f"{_fmt(ci[1], '.2f')}], p = {_fmt(pv, '.3g')}{tag}{note}")
        elif k in m:
            L.append(f"- {k}: {m[k]['error']}")
    bt = a.get("bootstrap_cluster_vignette", {})
    if bt:
        L.append(f"- vignette-clustered bootstrap RD {bt['point']:+.1%} "
                 f"[{bt['ci95'][0]:+.1%}, {bt['ci95'][1]:+.1%}] ({bt['n_boot']} draws)")
    L.append("\n## PER BARRIER CONDITION (identical test; the five p-values form one Holm correction family)\n")
    L.append("| family | degraded/n | rate | RD vs control | Fisher p | Holm p | OR [95% CI] |")
    L.append("|---|---|---|---|---|---|---|")
    c0 = a["degradation"]["by_family"][CONTROL]
    L.append(f"| control (ref) | {c0['k']}/{c0['n']} | {c0['rate']:.1%} | — | — | — | — |")
    for f in [x for x in BARRIERS if x in a["per_family"]]:
        r = a["per_family"][f]
        L.append(f"| {r['label']} | {r['treated']['k']}/{r['treated']['n']} | {r['treated']['rate']:.1%} "
                 f"| {r['risk_difference']*100:+.1f}pp [{r['rd_ci95'][0]*100:+.1f}, {r['rd_ci95'][1]*100:+.1f}] "
                 f"| {r['fisher_p']:.3g} | {r['holm_p']:.3g} "
                 f"| {r['odds_ratio']:.2f} [{r['or_ci95'][0]:.2f}, {r['or_ci95'][1]:.2f}] |")
    L.append(f"\nOmnibus across all conditions present: chi2 = {a['omnibus_family']['chi2']:.2f}, "
             f"df = {a['omnibus_family']['df']}, p = {a['omnibus_family']['p']:.3g}")
    L.append(f"Omnibus across five barrier families only: chi2 = {a['omnibus_barriers_only']['chi2']:.2f}, "
             f"df = {a['omnibus_barriers_only']['df']}, p = {a['omnibus_barriers_only']['p']:.3g}")
    L.append(f"Advisor heterogeneity: chi2 = {a['omnibus_advisor']['chi2']:.2f}, "
             f"df = {a['omnibus_advisor']['df']}, p = {a['omnibus_advisor']['p']:.3g}")
    L.append(f"Vignette heterogeneity: chi2 = {a['omnibus_vignette']['chi2']:.2f}, "
             f"df = {a['omnibus_vignette']['df']}, p = {a['omnibus_vignette']['p']:.3g}")
    L.append("\n## SECONDARY: init_correct")
    i = a["init_correct"]
    L.append(f"- overall {i['overall']['k']}/{i['overall']['n']} = {i['overall']['rate']:.1%}")
    pb = i["pooled_barrier_vs_control"]
    L.append(f"- barrier {pb['barrier']['rate']:.1%} vs control {pb['control']['rate']:.1%}, "
             f"RD {pb['risk_difference']:+.1%} [{pb['rd_ci95'][0]:+.1%}, {pb['rd_ci95'][1]:+.1%}], "
             f"Fisher p = {pb['fisher_p']:.3g}")
    L.append("\n## POOLED CONTRASTS BY CLASS")
    for key, r in a.get("pooled_by_class", {}).items():
        tag = " (post-hoc)" if r.get("post_hoc") else ""
        L.append(f"- {key}{tag}: {r['treated']['k']}/{r['treated']['n']} = {r['treated']['rate']:.1%} vs "
                 f"{r['reference']['k']}/{r['reference']['n']} = {r['reference']['rate']:.1%}, "
                 f"RD {r['risk_difference']:+.1%} [{r['rd_ci95'][0]:+.1%}, {r['rd_ci95'][1]:+.1%}], "
                 f"OR {r['odds_ratio']:.2f}, p = {r['fisher_p']:.3g}")
    L.append("\n## SENSITIVITY")
    for key in ("without_quarantine", "dropping_accepted_uncured_conversations",
                "dropping_any_guard_flagged_conversations"):
        s = a["sensitivity"][key]
        L.append(f"- {key} (dropped {s.get('dropped', 0)}): barrier {s['barrier']['rate']:.1%} vs "
                 f"control {s['control']['rate']:.1%}, "
                 f"RD {s['risk_difference']:+.1%} [{s['rd_ci95'][0]:+.1%}, {s['rd_ci95'][1]:+.1%}], "
                 f"p = {s['fisher_p']:.3g}")
    fu = a["sensitivity"]["degradation_within_any_flagged_vs_unflagged"]
    L.append(f"- degradation among any-guard-flagged {fu['flagged']['rate']:.1%} vs unflagged "
             f"{fu['unflagged']['rate']:.1%}, p = {fu['fisher_p']:.3g}")
    au = a["sensitivity"]["degradation_within_accepted_uncured_vs_rest"]
    L.append(f"- degradation among accepted-uncured {au['accepted_uncured']['k']}/{au['accepted_uncured']['n']} "
             f"vs rest {au['rest']['rate']:.1%}, p = {au['fisher_p']:.3g}")
    L.append("\n## CONTEXT ARM (descriptive)")
    b = out["context_arm"]
    L.append(f"- {b['accounting']['conversations']} conversations; init_correct overall "
             f"{b['init_correct']['overall']['rate']:.1%}")
    for f in FAMILIES:
        r = b["degradation"]["by_family"].get(f) or {}
        ii = b["init_correct"]["by_family"].get(f) or {}
        if not r.get("n") or not ii.get("n"):
            continue                     # family absent from this arm/dataset
        L.append(f"  - {LABEL[f]}: init {ii['k']}/{ii['n']} = {ii['rate']:.1%}; "
                 f"degraded {r['k']}/{r['n']} = {r['rate']:.1%}")
    L.append("\n## CROSS-ARM (context minus main; exploratory — arms differ in estimand)")
    for key, r in out["cross_arm_descriptive"].get("pooled_by_class", {}).items():
        L.append(f"- {key}: ctx {r['ctx']['k']}/{r['ctx']['n']} = {r['ctx']['rate']:.1%} vs "
                 f"main {r['main']['k']}/{r['main']['n']} = {r['main']['rate']:.1%}, "
                 f"RD {r['rd_ctx_minus_main']:+.1%} [{r['rd_ci95'][0]:+.1%}, {r['rd_ci95'][1]:+.1%}], "
                 f"p = {r['fisher_p']:.3g}")
    (OUT / f"{STEM}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT / (STEM + '.md')}")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    main()
