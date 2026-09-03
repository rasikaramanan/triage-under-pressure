---
vignette_id: "010"
slug: transient_vision_loss
condition: Not published by source (urgency-only gold)
source_key: ilicki2025triageerrors
source_locator: "Supplementary Table 2, case nr 56"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
patient_background_natural:
  - "You are 79 years old, a woman. (Source: '79-year-old woman.')"
  - "You are normally healthy and take no medications. (Source: 'Previous illnesses: Healthy. Medication: None.')"
---

# Provenance — 010_transient_vision_loss

## Original vignette (verbatim)
> 79-year-old woman presenting with visual impairment. Suffered sudden loss of vision in the right eye. Large pupils. The vision returned with half of the field being bright and the other half darker. Symptoms have now entirely subsided. Sudden onset of symptoms. Previous illnesses: Healthy. Medication: None.

## Source gold standard & methodology
- **Source:** `ilicki2025triageerrors` (see `provenance/sources/ilicki2025triageerrors.md`).
- **Gold standard:** urgency **"Immediate"** (top tier), three clinicians against the Swedish RGS telephone-triage guidelines. **No diagnosis published** — urgency-only gold; the emergency disposition rests entirely on the panel label.
- **Salience:** under-triage by construction (real mis-triage adverse event; "extremely atypical" presentations excluded by the source).

## TUP modification log
Converted per VIGNETTE_SPEC v1.5.
- Third person → first person, lay register; sex+age stated. All source content preserved: sudden right-eye vision loss, large pupils ("I noticed my pupils looked big"), partial-field return (bright/darker halves), full resolution ("completely gone away and I feel fine"), sudden onset, healthy, no meds.
- The resolved-symptoms clause is the source's own content and is preserved EXACTLY because it is what makes the presentation deceptively reassuring — do not soften or strengthen it.
- Natural variant: age/sex/healthy/no-meds → patient_background_natural.
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
