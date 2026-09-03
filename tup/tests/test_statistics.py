"""The statistics that produce every published number, checked against independent implementations.

WHY THIS FILE EXISTS

The estimators in ``scripts/analysis/analyze_experiment.py`` — ``wilson``, ``newcombe_rd``,
``or_ci``, ``holm``, ``cluster_bootstrap_rd``, ``resistance``, ``mde_two_proportion`` — have no
test coverage anywhere else, yet they compute every confidence interval, risk difference and
p-value the published stats report. A silent arithmetic error in any of them would be invisible: the pipeline would still run,
still produce plausible numbers, and still pass every completeness check, because completeness and
correctness are different questions.

Each base estimator is checked against a DIFFERENT implementation (statsmodels / scipy) or a
closed-form value; the two composite helpers (resistance intervals, the rate block) are checked for
consistency with the already-verified ``wilson``. Agreement with an independent library is evidence; agreement
with a golden file this repo generated is not.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "analysis"))
import analyze_experiment as A  # noqa: E402

TOL = 1e-9


# --------------------------------------------------------------------- Wilson interval
@pytest.mark.parametrize("k,n", [(0, 10), (1, 10), (5, 10), (9, 10), (10, 10),
                                 (25, 1470), (1, 490), (245, 490), (3, 7), (0, 1), (1, 1)])
def test_wilson_matches_statsmodels(k, n):
    lo, hi = A.wilson(k, n)
    slo, shi = proportion_confint(k, n, alpha=0.05, method="wilson")
    assert lo == pytest.approx(slo, abs=1e-12)
    assert hi == pytest.approx(shi, abs=1e-12)


def test_wilson_is_clamped_to_the_unit_interval():
    for k, n in [(0, 5), (5, 5), (0, 1000), (1000, 1000)]:
        lo, hi = A.wilson(k, n)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_on_an_empty_sample_is_maximally_uninformative():
    """n=0 must not divide by zero, and must not claim knowledge it does not have."""
    assert A.wilson(0, 0) == (0.0, 1.0)


def test_wilson_contains_the_point_estimate():
    for k, n in [(1, 10), (5, 10), (9, 10), (25, 1470), (245, 490)]:
        lo, hi = A.wilson(k, n)
        assert lo <= k / n <= hi


def test_the_z_constant_is_the_exact_two_sided_95_quantile():
    assert A.Z == pytest.approx(sps.norm.isf(0.025), abs=1e-12)


# --------------------------------------------------------------------- Newcombe risk difference
@pytest.mark.parametrize("k1,n1,k0,n0", [(56, 70, 48, 80), (25, 1470, 1, 490),
                                         (0, 50, 0, 50), (10, 10, 0, 10), (245, 1050, 5, 210)])
def test_newcombe_rd_matches_statsmodels_newcombe(k1, n1, k0, n0):
    """Newcombe method 10 (square-and-add of two Wilson intervals)."""
    from statsmodels.stats.proportion import confint_proportions_2indep
    d, lo, hi = A.newcombe_rd(k1, n1, k0, n0)
    slo, shi = confint_proportions_2indep(k1, n1, k0, n0, method="newcomb",
                                          compare="diff", alpha=0.05)
    assert d == pytest.approx(k1 / n1 - k0 / n0, abs=TOL)
    assert lo == pytest.approx(slo, abs=1e-9)
    assert hi == pytest.approx(shi, abs=1e-9)


def test_newcombe_rd_interval_brackets_its_point_estimate():
    for args in [(56, 70, 48, 80), (25, 1470, 1, 490), (3, 100, 30, 100)]:
        d, lo, hi = A.newcombe_rd(*args)
        assert lo <= d <= hi


def test_newcombe_rd_is_antisymmetric_under_swapping_the_groups():
    d1, lo1, hi1 = A.newcombe_rd(25, 1470, 1, 490)
    d2, lo2, hi2 = A.newcombe_rd(1, 490, 25, 1470)
    assert d1 == pytest.approx(-d2, abs=TOL)
    assert lo1 == pytest.approx(-hi2, abs=TOL) and hi1 == pytest.approx(-lo2, abs=TOL)


def test_newcombe_rd_is_clamped_to_plus_minus_one():
    _, lo, hi = A.newcombe_rd(10, 10, 0, 10)
    assert -1.0 <= lo <= hi <= 1.0


# --------------------------------------------------------------------- odds ratio
@pytest.mark.parametrize("a,b,c,d", [(25, 1445, 1, 489), (10, 90, 5, 95), (56, 14, 48, 32)])
def test_or_ci_matches_statsmodels_woolf_when_no_cell_is_zero(a, b, c, d):
    from statsmodels.stats.contingency_tables import Table2x2
    orv, lo, hi, corrected = A.or_ci(a, b, c, d)
    t = Table2x2(np.array([[a, b], [c, d]]))
    slo, shi = t.oddsratio_confint(alpha=0.05)
    assert corrected is False
    assert orv == pytest.approx(t.oddsratio, rel=1e-12)
    assert lo == pytest.approx(slo, rel=1e-9) and hi == pytest.approx(shi, rel=1e-9)


def test_or_ci_applies_haldane_anscombe_only_when_a_cell_is_zero():
    """A zero cell makes the odds ratio 0 or infinite and the Woolf SE undefined; the 0.5
    correction is applied AND reported, so a reader can tell a corrected estimate from a raw one."""
    orv, lo, hi, corrected = A.or_ci(0, 50, 10, 40)
    assert corrected is True and math.isfinite(orv) and orv > 0
    from statsmodels.stats.contingency_tables import Table2x2
    t = Table2x2(np.array([[0.5, 50.5], [10.5, 40.5]]))
    assert orv == pytest.approx(t.oddsratio, rel=1e-12)


def test_or_ci_interval_brackets_the_point_estimate():
    for args in [(25, 1445, 1, 489), (0, 50, 10, 40), (10, 90, 5, 95)]:
        orv, lo, hi, _ = A.or_ci(*args)
        assert lo <= orv <= hi


# --------------------------------------------------------------------- Fisher exact
def test_fisher_matches_scipy_and_is_two_sided():
    for a, b, c, d in [(25, 1445, 1, 489), (10, 90, 5, 95), (0, 50, 10, 40)]:
        assert A.fisher(a, b, c, d) == pytest.approx(
            sps.fisher_exact([[a, b], [c, d]], alternative="two-sided")[1], abs=1e-15)


def test_fisher_is_symmetric_under_swapping_rows():
    assert A.fisher(25, 1445, 1, 489) == pytest.approx(A.fisher(1, 489, 25, 1445), abs=1e-15)


# --------------------------------------------------------------------- Holm correction
@pytest.mark.parametrize("pv", [
    [0.001, 0.008, 0.039, 0.041, 0.042],
    [0.01, 0.01, 0.01],
    [0.5, 0.6, 0.7],
    [1e-9, 0.2],
    [0.04],
])
def test_holm_matches_statsmodels(pv):
    keys = [f"h{i}" for i in range(len(pv))]
    got = A.holm(dict(zip(keys, pv)))
    want = multipletests(pv, alpha=0.05, method="holm")[1]
    for k, w in zip(keys, want):
        assert got[k] == pytest.approx(w, abs=1e-12)


def test_holm_is_monotone_and_never_below_the_raw_p():
    pv = {"a": 0.001, "b": 0.02, "c": 0.03, "d": 0.04}
    adj = A.holm(pv)
    assert all(adj[k] >= pv[k] - 1e-15 for k in pv)
    ordered = [adj[k] for k in sorted(pv, key=lambda k: pv[k])]
    assert ordered == sorted(ordered)


def test_holm_is_capped_at_one():
    assert all(v <= 1.0 for v in A.holm({"a": 0.9, "b": 0.95, "c": 0.99}).values())


def test_holm_is_insensitive_to_input_order_including_ties():
    """Ties are common here (identical p-values across families). Whichever order the dict happens
    to be built in must not change any adjusted value."""
    base = {"a": 0.05, "b": 0.05, "c": 0.01, "d": 0.05}
    ref = A.holm(base)
    for perm in ([("d", .05), ("c", .01), ("b", .05), ("a", .05)],
                 [("b", .05), ("a", .05), ("d", .05), ("c", .01)]):
        assert A.holm(dict(perm)) == ref


# --------------------------------------------------------------------- resistance curve
def test_resistance_is_the_survival_function_of_tod():
    d = pd.DataFrame({"tod": [1, 2, 3, 9, 9, 9]})     # 9 == T+1, i.e. never degraded
    out = A.resistance(d, T=8)
    assert out["1"]["k"] == 5 and out["1"]["n"] == 6           # ToD > 1
    assert out["2"]["k"] == 4
    assert out["8"]["k"] == 3                                   # survived the whole conversation
    assert out["1"]["survival"] == pytest.approx(5 / 6)


def test_resistance_is_non_increasing_in_t():
    d = pd.DataFrame({"tod": [1, 2, 3, 4, 5, 6, 7, 8, 9, 9]})
    out = A.resistance(d, T=8)
    ks = [out[str(t)]["k"] for t in range(1, 9)]
    assert ks == sorted(ks, reverse=True)


def test_resistance_intervals_agree_with_wilson_on_the_same_counts():
    d = pd.DataFrame({"tod": [1, 2, 9, 9, 9]})
    out = A.resistance(d, T=8)
    for t in range(1, 9):
        b = out[str(t)]
        assert tuple(b["ci95"]) == A.wilson(b["k"], b["n"])


# --------------------------------------------------------------------- MDE
def test_mde_reproduces_the_closed_form_two_proportion_power():
    """The module's bisection must land where the normal-approximation power equation says."""
    za, zb = sps.norm.isf(0.025), sps.norm.isf(1 - 0.80)

    def z_at(delta, n1, n0, p0):
        p1 = p0 + delta
        se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
        return delta / se

    for n1, n0, p0 in [(210, 210, 0.017), (1050, 210, 0.05), (300, 300, 0.10)]:
        d = A.mde_two_proportion(n1, n0, p0)
        assert z_at(d, n1, n0, p0) >= (za + zb) - 1e-6      # detectable at the returned MDE
        assert z_at(d * 0.9, n1, n0, p0) < (za + zb)        # ... and not at 90% of it


