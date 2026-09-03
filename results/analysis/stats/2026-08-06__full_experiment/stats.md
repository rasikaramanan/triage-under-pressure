# Run-1 statistics (auto-generated)

Main arm: 1470 conversations, 1470 analyzable, 0 quarantined.

## PRIMARY: pooled structural barriers vs control, P(degrade | init=1)
- barrier 170/886 = 19.187% [16.730%, 21.911%]
- control 4/179 = 2.235% [0.872%, 5.604%]
- risk difference +17.0% [+12.8%, +20.0%]
- risk ratio 8.59 · odds ratio 10.39 [3.80, 28.38]
- Fisher exact p = 1.42e-10
- y ~ barrier + advisor + (1 | vignette); ML via Gauss-Hermite quadrature; estimation sample = five structural conditions + cooperative control (the non-structural comparator is excluded by design): OR 22.87 [7.54, 69.35], p = 3.22e-08 **(prespecified primary estimator)**
- y ~ barrier + advisor + (1 + barrier | vignette); ML quadrature: OR 21.78 [—, —], p = — — Hessian singular at the fitted values (random-effects boundary): Wald standard errors, intervals and p-values not estimable at this fit; likelihood quantities remain valid
- y ~ barrier + advisor, GEE exchangeable, clustered on vignette; estimation sample = five structural conditions + cooperative control (the non-structural comparator is excluded by design): OR 9.59 [4.38, 21.00], p = 1.57e-08
- y ~ barrier + advisor, logistic, vignette cluster-robust SEs; estimation sample = five structural conditions + cooperative control (the non-structural comparator is excluded by design): OR 13.74 [5.07, 37.19], p = 2.53e-07
- vignette-clustered bootstrap RD +17.0% [+11.7%, +22.7%] (5000 draws)

## PER BARRIER CONDITION (identical test; the five p-values form one Holm correction family)

| family | degraded/n | rate | RD vs control | Fisher p | Holm p | OR [95% CI] |
|---|---|---|---|---|---|---|
| control (ref) | 4/179 | 2.2% | — | — | — | — |
| caregiving | 34/176 | 19.3% | +17.1pp [+10.9, +23.7] | 6.63e-08 | 1.99e-07 | 10.48 [3.63, 30.22] |
| transport / ambulance cost | 37/179 | 20.7% | +18.4pp [+12.2, +25.1] | 1.92e-08 | 7.68e-08 | 11.40 [3.97, 32.74] |
| work | 33/176 | 18.8% | +16.5pp [+10.4, +23.1] | 1.33e-07 | 2.65e-07 | 10.10 [3.49, 29.17] |
| cost / medical debt | 40/177 | 22.6% | +20.4pp [+13.9, +27.2] | 9.94e-10 | 4.97e-09 | 12.77 [4.46, 36.57] |
| no insurance | 26/178 | 14.6% | +12.4pp [+6.8, +18.5] | 1.55e-05 | 1.55e-05 | 7.48 [2.55, 21.92] |

Omnibus across all conditions present: chi2 = 39.08, df = 6, p = 6.92e-07
Omnibus across five barrier families only: chi2 = 4.01, df = 4, p = 0.404
Advisor heterogeneity: chi2 = 239.66, df = 4, p = 1.1e-50
Vignette heterogeneity: chi2 = 79.67, df = 13, p = 1.28e-11

## SECONDARY: init_correct
- overall 1238/1470 = 84.2%
- barrier 84.4% vs control 85.2%, RD -0.9% [-5.6%, +5.0%], Fisher p = 0.835

## POOLED CONTRASTS BY CLASS
- structural_vs_cooperative: 170/886 = 19.2% vs 4/179 = 2.2%, RD +17.0% [+12.8%, +20.0%], OR 10.39, p = 1.42e-10
- nonstructural_vs_cooperative: 40/173 = 23.1% vs 4/179 = 2.2%, RD +20.9% [+14.3%, +27.8%], OR 13.16, p = 7.05e-10
- structural_vs_nonstructural: 170/886 = 19.2% vs 40/173 = 23.1%, RD -3.9% [-11.2%, +2.3%], OR 0.79, p = 0.252
- any_obstacle_vs_cooperative (post-hoc): 210/1059 = 19.8% vs 4/179 = 2.2%, RD +17.6% [+13.5%, +20.5%], OR 10.82, p = 3.29e-11

## SENSITIVITY
- without_quarantine (dropped 0): barrier 19.2% vs control 2.2%, RD +17.0% [+12.8%, +20.0%], p = 1.42e-10
- dropping_accepted_uncured_conversations (dropped 2): barrier 19.2% vs control 2.2%, RD +17.0% [+12.8%, +20.0%], p = 1.4e-10
- dropping_any_guard_flagged_conversations (dropped 70): barrier 19.2% vs control 2.6%, RD +16.6% [+12.0%, +19.8%], p = 6.6e-09
- degradation among any-guard-flagged 12.9% vs unflagged 17.6%, p = 0.415
- degradation among accepted-uncured 0/2 vs rest 17.3%, p = 1

## CONTEXT ARM (descriptive)
- 490 conversations; init_correct overall 81.4%
  - control: init 59/70 = 84.3%; degraded 0/59 = 0.0%
  - hospital fear (non-structural): init 56/70 = 80.0%; degraded 9/56 = 16.1%
  - caregiving: init 55/70 = 78.6%; degraded 12/55 = 21.8%
  - transport / ambulance cost: init 58/70 = 82.9%; degraded 8/58 = 13.8%
  - work: init 58/70 = 82.9%; degraded 7/58 = 12.1%
  - cost / medical debt: init 56/70 = 80.0%; degraded 9/56 = 16.1%
  - no insurance: init 57/70 = 81.4%; degraded 4/57 = 7.0%

## CROSS-ARM (context minus main; exploratory — arms differ in estimand)
- degradation_any_obstacle: ctx 49/340 = 14.4% vs main 210/1059 = 19.8%, RD -5.4% [-9.6%, -0.7%], p = 0.0248
- degradation_structural: ctx 40/284 = 14.1% vs main 170/886 = 19.2%, RD -5.1% [-9.6%, +0.0%], p = 0.0511
- degradation_nonstructural: ctx 9/56 = 16.1% vs main 40/173 = 23.1%, RD -7.0% [-17.1%, +6.0%], p = 0.349
- degradation_cooperative: ctx 0/59 = 0.0% vs main 4/179 = 2.2%, RD -2.2% [-5.6%, +4.0%], p = 0.575
- init_correct_all_conditions: ctx 399/490 = 81.4% vs main 1238/1470 = 84.2%, RD -2.8% [-6.9%, +1.0%], p = 0.16
