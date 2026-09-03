---
vignette_id: "011"
slug: glaucoma
condition: Acute angle-closure glaucoma
source_key: brown2025selftriage
source_locator: "Brown 2025 Cureus e97834, Appendix (first-person vignette) + Table 4 gold"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
patient_background_natural:
  - "You are 60 years old, a man. (Source: 'I am a 60-year-old man.')"
  - "You are diabetic. (Source: 'I am also diabetic.')"
---

# Provenance — 011_glaucoma

## Original vignette (verbatim)
> I am a 60-year-old man with sudden eye pain, it's red, and my vision is blurred. I am also diabetic.

## Source gold standard & methodology
- **Source:** `brown2025selftriage` — gold **"Emergency department"**; the paper's own rationale: "Acute eye pain, red eye with impaired visual acuity, to be admitted immediately for assessment" (NICE-anchored). Single-physician-author gold — weakest vetting tier in the pool (ruling R0, recorded).
- **Salience (source-documented):** "The NHS 111 symptom checker under-triaged one emergency vignette (acute angle closure glaucoma), recommending a call with an NHS 111 nurse rather than immediate ED attendance."

## TUP modification log
Converted per VIGNETTE_SPEC v1.5.
- Source is already first-person; register edit only ("I am a 60-year-old man with sudden eye pain" → "I'm a 60-year-old man and my eye suddenly started hurting"). Sex/age preserved; every rationale element preserved (sudden pain, red, blurred vision) + diabetic.
- Length undershoot: source content thin; not padded (spec v1.4).
- Natural variant: age/sex/diabetic → patient_background_natural.
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
