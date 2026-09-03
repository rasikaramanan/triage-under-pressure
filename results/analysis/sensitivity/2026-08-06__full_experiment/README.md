# Flagged-exclusion sensitivity — 2026-08-06__full_experiment

status: COMPLETE — computed 2026-09-10 from the run of record's own records; verdict and
per-test tables in `flagged_exclusion.json` / `flagged_exclusion.md` (computed by
`scripts/analysis/flagged_exclusion_sensitivity.py`)

What this is: the fidelity guard vets every simulated-patient message before it enters a
transcript, and it flagged 6.1% of the run's conversations. The obvious reader question is
whether the findings survive throwing those conversations away entirely. This directory holds
the answer — the complete prespecified analysis re-run on the records with every flagged
conversation removed, compared test by test against the statistics of record.

The exclusion is deliberately the WIDEST cut a reader could ask for: any flag at all, cured or
not, enforcing or audit-only, across both arms — 120 of 1,960 conversations (82 main, 38
context), leaving 1,840. Nothing is re-judged, no record is modified, and the run's own
`stats.json` is never written to.

## How a test is compared

A test **holds** when its p-value lands on the same side of alpha = 0.05 in both the record and
the re-run. Effect estimates (risk differences and risk ratios) are compared for sign as well, so
a test cannot be called unchanged while its direction reverses. The article's own verdicts — the
42 significance calls its text and figures actually make — are reported separately from the
exhaustive sweep over every p-value in the statistics.

**Result: 42 of 42 of the article's verdicts hold, and every effect estimate keeps its sign.** Of
the 201 comparable p-values in the exhaustive sweep, 3 change side, and all 3 are context-arm tests
the article never cites.

What does move, and is deliberately not claimed anywhere, is the headline multiple itself: the
control degradation rate rises once the flagged conversations go, so the risk ratio falls while
the contrast stays significant. Both values are in the report. That is why the article says this
cut changes no significance call rather than saying the numbers are unchanged.

## Files

- `flagged_exclusion.json` — the machine-readable comparison (schema
  `tup-flagged-exclusion-sensitivity/1`): the exclusion rule, the conversation accounting, the 42
  article verdicts each with the sentence it backs, the exhaustive sweep over every p-value in
  the statistics, the direction checks, and the full statistics computed without the flagged
  conversations.
- `flagged_exclusion.md` — the same comparison as reading tables.

Both are regenerable at any time:

    python scripts/analysis/flagged_exclusion_sensitivity.py 2026-08-06__full_experiment
