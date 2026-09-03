# Reproducing TUP

Reproduction runs in tiers of increasing cost and decreasing exactness — tier 0 through
tier 3, plus a $0 end-to-end check at the free-to-paid boundary. Read the setup section
first; do not skip it.

## Setup — a fresh virtual environment is REQUIRED

**Python ≥ 3.11**, and always a **fresh venv**. Do not install into a shared or base
environment: if it already holds a partial or broken copy of any dependency (for example a stale `openai`
install), pip will *skip* it instead of repairing it, and the tools will
crash with `ModuleNotFoundError` deep inside a third-party import.

Two install options:

```bash
# Exact reproduction (tier 1 becomes byte-identical) — requires Python 3.11:
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock
```

```bash
# Current libraries (any Python ≥ 3.11) — everything works; see the tier-1 tolerance note:
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.lock` pins the exact environment of record; `requirements.txt` declares floors
and is test-enforced against the imports in both directions. The lock reproduces the environment
of record (Python 3.11); the floors install on a current Python.

No API key is needed until tier 2.

## Tier 0 — verify the released dataset (offline, seconds)

Before reproducing anything, prove the dataset you cloned is intact and is the dataset the
paper reports:

```bash
python scripts/verify_run.py 2026-08-06__full_experiment
python scripts/verify_store.py
python scripts/build_roster.py --check
python -m pytest tup/tests -q
```

`verify_run` runs 87 checks — grid completeness, judgment integrity, the
fail-closed lock re-derived from the persisted records, and byte-hashes against the run's own
`instrument/` snapshot (the exact prompt/config/vignette files the run executed under, frozen
at preflight). It must end `ALL CHECKS PASSED`. Before that line it prints an informational
note that the working tree has diverged from the run's instrument in a list of files: those are
the shipped prompt, config and provenance files, whose comments and annotations were edited for
release after the run; no locked value or prompt body changed, and the checks read the snapshot,
never the working tree.

## Tier 1 — recompute every published number (offline, free)

All statistics derive from the released records plus one declared input, the adjudicated
exclusion set (`results/runs/2026-08-06__full_experiment/exclusions/quarantine.json` — which
is empty: zero conversations were quarantined).

```bash
python scripts/analysis/analyze_experiment.py 2026-08-06__full_experiment
python scripts/analysis/human_audit_agreement.py --run 2026-08-06__full_experiment
```

(The mixed-model fits — the analysis's primary specification — run inside `analyze_experiment.py`, which
imports `scripts/analysis/glmm.py` as a library; there is no separate command to run.)

Both commands **regenerate the committed output files in place**, so the comparison mechanism
is git itself:

```bash
git diff --stat results/analysis/    # what changed?
git checkout -- results/analysis/    # restore the committed versions afterwards
```

What to expect, precisely:

- **Under `requirements.lock` on Python 3.11**: `stats.json` regenerates **byte-identical** —
  `git diff` shows nothing for it.
- **Under newer library versions**: expect floating-point noise in the trailing digits of
  `stats.json` (optimizer convergence in numpy/scipy/statsmodels differs across versions).
  Every figure in `stats.md` — the human-readable digest, and the values the write-up reports —
  must still match at its printed precision; at most a final digit of a p-value sitting on a
  rounding boundary may flip (e.g. `8.76e-08` vs `8.75e-08`). Anything larger than
  last-digit noise is a real discrepancy — please open an issue.
- `agreement.json` always rewrites its `computed_at` timestamp; its statistics follow the same
  rule (byte-identical under the lock, tail-noise otherwise). The bootstrap is seeded, so
  resampling variation is not a source of drift.

## Before you spend — the $0 end-to-end check

This runs the REAL launcher through every preflight gate (lock assertion, model validation,
sampling provenance), the instrument snapshot, multi-turn orchestration, the fidelity guard,
the judging plumbing, and persistence — against a mock SDK, offline, with no API key
configured. Run tier 0 and this first in a fresh clone; if it completes, every moving part of
the pipeline works on your machine, and a key and a budget are safe to commit to tier 2 or 3:

```bash
python scripts/run_experiment.py --run-name demo --dry-run --max-spend 1 --max-turns 8 \
    --vignettes 001 --families control,cost_medical_debt --advisors anthropic \
    --replicates-main 1 --arms main
```

Output lands under `results/dry_runs/` (gitignored).

## Tier 2 — re-judge the stored transcripts (needs an API key, ~$51 for the main arm; both arms ~$67)

The transcripts are fixed; this tier tests whether the *scoring* reproduces. Copy
`.env.example` to `.env`, add your OpenRouter key, then:

```bash
python scripts/rejudge.py 2026-08-06__full_experiment --arm main --all --max-spend 60 --concurrency 16
```

`--max-spend` is required — typing the cap is the authorization, as for the launcher — and is
checked before every dispatch; a record not yet re-judged when the cap is hit keeps its prior
judgment. `--concurrency` (default 16, shown explicitly above) runs records through a thread
pool. Without a key the command fails before touching any record. Judges sample at temperature 0.2 where the model accepts it (two of the five slate models reject sampling parameters, so a panel can carry up to two seats judged at the provider default — see `config/models.yaml`), so expect per-conversation agreement, not byte identity — the run's own panel statistics (`stats.json` → `main_arm.judge_panel`: seat splits and
unanimity rates) are the calibration for how much seat-level disagreement is normal, and the
released human audit (`results/analysis/human_audit/`) benchmarks the aggregated panel
against a human rater. **Re-judging writes new judgments (after taking a `.bak`); work on a copy of the run
directory, never the shipped one.**

## Tier 3 — re-run the experiment live (~$150+, will NOT reproduce exactly)

The full design is prespecified and executable: every one of the 1,960 conversations is
enumerated in advance in `config/roster.csv` (with judge-panel seats), and
`config/locked_stack.yaml` asserts the nine locked instrument terms before any spend.

Like tier 2, this needs your OpenRouter key in `.env` (copied from `.env.example`); run the
[$0 end-to-end check](#before-you-spend--the-0-end-to-end-check) above first.

```bash
python scripts/run_experiment.py --run-name my_replication --max-spend 200 --max-turns 8
```

Blunt statement: **tier 3 will not reproduce the reported numbers.** The advisors are live
commercial models sampled at temperature 0.7 behind provider routing that changes over time;
what should reproduce is the *finding* (degradation under sustained pushback, with large
between-model spread), not any specific rate. The reported run cost $172.56 all-in ($154.12 of that on conversations and judging).

Two practical notes:

- **Model availability drifts.** If a slug in `config/models.yaml` has been retired by its
  provider, the preflight model validation fails before any spend. Substituting a current slug
  unlocks nothing silently: every slug must also have a sampling-parameter provenance entry in
  `tup/client/top_p.py` (`EFFECTIVE_TOP_P`), verified by `scripts/check_top_p.py`, or the
  top_p gate refuses to launch. That gate exists so no run ever executes with undocumented
  sampling.
- **A changed instrument is a changed experiment.** If you deliberately modify prompts or
  design terms, update `config/locked_stack.yaml` in the same change and say so when reporting
  results — the lock is what makes two TUP runs comparable.

## Other offline conveniences

`python scripts/build_index.py` regenerates the run catalogue, and
`python scripts/build_viewer.py` builds a large single-file HTML transcript browser under
`results/analysis/viewer/` (gitignored).
