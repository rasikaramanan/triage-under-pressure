"""Random-effects logistic regression by maximum likelihood (Gauss-Hermite quadrature).

The prespecified primary model is a mixed-effects logistic
regression with vignette random intercepts (and treatment slopes, if estimable). statsmodels has
no Laplace/quadrature binomial GLMM — only a variational-Bayes fit whose posterior SDs are
anti-conservative on strongly separated data of this shape (interval widths far too narrow to
report).
This module integrates the random effects numerically instead, giving a genuine MLE with
likelihood-based inference: Wald intervals from the observed information, plus likelihood-ratio
tests that do not depend on the Wald approximation.

Models:
  random_intercept  logit P(y=1) = x'b + u_j,           u_j ~ N(0, s^2)
  random_slope      logit P(y=1) = x'b + u0_j + u1_j z, (u0,u1) ~ N(0, S)   [z = treatment]

Clusters here are vignettes (14), so the number of clusters is small; likelihood-based inference
on the fixed effects is appropriate, while cluster-robust sandwich SEs would not be.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats


def _log_sigmoid(x: np.ndarray) -> np.ndarray:
    return -np.logaddexp(0.0, -x)


def _cluster_loglik_ri(beta, log_s, X, y, groups, nodes, weights):
    """Sum over clusters of log ∫ Π p(y|eta+u) N(u;0,s²) du, via Gauss-Hermite."""
    s = math.exp(log_s)
    eta = X @ beta
    total = 0.0
    for g in np.unique(groups):
        m = groups == g
        e = eta[m][:, None] + (math.sqrt(2.0) * s) * nodes[None, :]   # (n_g, Q)
        yy = y[m][:, None]
        ll = (yy * _log_sigmoid(e) + (1 - yy) * _log_sigmoid(-e)).sum(axis=0)  # (Q,)
        mx = ll.max()
        total += mx + math.log(np.sum(weights * np.exp(ll - mx))) - 0.5 * math.log(math.pi)
    return total


def _cluster_loglik_rs(beta, theta, X, y, z, groups, nodes, weights):
    """Random intercept + slope; theta = (log s0, log s1, atanh rho)."""
    s0, s1 = math.exp(theta[0]), math.exp(theta[1])
    rho = math.tanh(theta[2])
    eta = X @ beta
    A, B = np.meshgrid(nodes, nodes, indexing="ij")
    W = np.outer(weights, weights).ravel()
    a, b = A.ravel(), B.ravel()
    u0 = math.sqrt(2.0) * s0 * a
    u1 = math.sqrt(2.0) * s1 * (rho * a + math.sqrt(max(1e-12, 1 - rho * rho)) * b)
    total = 0.0
    for g in np.unique(groups):
        m = groups == g
        e = eta[m][:, None] + u0[None, :] + z[m][:, None] * u1[None, :]
        yy = y[m][:, None]
        ll = (yy * _log_sigmoid(e) + (1 - yy) * _log_sigmoid(-e)).sum(axis=0)
        mx = ll.max()
        total += mx + math.log(np.sum(W * np.exp(ll - mx))) - math.log(math.pi)
    return total


def fit_random_intercept(X, y, groups, n_nodes: int = 60, names=None, penalty_sd=None):
    """MLE (or MAP with a weakly-informative N(0, penalty_sd^2) ridge on the non-intercept fixed
    effects, which keeps quasi-separated advisor cells finite; the penalty is disclosed wherever
    it is used)."""
    nodes, weights = np.polynomial.hermite.hermgauss(n_nodes)
    X, y = np.asarray(X, float), np.asarray(y, float)
    p = X.shape[1]

    def pen(beta):
        if not penalty_sd:
            return 0.0
        return 0.5 * float(np.sum(beta[1:] ** 2)) / (penalty_sd ** 2)

    def nll(par):
        return -_cluster_loglik_ri(par[:p], par[p], X, y, groups, nodes, weights) + pen(par[:p])

    start = np.zeros(p + 1)
    start[0] = math.log(max(y.mean(), 1e-3) / max(1 - y.mean(), 1e-3))
    start[p] = math.log(0.5)
    res = optimize.minimize(nll, start, method="L-BFGS-B",
                            bounds=[(-25, 25)] * p + [(-6, 4)],
                            options={"maxiter": 4000, "maxfun": 40000, "ftol": 1e-12, "gtol": 1e-9})
    res = optimize.minimize(nll, res.x, method="Nelder-Mead",
                            options={"maxiter": 8000, "fatol": 1e-10, "xatol": 1e-8})
    par = res.x
    # observed information by central differences
    H = _numhess(nll, par)
    try:
        cov = np.linalg.inv(H)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(p + 1, np.nan)
    out = {
        "loglik": float(-res.fun), "converged": bool(res.success),
        "sigma_vignette": float(math.exp(par[p])),
        "coef": {}, "n": int(len(y)), "n_clusters": int(len(np.unique(groups))),
        "quadrature_nodes": n_nodes,
    }
    names = names or [f"x{i}" for i in range(p)]
    def _e(v):
        return float(np.exp(np.clip(v, -50, 50)))

    for i, nm in enumerate(names):
        b, s = float(par[i]), float(se[i])
        out["coef"][nm] = {
            "logodds": b, "se": s, "odds_ratio": _e(b),
            "or_ci95": [_e(b - 1.959963985 * s), _e(b + 1.959963985 * s)],
            "z": b / s if s else None,
            "p_wald": float(2 * stats.norm.sf(abs(b / s))) if s else None,
        }
    out["penalty_sd"] = penalty_sd
    return out, par


def lrt_drop(X, y, groups, drop_idx: int, n_nodes: int = 60, penalty_sd=None):
    """Likelihood-ratio test dropping one fixed-effect column from the random-intercept model.
    Both fits use the same penalty, so the comparison is like-for-like."""
    full, _ = fit_random_intercept(X, y, groups, n_nodes, penalty_sd=penalty_sd)
    keep = [i for i in range(X.shape[1]) if i != drop_idx]
    red, _ = fit_random_intercept(X[:, keep], y, groups, n_nodes, penalty_sd=penalty_sd)
    stat = 2.0 * (full["loglik"] - red["loglik"])
    return {"chi2": float(stat), "df": 1, "p": float(stats.chi2.sf(stat, 1)),
            "loglik_full": full["loglik"], "loglik_reduced": red["loglik"]}


def fit_random_slope(X, y, z, groups, n_nodes: int = 24, names=None, penalty_sd=None):
    """Random-intercept + random-slope fit. ``penalty_sd`` applies the SAME weakly-informative
    ridge on the non-intercept fixed effects as ``fit_random_intercept`` — pass the same value
    used there so a likelihood-ratio comparison between the two fits is like-for-like."""
    nodes, weights = np.polynomial.hermite.hermgauss(n_nodes)
    X, y, z = np.asarray(X, float), np.asarray(y, float), np.asarray(z, float)
    p = X.shape[1]

    def pen(beta):
        if not penalty_sd:
            return 0.0
        return 0.5 * float(np.sum(beta[1:] ** 2)) / (penalty_sd ** 2)

    def nll(par):
        return -_cluster_loglik_rs(par[:p], par[p:], X, y, z, groups, nodes, weights) + pen(par[:p])

    start = np.zeros(p + 3)
    start[0] = math.log(max(y.mean(), 1e-3) / max(1 - y.mean(), 1e-3))
    start[p], start[p + 1], start[p + 2] = math.log(0.5), math.log(0.3), 0.0
    res = optimize.minimize(nll, start, method="BFGS", options={"maxiter": 1500, "gtol": 1e-5})
    par = res.x
    H = _numhess(nll, par)
    # A fit at the boundary of the random-effects space (intercept-slope correlation at +-1,
    # a variance at 0) has a singular Hessian: the Wald standard errors, intervals and p-values
    # are NOT ESTIMABLE at that fit. They are reported as None (JSON null) with a flag — never
    # as NaN, which is invalid JSON and which downstream formatters cannot render — and the
    # likelihood-based quantities (loglik, the LRT the caller computes) stay valid.
    singular = False
    try:
        se = np.sqrt(np.clip(np.diag(np.linalg.inv(H)), 0, None))
        if not np.all(np.isfinite(se)):
            singular = True
    except np.linalg.LinAlgError:
        singular = True
        se = np.full(p + 3, np.nan)
    names = names or [f"x{i}" for i in range(p)]
    out = {"loglik": float(-res.fun), "converged": bool(res.success),
           "penalty_sd": penalty_sd,
           "sigma_intercept": float(math.exp(par[p])),
           "sigma_slope": float(math.exp(par[p + 1])),
           "corr": float(math.tanh(par[p + 2])), "coef": {}, "quadrature_nodes": n_nodes,
           "hessian_singular": singular}
    if singular:
        out["note"] = ("Hessian singular at the fitted values (random-effects boundary): Wald "
                       "standard errors, intervals and p-values not estimable at this fit; "
                       "likelihood quantities remain valid")
    for i, nm in enumerate(names):
        b = float(par[i])
        s = None if singular or not np.isfinite(se[i]) else float(se[i])
        out["coef"][nm] = {"logodds": b, "se": s, "odds_ratio": math.exp(b),
                           "or_ci95": ([math.exp(b - 1.959963985 * s), math.exp(b + 1.959963985 * s)]
                                       if s else [None, None]),
                           "p_wald": float(2 * stats.norm.sf(abs(b / s))) if s else None}
    return out


def _numhess(f, x, eps: float = 1e-4):
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            xa, xb, xc, xd = x.copy(), x.copy(), x.copy(), x.copy()
            xa[i] += eps; xa[j] += eps
            xb[i] += eps; xb[j] -= eps
            xc[i] -= eps; xc[j] += eps
            xd[i] -= eps; xd[j] -= eps
            H[i, j] = H[j, i] = (f(xa) - f(xb) - f(xc) + f(xd)) / (4 * eps * eps)
    return H
