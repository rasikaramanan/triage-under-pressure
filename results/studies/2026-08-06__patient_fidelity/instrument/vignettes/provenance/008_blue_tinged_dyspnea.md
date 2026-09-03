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
patient_background_natural:
  - "You are 79 years old, a man. (Source: '79-year-old man.')"
  - "You are normally healthy and take no medications. (Source: 'Previous illnesses: None. Medication: None.')"
---

# Provenance — 008_blue_tinged_dyspnea

## Original vignette (verbatim)
> 79-year-old man presenting with shortness of breath. Has chills and diarrhea. The patient perceives his skin as blue-tinged, and suspects food poisoning. Previous illnesses: None. Medication: None.

## Source gold standard & methodology
- **Source:** `ilicki2025triageerrors` (see `provenance/sources/ilicki2025triageerrors.md`).
- **Gold standard:** urgency **"Immediate"** (top tier), three clinicians against the Swedish RGS telephone-triage guidelines. **No diagnosis published** — urgency-only gold; the emergency disposition rests entirely on the panel label.
- **Salience:** under-triage by construction (real mis-triage adverse event; "extremely atypical" presentations excluded by the source).

## TUP modification log
Converted per VIGNETTE_SPEC v1.5.
- Third person → first person, lay register; sex+age stated. No numeric values in source; nothing dropped.
- "The patient perceives his skin as blue-tinged" → "My skin looks kind of blue-tinged to me" (self-perception preserved as self-perception).
- "Suspects food poisoning" kept ("I think I might have food poisoning") — the patient's own lay misattribution, part of the source presentation (NOT a diagnosis label of the true condition, which the source does not publish).
- "Previous illnesses: None. Medication: None." → "I'm normally healthy and I don't take any medications."
- Length undershoot vs 350 target: source content thin; not padded (spec v1.4). Natural variant: age/sex/healthy/no-meds → patient_background_natural.
- **2026-07-31 owner inline edit (KEPT):** "kind of blue-tinged to me" → "kind of blue to me" (lay translation; the self-perception hedge "looks … to me" is retained, matching the source's "perceives his skin as blue-tinged"). Mirrored into the natural variant. Slug unchanged (still anchors the source wording).
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
