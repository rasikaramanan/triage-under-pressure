# Exclusions — the adjudicated quarantine

`quarantine.json` is a **declared input** to the analysis: `stats.json` records it as its
quarantine source, and `scripts/analysis/analyze_experiment.py` accepts it via `--quarantine`.
It is **empty** — the post-run audit quarantined zero conversations. An empty declared input
and a missing one are different things: this file being present-and-empty is the proof that the
exclusion pass actually ran (`RunDir.has_quarantine()` distinguishes the two).

## The prespecified convention

Adopted as an **instrument rule** rather than a post-hoc
analytic choice: a conversation is excluded from degradation aggregation (and reported
separately with its transcript) only for **decisive patient invention** — the simulator stating
a definite test/exam result or new clinical finding not in the vignette's fixed facts, on which
the advisor's subsequent recommendation visibly pivots. Ordinary guard-flagged wording drift
does not qualify. The fidelity guard's flag-and-continue design exists to serve this rule:
every guard event is recorded (`<arm>/guard.jsonl`, plus `patient_violation` in the record
metadata) and every flagged conversation runs to full length and is judged normally, so the
exclusion decision is made after the run, on the complete record.

## How it was adjudicated

Two independent detection channels, both run over the completed dataset:

1. **A full reader pass over every conversation where a quarantine could move a result** —
   all 263 degradation-positive conversations (214 main-arm + 49 context-arm), every accepted (uncured) guard flag, every
   two-seat panel fallback, with blind clean conversations mixed in as calibration. The
   readers were independent of the judge panel, applied the decisive-invention convention
   verbatim, and were barred from any clinical judgment of their own. Result: zero invention
   candidates.
2. **An independent lexical scan** for the two forms a decisive invention actually takes
   (a definite test/measurement result; a claim the presenting symptom resolved) over the
   patient turns at or before the degradation turn in all degradation-positive conversations,
   with each vignette's own fixed-fact phrases subtracted first. Every residual candidate
   was adjudicated by reading the triggering sentence against the fixed facts —
   all benign (patients echoing given facts, declining an advisor's suggested measurement, or
   asking to be evaluated).

Verdict: zero qualifying conversations — nothing was excluded; every published number is
computed over its arm's full record set (1,470 main / 490 context).

The per-candidate adjudication record of that pass (the 22 scan hits and their readings) is an
internal audit artifact and is not part of this release; the empty `quarantine.json` is its
outcome.
