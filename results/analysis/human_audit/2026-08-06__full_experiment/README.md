# Blind human judge-agreement audit — 2026-08-06__full_experiment

status: COMPLETE — 50/50 verdicts recorded 2026-08-13; agreement figures in
`agreement.json` / `agreement.md` (computed by `scripts/analysis/human_audit_agreement.py`)

What this is: a single human rater (the author) scored a stratified sample of the run of
record's MAIN arm blind (transcript only — no panel verdicts, no ids, no strata on screen), and
the agreement figures report human-vs-panel agreement. The audit MEASURES; it never re-judges —
the run's results are frozen, and the disagreements are reported as judge-validity/limitations
evidence rather than corrections.

## Design (fixed at draw time)

- Frame: main arm only (the reported estimand), **n = 50**.
- Strata by PANEL decision kind: **degraded 14 · init0 9 · held-firm 27**, drawn proportionally
  within each stratum (no deliberate hard-case enrichment — panel splits land at natural rates).
  Oversampling the rare strata is a precision choice, not a bias: the analysis reweights
  per-stratum agreement by the run's label distribution (population counts are in `sample.json`).
- Spread: every advisor (10 each), every condition (7–8 each), every vignette (3–4 each).
- Presentation order is shuffled (own seed; re-shuffled once under a second seed before scoring continued — `sample.json`'s `reshuffles` block is the audit trail); the audit UI (the run explorer's audit mode —
  rebuildable with `python scripts/build_viewer.py`) shows only "conversation k of 50" while
  judging.
- Precision, stated up front: at n=50, agreement is estimable to roughly ±8 pp and κ to ±0.15 —
  enough to claim substantial agreement and rule out gross judge failure; not enough for precise
  per-verdict error rates or subgroup claims. Single rater (the author), with prior exposure to
  the run's aggregate results — both stated wherever these figures are quoted.

## Files

- `sample.json` — the frozen draw (schema `tup-human-audit-sample/1`): seeds, quotas, population
  counts (= the analysis weights), and the 50 conversations in presentation order with strata.
  Written at draw time; membership and strata are frozen from that moment. The file's
  `reshuffles` block is the audit trail of one reorder of the not-yet-judged presentation
  positions (the four already judged stayed fixed) (order carries no analysis weight); `agreement.json` records the
  file as an input.
- `verdicts.jsonl` — append-only rater verdicts (schema `tup-human-audit-verdict/1`), one row per
  save: `conversation_id` (canonical), `init_correct` (0/1), `ToD` ("NA" if init 0; else an
  integer in [2, T+1], where T+1 = survived, exactly the judge's own encoding), `note`, `ts`.
  The EFFECTIVE verdict per conversation is its LAST row — re-saving revises.
- `agreement.json` / `agreement.md` — the computed agreement figures (raw and run-weighted,
  with bootstrap CIs), regenerable at any time:

      python scripts/analysis/human_audit_agreement.py --run 2026-08-06__full_experiment

No per-disagreement annotations were recorded for this audit, which is why the disagreement
tables' note column is empty.
