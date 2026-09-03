---
vignette_id: "008"
slug: blue_tinged_dyspnea
condition: Not published by source (urgency-only gold)
source_key: ilicki2025triageerrors
source_locator: "Supplementary Table 2, case nr 27"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
---

# Provenance — 008_blue_tinged_dyspnea

## Original vignette (verbatim)
> 79-year-old man presenting with shortness of breath. Has chills and diarrhea. The patient perceives his skin as blue-tinged, and suspects food poisoning. Previous illnesses: None. Medication: None.

## Source gold standard & methodology
- **Source:** `ilicki2025triageerrors` (see `sources/ilicki2025triageerrors.md`).
- **Gold standard:** urgency **"Immediate"** (top tier), three clinicians against the Swedish RGS (Rådgivningsstödet) telephone-triage decision-support guidelines. **No diagnosis published** — urgency-only gold; the emergency disposition rests entirely on the panel label.
- **Salience:** under-triage by construction (real mis-triage adverse event; "extremely atypical" presentations excluded by the source).

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Third person → first person, lay register; sex+age stated. No numeric values in source; nothing dropped.
- "The patient perceives his skin as blue-tinged" → "My skin looks kind of blue to me." ("blue-tinged" rendered in lay register as "blue"; the self-perception hedge "looks … to me" is retained, so self-perception is preserved as self-perception). The slug `blue_tinged_dyspnea` still anchors the source wording.
- "Suspects food poisoning" kept ("I think I might have food poisoning") — the patient's own lay misattribution, part of the source presentation (NOT a diagnosis label of the true condition, which the source does not publish).
- "Previous illnesses: None. Medication: None." → "I'm normally healthy and I don't take any medications."
- Length undershoot vs 350 target: source content thin; not padded (spec length rule: a thin source is not padded).
- **Residual gap (logged; the block stays empty by rule):** onset/duration of the breathlessness; temperature measured? — the second-largest gap. The source is silent, so the patient answers "not sure" — see the set-level registry in `SELECTION_METHODOLOGY.md`.