# --------------------------------------------------------------------- cluster bootstrap
def _boot_frame(seed=0, n_vig=14):
    rng = np.random.default_rng(seed)
    rows = []
    for v in range(n_vig):
        for fam in ("control", "work", "caregiving"):
            for _ in range(10):
                rows.append({"vignette": f"{v:03d}", "family": fam,
                             "degraded": int(rng.random() < (0.02 if fam == "control" else 0.18))})
    return pd.DataFrame(rows)


def test_cluster_bootstrap_point_estimate_is_the_plain_difference_of_means():
    d = _boot_frame()
    out = A.cluster_bootstrap_rd(d, n_boot=200)
    want = (d[d.family.isin(A.STRUCTURAL)].degraded.mean() - d[d.family == "control"].degraded.mean())
    assert out["point"] == pytest.approx(want, abs=1e-12)


def test_cluster_bootstrap_interval_brackets_the_point_and_reports_its_draw_count():
    d = _boot_frame()
    out = A.cluster_bootstrap_rd(d, n_boot=300)
    lo, hi = out["ci95"]
    assert lo <= out["point"] <= hi
    assert out["n_boot"] <= 300 and out["se"] > 0


def test_cluster_bootstrap_resamples_VIGNETTES_not_rows():
    """Clustering is the whole point: rows within a vignette are correlated, so a row bootstrap
    would understate the standard error. With one vignette there is nothing to resample, so every
    draw is identical and the interval collapses — a row bootstrap would still show spread."""
    d = _boot_frame(n_vig=1)
    out = A.cluster_bootstrap_rd(d, n_boot=100)
    lo, hi = out["ci95"]
    assert hi - lo == pytest.approx(0.0, abs=1e-12)
    assert out["se"] == pytest.approx(0.0, abs=1e-12)


def test_cluster_bootstrap_is_reproducible_for_a_fixed_module_seed():
    """RNG is a module-level default_rng(...) with a fixed seed, so the published interval must be
    regenerable. Re-seeding between calls is what makes the two runs comparable."""
    d = _boot_frame()
    A.RNG = np.random.default_rng(20260805)
    first = A.cluster_bootstrap_rd(d, n_boot=200)
    A.RNG = np.random.default_rng(20260805)
    second = A.cluster_bootstrap_rd(d, n_boot=200)
    assert first == second


# --------------------------------------------------------------------- rate_block
def test_rate_block_reports_counts_rate_and_a_wilson_interval():
    b = A.rate_block(25, 1470)
    assert b["k"] == 25 and b["n"] == 1470
    assert b["rate"] == pytest.approx(25 / 1470)
    assert tuple(b["ci95"]) == A.wilson(25, 1470)


def test_rate_block_on_an_empty_denominator_reports_no_rate_rather_than_zero():
    """0/0 is 'unknown', not 0% — reporting 0.0 would be a claim the data does not support."""
    b = A.rate_block(0, 0)
    assert b["rate"] is None and b["n"] == 0
