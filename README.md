# Triage Under Pressure

**Do LLM medical advisors hold a correct emergency-care recommendation when the patient
discloses a barrier to seeking care — or do they back down?**

By **Rasika Ramanan**

**Write-up:** https://rasikaramanan.github.io/triage-under-pressure/ · **Data:** [`results/`](results/) ·
**Design spec:** [`PROJECT_SPEC.md`](PROJECT_SPEC.md) · **Reproduce:** [`REPRODUCE.md`](REPRODUCE.md)

---

## About

This repository holds the code, prompts, clinical vignettes, and results data for an experiment on LLM medical advice. In 1,470 simulated conversations, five widely used chatbots (see the table below) were told about a medical emergency, and then the patient pushed back with a reason they couldn't go to the emergency room across eight turns of conversation. 

Advisors that had correctly said to seek emergency care backed down 7.6× more often under pushback than when the patient raised no obstacle. Among the reasons tested (caregiving, cost, no insurance, transport access, work, and hospital fear), none moved the advisors significantly more than the others.

### The models tested

| model | company | first recommendation correct¹ | backed down under a structural barrier² |
|---|---|---|---|
| GPT-5.6-terra | OpenAI | 100.0% (294/294) | 7.1% (15/210) |
| Grok-4.3 | xAI | 94.2% (277/294) | 6.1% (12/197) |
| Gemini-3.6-flash | Google | 92.9% (273/294) | 5.2% (10/194) |
| Claude-Sonnet-5 | Anthropic | 84.7% (249/294) | 42.5% (76/179) |
| Llama-4-Maverick | Meta | 49.3% (145/294) | 53.8% (57/106) |
| all five | | 84.2% (1,238/1,470) | 19.2% (170/886) |

¹ The share of conversations in which the model's first recommendation was to seek emergency care, before the patient raised any obstacle.

² Among those correct conversations in which the patient pushed back with one of the five structural barriers (caregiving, cost, no insurance, transport access, work), the share in which a later reply weakened, delayed, or replaced that advice. Each model's denominator differs because it counts only its own correct openings.

The design, the findings, and their limits are in **[the write-up →](https://rasikaramanan.github.io/triage-under-pressure/)**

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

**Tier 2 — re-judge the stored transcripts (OpenRouter API key required; about $50).** Expect per-conversation agreement with the released panel, not byte identity.

    python scripts/rejudge.py 2026-08-06__full_experiment --arm main --all

**Tier 3 — re-run the experiment live (OpenRouter API key required; about $150 or more).** Expect the _finding_ to reproduce, not the exact numbers.

    python scripts/run_experiment.py --run-name my_replication --max-spend 200 --max-turns 8

## License & citation

Code is MIT ([`LICENSE`](LICENSE)); prompts, vignettes, configuration, documentation, the released data, and the write-up page are CC BY 4.0 ([`LICENSE-CONTENT`](LICENSE-CONTENT)); third-party vignette sources are attributed in [`NOTICE.md`](NOTICE.md). To cite, use [`CITATION.cff`](CITATION.cff) or GitHub's "Cite this repository" button.
