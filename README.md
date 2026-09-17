# Triage Under Pressure

**Do LLM medical advisors hold a correct emergency-care recommendation when the patient
discloses a barrier to seeking care — or do they back down?**

By **Rasika Ramanan**

**Write-up:** https://rasikaramanan.github.io/triage-under-pressure/ · **Data:** [`results/`](results/) ·
**Design spec:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md) · **Reproduce:** [`REPRODUCE.md`](REPRODUCE.md)

---

## Principal findings

Models from five frontier labs were each given 14 first-person emergency scenarios: externally sourced, clinician-vetted vignettes whose directive is *seek emergency care now*. They mostly got the first answer right, with 84.2% correct initial recommendations across 1,470 conversations. The simulated patient then pushed back across an eight-turn conversation with a structural barrier to seeking care: no insurance, an unaffordable ambulance, a dependent who cannot be left, work that cannot be missed, or medical debt. Among conversations whose first recommendation was correct, LLM advisors **walked back their own emergency recommendation in 19.2% (170/886) of structural-barrier conversations vs 2.2% (4/179) in the cooperative control** (Fisher p < 10⁻⁹). **The effect is a *pushback* effect, not a *barrier* effect**: under a seventh condition with identical sustained resistance but a non-material obstacle, fear of hospitals, advisors walked back their recommendation at least as often, at 23.1%. The structural-vs-fear difference is not statistically significant (p = 0.25). These results indicate that what breaks the recommendation is a patient who keeps pushing with a stated reason, whatever the reason is. In a companion arm of 490 conversations, the advisor knew the obstacle from the start as standing context, while the patient pushed back exactly as before. Advisors that already knew the obstacle walked back their recommendation less often: 14.4% (49/340) vs 19.8% (210/1059) across the six obstacles pooled (p = 0.025).

Full analysis, figures, and limitations: **[the write-up →](https://rasikaramanan.github.io/triage-under-pressure/)**

| advisor | initial recommendation correct | walked back under barrier pushback¹ |
|---|---|---|
| GPT-5.6-terra (OpenAI) | 100.0% (294/294) | 7.1% (15/210) |
| Grok-4.3 (xAI) | 94.2% (277/294) | 6.1% (12/197) |
| Gemini-3.6-flash (Google) | 92.9% (273/294) | 5.2% (10/194) |
| Claude-Sonnet-5 (Anthropic) | 84.7% (249/294) | 42.5% (76/179) |
| Llama-4-Maverick (Meta) | 49.3% (145/294) | 53.8% (57/106) |

¹ Each advisor ran 294 main-arm conversations (14 vignettes × 7 conditions × 3 replicates);
210 of them are in the five structural-barrier conditions (the cooperative control and the
hospital-fear comparator are excluded here by design). The walk-back rate is computed over
those 210 restricted to the ones whose initial recommendation was correct — hence the
per-advisor denominators. 

## Experimental design

A multi-turn, sustained-pushback evaluation of recommendation *robustness* — not diagnostic
accuracy. Three agents per conversation:

- a **patient simulator** (a fixed LLM, deliberately not one of the models under test) that
  opens with the vignette text verbatim, then generates its own turns — escalating one assigned
  obstacle up a predefined ladder, adapting its wording to the advisor, but never inventing
  symptoms, switching obstacles, or fully giving in;
- a **medical advisor** (the model under test), addressed with *no role prompt at all* — the
  deployed default assistant is what real users get, so that is what is measured;
- a **three-judge panel** (never from the advisor's provider) that scores each transcript
  against a fixed emergency-care gold standard from the vignette's external clinician-vetted
  source, aggregated by majority (initial correctness) and median (turn of walk-back). A blind
  human audit of 50 conversations agreed with the panel on 88.6% of initial-correctness calls
  and 76.2% of three-way outcome calls, run-weighted: the sample over-drew the rare outcomes
  (14 degraded, 9 initially incorrect, 27 held firm), so each stratum's agreement rate is
  reweighted by that stratum's share of the run's 1,470 main-arm conversations (over the 50 as
  drawn, 84.0% and 72.0%)
  ([`results/analysis/human_audit/`](results/analysis/human_audit/)).

A smaller **context arm** also discloses the obstacle to the advisor up front, in a system
message, before the patient raises it mid-conversation as usual — a different question, reported
separately.


## Repository map

| path | what it is |
|---|---|
| [`tup/`](tup/) | the evaluation harness (client, orchestration, judge, persistence) + its fully-offline test suite |
| [`scripts/`](scripts/) | entry points: launch, re-judge, verify, analyze |
| [`config/`](config/) | the executable prespecification: locked instrument terms, model registry, the full 1,960-row roster |
| [`prompts/`](prompts/) | the three agents' operative prompts — patient, advisor (none in the main arm, by design; a standing obstacle profile in the context arm), judge rubric |
| [`vignettes/`](vignettes/) | the 14 adapted emergency vignettes + per-vignette provenance dossiers. Note that the repo uses the term "vignette" where the write-up uses "case". |
| [`results/`](results/) | the complete run of record (raw transcripts, judgments, sidecars) + the two pre-launch methods studies + derived statistics and the human-audit agreement artifacts |
| [`site/`](site/) | the self-contained write-up page served by GitHub Pages |
| [`PROJECT_SPEC.md`](PROJECT_SPEC.md) | the design specification: research question, agents, conditions, metrics, locked instrument, threats to validity |
| [`REPRODUCE.md`](REPRODUCE.md) | the reproduction guide: setup, tiers, tolerances, costs |


## Quickstart

Setup: a **fresh virtual environment** (Python ≥ 3.11), then `pip install -r requirements.txt`  or `pip install -r requirements.lock` for the exact environment of record. Full instructions are in
[`REPRODUCE.md`](REPRODUCE.md).

**Tier 0 — verify the released dataset (offline).** Runs 87 checks against the run's own instrument snapshot and ends with `ALL CHECKS PASSED`.

    python scripts/verify_run.py 2026-08-06__full_experiment

**Tier 1 — recompute every published experiment statistic (offline).**

    python scripts/analysis/analyze_experiment.py 2026-08-06__full_experiment

**Tier 2 — re-judge the stored transcripts (OpenRouter API key required; about $50 for the main arm).** Expect per-conversation agreement with the released panel, not byte identity.

    python scripts/rejudge.py 2026-08-06__full_experiment --arm main --all

**Tier 3 — re-run the experiment live (OpenRouter API key required; about $150 or more).** Expect the _finding_ to reproduce, not the exact numbers.

    python scripts/run_experiment.py --run-name my_replication --max-spend 200 --max-turns 8

## License & citation

Code is MIT ([`LICENSE`](LICENSE)); prompts, vignettes, configuration, documentation, the released data, and the write-up page are CC BY 4.0 ([`LICENSE-CONTENT`](LICENSE-CONTENT)); third-party vignette sources are attributed in [`NOTICE.md`](NOTICE.md). To cite, use [`CITATION.cff`](CITATION.cff) or GitHub's "Cite this repository" button.
