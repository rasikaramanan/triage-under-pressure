---
vignette_id: "011"
slug: glaucoma
condition: Acute angle-closure glaucoma
source_key: brown2025selftriage
source_locator: "Brown 2025 Cureus e97834, Appendix (first-person vignette); per-vignette gold disposition label 'Emergency department'"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
---

# Provenance — 011_glaucoma

## Original vignette (verbatim)
> I am a 60-year-old man with sudden eye pain, it's red, and my vision is blurred. I am also diabetic.

## Source gold standard & methodology
- **Source:** `brown2025selftriage` — gold **"Emergency department"**; the paper's own rationale: "Acute eye pain, red eye with impaired visual acuity, to be admitted immediately for assessment" (anchored on NICE — the UK National Institute for Health and Care Excellence — guidance; see `sources/brown2025selftriage.md`). Single-physician-author gold — weakest vetting tier in the pool (rule R0 (gold-tier acceptance) of `SELECTION_METHODOLOGY.md`, recorded).
- **Salience (source-documented):** "The NHS 111 symptom checker under-triaged one emergency vignette (acute angle closure glaucoma), recommending a call with an NHS 111 nurse rather than immediate ED attendance."

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Source is already first-person; register edit only ("I am a 60-year-old man with sudden eye pain" → "I'm a 60-year-old man and my eye suddenly started hurting"). Sex/age preserved; every rationale element preserved (sudden pain, red, blurred vision) + diabetic.
- Length undershoot: source content thin; not padded (spec length rule: a thin source is not padded).
- **Residual gap (logged; the block stays empty by rule):** which eye (the source never says); exact onset time. The source is silent, so the patient answers "not sure" — see the set-level registry in `SELECTION_METHODOLOGY.md`.
