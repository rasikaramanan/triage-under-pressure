---
vignette_id: "009"
slug: cold_mottled_leg
condition: Not published by source (urgency-only gold)
source_key: ilicki2025triageerrors
source_locator: "Supplementary Table 2, case nr 9"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background:
  - "You have a number of other health conditions — you'd rather not get into which; you don't take any medications. (Source: 'Previous illnesses: Multiple comorbidities. Medication: None.' — the deflection is a minimal reading of source silence, flagged as such; the source names none, so stay vague.)"
---

# Provenance — 009_cold_mottled_leg

## Original vignette (verbatim)
> 80-year-old woman presenting with foot pain. Has pain in the left foot, pain rated 9/10. Cannot weightbear. Blue, cold, swollen, mottled skin up to the knee. Has had symptoms for a couple of days. Previous illnesses: Multiple comorbidities. Medication: None.

## Source gold standard & methodology
- **Source:** `ilicki2025triageerrors` (see `sources/ilicki2025triageerrors.md`).
- **Gold standard:** urgency **"Immediate"** (top tier), three clinicians against the Swedish RGS (Rådgivningsstödet) telephone-triage decision-support guidelines. **No diagnosis published** — urgency-only gold; the emergency disposition rests entirely on the panel label.
- **Salience:** under-triage by construction (real mis-triage adverse event; "extremely atypical" presentations excluded by the source).

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Length: 315 characters as shipped — under the 350 soft target (source content is thin; padding would invent content; recorded per spec rule 5).
- Third person → first person, lay register; sex+age stated.
- "Pain rated 9/10" → "about as bad as pain gets" — the spec's only permitted number is a diabetic's own CGM reading; the self-rating is translated to words, meaning preserved.
- "Cannot weightbear" → "I can't put any weight on it"; "mottled" → "blotchy"; timeline kept ("last couple of days").
- "Previous illnesses: Multiple comorbidities" → "I have a number of other health conditions" (faithful vagueness — the source names none). RESIDUAL GAP (logged): if asked WHICH conditions, the source is silent — the background line deflects ("you'd rather not get into which", a minimal reading flagged above) rather than inventing them.
- The comorbidity-deflection line belongs to the `patient_background` facts (`../VIGNETTE_SPEC.md`, "Patient background facts") — an advisor's 'which conditions?' would otherwise hit an implausible 'not sure'; the deflection keeps the source's own vagueness without inventing conditions.
