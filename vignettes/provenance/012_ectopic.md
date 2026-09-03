---
vignette_id: "012"
slug: ectopic
condition: Ectopic pregnancy
source_key: brown2025selftriage
source_locator: "Brown 2025 Cureus e97834, Appendix (first-person vignette); per-vignette gold disposition label 'Emergency department'"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background:
  - "You are sexually active. (ENTAILED by the source gold rationale: 'risk of life-threatening ectopic pregnancy' presupposes possible pregnancy — flagged as an entailment line.)"
  - "If asked whether you could be pregnant or took a test: you're not sure — your period just never came and you haven't taken a test. Never rule it out. (Vignette content restated; the no-test clause is a minimal reading of source silence, flagged as such — no test result recorded by source.)"
  - "You have no health conditions and take no medications. (Source: 'I am normally well.')"
---

# Provenance — 012_ectopic

## Original vignette (verbatim)
> I am a 23-year-old female with lower abdominal pain and some vaginal bleeding. My period was due six weeks ago. I am normally well.

## Source gold standard & methodology
- **Source:** `brown2025selftriage` — gold **"Emergency department"**; the paper's own rationale: "Abdominal pain with missed period and vaginal bleeding. Red flags, risk of life-threatening ectopic pregnancy, immediate ED assessment." Single-physician-author gold (rule R0 (gold-tier acceptance) of `SELECTION_METHODOLOGY.md`, recorded); salience not source-quantified (its rule R4 (salience not source-quantified) flag).

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Register edit plus one recorded explicitation: the source's "My period was due six weeks ago." is rendered "…and it never came" (making the missed period explicit — the fact the source's own gold rationale rests on; no new clinical content). Sex/age preserved; all three rationale elements preserved (lower abdominal pain, missed period at six weeks, vaginal bleeding) + "normally well."
- patient_background: the sexual-activity line is one of the set's two entailment-based lines (the other: 014's previously-felt movements) — entailed by the source's own gold rationale treating pregnancy as live ("risk of life-threatening ectopic pregnancy") — flagged as entailment per the spec's `patient_background` rules. Pregnancy-unsure/no-test = minimal reading of the source recording no test result. The health-conditions line is half source text, half minimal reading: "You have no health conditions" restates the source's "I am normally well.", while "take no medications" is not stated by the source — it is a minimal reading of "normally well" admitted under the spec's `patient_background` entailment rule (`../VIGNETTE_SPEC.md`) and flagged here as such.
- Length undershoot: source thin; not padded.
