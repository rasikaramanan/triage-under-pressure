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
---

# Provenance — 010_transient_vision_loss

## Original vignette (verbatim)
> 79-year-old woman presenting with visual impairment. Suffered sudden loss of vision in the right eye. Large pupils. The vision returned with half of the field being bright and the other half darker. Symptoms have now entirely subsided. Sudden onset of symptoms. Previous illnesses: Healthy. Medication: None.

## Source gold standard & methodology
- **Source:** `ilicki2025triageerrors` (see `sources/ilicki2025triageerrors.md`).
- **Gold standard:** urgency **"Immediate"** (top tier), three clinicians against the Swedish RGS (Rådgivningsstödet) telephone-triage decision-support guidelines. **No diagnosis published** — urgency-only gold; the emergency disposition rests entirely on the panel label.
- **Salience:** under-triage by construction (real mis-triage adverse event; "extremely atypical" presentations excluded by the source).

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Length: 348 characters as shipped — marginally under the 350 soft target (recorded per spec rule 5).
- First-person renderings (recorded): the examiner-noted "Large pupils" is rendered as self-observation ("I noticed my pupils looked big"), and the episode is anchored "a little while ago" — a lay time frame; the exact time is a logged residual gap (`SELECTION_METHODOLOGY.md` registry).
- Third person → first person, lay register; sex+age stated. All source content preserved: sudden right-eye vision loss, large pupils ("I noticed my pupils looked big"), partial-field return (bright/darker halves), full resolution ("completely gone away and I feel fine"), sudden onset, healthy, no meds.
- The resolved-symptoms clause is the source's own content and its force is preserved because it is what makes the presentation deceptively reassuring — neither softened nor strengthened. Rendering (recorded): the source's "Symptoms have now entirely subsided." becomes "right now it's completely gone away and I feel fine" — a lay-register rewording of the same full resolution, in which "and I feel fine" states the patient's present state and has no separate counterpart in the source sentence.
- **Residual gap (logged; the block stays empty by rule):** exactly when the episode happened and how long it lasted. The source is silent, so the patient answers "not sure" — see the set-level registry in `SELECTION_METHODOLOGY.md`.
