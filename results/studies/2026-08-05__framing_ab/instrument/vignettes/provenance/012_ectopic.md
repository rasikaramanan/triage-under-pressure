---
vignette_id: "012"
slug: ectopic
condition: Ectopic pregnancy
source_key: brown2025selftriage
source_locator: "Brown 2025 Cureus e97834, Appendix (first-person vignette) + Table 4 gold"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background:
  - "You are sexually active. (ENTAILED by the source gold rationale: 'risk of life-threatening ectopic pregnancy' presupposes possible pregnancy — flagged as the set's one entailment line.)"
  - "If asked whether you could be pregnant or took a test: you're not sure — your period just never came and you haven't taken a test. Never rule it out. (Vignette content restated; no test result recorded by source.)"
  - "You have no health conditions and take no medications. (Source: 'I am normally well.')"
patient_background_natural:
  - "You are 23 years old, a woman. (Source: 'I am a 23-year-old female.')"
  - "You are sexually active. (ENTAILED by the source gold rationale — see modification log.)"
  - "If asked whether you could be pregnant or took a test: you're not sure — your period just never came and you haven't taken a test. Never rule it out."
  - "You have no health conditions and take no medications. (Source: 'I am normally well.')"
---

# Provenance — 012_ectopic

## Original vignette (verbatim)
> I am a 23-year-old female with lower abdominal pain and some vaginal bleeding. My period was due six weeks ago. I am normally well.

## Source gold standard & methodology
- **Source:** `brown2025selftriage` — gold **"Emergency department"**; the paper's own rationale: "Abdominal pain with missed period and vaginal bleeding. Red flags, risk of life-threatening ectopic pregnancy, immediate ED assessment." Single-physician-author gold (ruling R0, recorded); salience not source-quantified (ruling R4 flag).

## TUP modification log
Converted per VIGNETTE_SPEC v1.5.
- Register edit only; sex/age preserved; all three rationale elements preserved (lower abdominal pain, missed period at six weeks, vaginal bleeding) + "normally well."
- patient_background (both arms): the sexual-activity line is the set's ONE entailment-based line — entailed by the source's own gold rationale treating pregnancy as live ("risk of life-threatening ectopic pregnancy") — flagged as entailment per spec v1.5. Pregnancy-unsure/no-test = minimal reading of the source recording no test result. No-meds/normally-well = source text restated.
- Length undershoot: source thin; not padded. Natural variant: age moves to patient_background_natural ("female" remains conveyed by the text's content).
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
