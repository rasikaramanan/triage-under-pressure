# Flagged-exclusion sensitivity

Run: `2026-08-06__full_experiment`  ·  generated 2026-09-10T05:05:29+00:00

Does dropping every conversation the fidelity guard flagged — any flag at all, cured or not — change any verdict the write-up states?

Dropped every conversation carrying at least one guard flag: 120 of 1960, leaving 1840 (82 main arm, 38 context arm).

**42 of 42 write-up verdicts hold.** Across every test in the statistics, 186 of 189 comparable p-values keep their side of alpha = 0.05.

## The write-up's verdicts

| verdict | record p | without flagged | holds |
|---|---|---|---|
| the headline contrast: the structural barriers against the cooperative control | 1.42e-10 (significant) | 6.6e-09 (significant) | yes |
| any obstacle against the cooperative control (post-hoc pooling) | 3.29e-11 (significant) | 1.37e-09 (significant) | yes |
| hospital fear against the cooperative control | 7.05e-10 (significant) | 2.36e-08 (significant) | yes |
| the mixed-effects model behind the headline contrast | 3.22e-08 (significant) | 1.2e-07 (significant) | yes |
| the likelihood-ratio companion to the mixed-effects model | 1.54e-14 (significant) | 8.43e-13 (significant) | yes |
| the population-averaged companion model | 1.57e-08 (significant) | 1.84e-07 (significant) | yes |
| the cluster-robust companion model | 2.53e-07 (significant) | 3.3e-06 (significant) | yes |
| the random-slope test: obstacle effects do not vary detectably across cases | 0.687 (not-significant) | 0.554 (not-significant) | yes |
| the reason test, locked phrasing: the structural/fear difference is not statistically significant | 0.252 (not-significant) | 0.286 (not-significant) | yes |
| the per-obstacle Holm family: caregiving | 1.99e-07 (significant) | 2.57e-06 (significant) | yes |
| the per-obstacle Holm family: transport access | 7.68e-08 (significant) | 4.17e-07 (significant) | yes |
| the per-obstacle Holm family: work | 2.65e-07 (significant) | 3.59e-06 (significant) | yes |
| the per-obstacle Holm family: cost/medical debt | 4.97e-09 (significant) | 2.85e-07 (significant) | yes |
| the per-obstacle Holm family: no insurance | 1.55e-05 (significant) | 6.85e-05 (significant) | yes |
| the five structural barriers are not distinguishable from each other | 0.404 (not-significant) | 0.593 (not-significant) | yes |
| the seven groups differ overall | 6.92e-07 (significant) | 1.59e-05 (significant) | yes |
| the model matters more than the obstacle: advisors differ | 1.1e-50 (significant) | 3.01e-51 (significant) | yes |
| cases differ | 1.28e-11 (significant) | 7.83e-11 (significant) | yes |
| the per-advisor pattern: Claude | 3.32e-05 (significant) | 0.00437 (significant) | yes |
| the per-advisor pattern: Gemini | 0.434 (not-significant) | 0.439 (not-significant) | yes |
| the per-advisor pattern: Llama | 0.00152 (significant) | 0.000892 (significant) | yes |
| the per-advisor pattern: GPT | 0.249 (not-significant) | 0.243 (not-significant) | yes |
| the per-advisor pattern: Grok | 0.434 (not-significant) | 0.439 (not-significant) | yes |
| the advisor terms in the mixed-effects model: Gemini | 8.59e-17 (significant) | 1.43e-16 (significant) | yes |
| the advisor terms in the mixed-effects model: Llama | 1.02e-05 (significant) | 4.05e-05 (significant) | yes |
| the headline contrast with the weakest advisor removed | 8.49e-08 (significant) | 2.51e-06 (significant) | yes |
| the built-in check: first-response accuracy does not differ before the obstacle appears | 0.835 (not-significant) | 0.912 (not-significant) | yes |
| the fine print's accepted-uncured robustness cut | 1.4e-10 (significant) | 6.6e-09 (significant) | yes |
| the fine print's any-flag robustness cut (the cut this analysis generalises) | 6.6e-09 (significant) | 6.6e-09 (significant) | yes |
| flagged conversations do not degrade more than unflagged ones | 0.415 (not-significant) | 1 (not-significant) | yes |
| the context arm: the structural barriers against that arm's own control | 0.000528 (significant) | 0.00152 (significant) | yes |
| the context arm: any obstacle against that arm's own control | 0.00037 (significant) | 0.00171 (significant) | yes |
| the context arm: hospital fear against that arm's own control | 0.00108 (significant) | 0.0128 (significant) | yes |
| the context arm's per-obstacle tests: caregiving | 7.94e-05 (significant) | 0.00125 (significant) | yes |
| the context arm's per-obstacle tests: cost/medical debt | 0.00108 (significant) | 0.00306 (significant) | yes |
| the context arm's per-obstacle tests: transport access | 0.00281 (significant) | 0.00577 (significant) | yes |
| the context arm's per-obstacle tests: work | 0.00606 (significant) | 0.0136 (significant) | yes |
| the context arm's per-obstacle tests: no insurance (not significant) | 0.0552 (not-significant) | 0.121 (not-significant) | yes |
| the cross-arm comparison: degradation under any obstacle | 0.0248 (significant) | 0.0206 (significant) | yes |
| the cross-arm comparison: degradation under the structural barriers | 0.0511 (not-significant) | 0.068 (not-significant) | yes |
| the cross-arm first-response dip, locked phrasing: not significant | 0.16 (not-significant) | 0.215 (not-significant) | yes |
| no single obstacle's cross-arm difference is individually significant | 0.173 (not-significant) | 0.172 (not-significant) | yes |

## Effect directions

- the headline risk difference: 0.16952722044970175 → 0.16641052951917223 (same sign)
- the headline risk ratio: 8.586343115124153 → 7.448408018867925 (same sign)
- any obstacle against the cooperative control: 0.17595391457103518 → 0.1726140814571856 (same sign)
- hospital fear against the cooperative control: 0.20886750411728613 → 0.20449657869012708 (same sign)
- the context arm's structural contrast: 0.14084507042253522 → 0.1417910447761194 (same sign)

## Every other test that changed side (4)

- `main_arm/models/mixed_glmm_random_slope/p_wald`: None (unavailable) → 1.7921298407602927e-06 (significant)
- `context_arm/omnibus_family/p`: 0.0138 (significant) → 0.0575 (not-significant)
- `context_arm/sensitivity_drop_weakest_advisor/fisher_p`: 0.031 (significant) → 0.0851 (not-significant)
- `context_arm/sensitivity_drop_weakest_advisor/per_family/cost_medical_debt/fisher_p`: 0.0241 (significant) → 0.0583 (not-significant)

