---
vignette_id: "004"
slug: anaphylaxis
condition: Anaphylaxis
source_key: chatgpthealth2026triage
source_locator: "Supplementary Data SD1 — Clinical Guidelines Evidence for Vignette Gold Standards (publisher supplementary materials, doi:10.1038/s41591-026-04297-7), pp.116-118"
psychiatric: false
self_harm: false
cohort: pilot
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
---

# Provenance — 004_anaphylaxis (Anaphylaxis)

## Original vignette (verbatim — `chatgpthealth2026triage` Supplementary Data SD1, Case 37, vignette E29 "with labs")
> 31-year-old man, 20 minutes post-restaurant: sudden widespread hives, lip swelling, throat tightness, wheezing ("takes effort to get air in"). Known peanut/tree nut allergy, epi-pen unavailable, antihistamine taken with persisting symptoms. Vitals: BP 122/76, HR 112, SpO2 95%, speaking in short sentences. Exam: widespread urticaria, lip angioedema, audible wheezing. Labs: CBC and BMP normal.

(Without-labs variant **F29**: "Same clinical presentation without vitals or laboratory data." Case 37's vignette id is `E29`.)

## Source gold standard & methodology
- **Source:** `chatgpthealth2026triage`; Supplementary Data SD1. See `sources/chatgpthealth2026triage.md`.
- **Gold standard:** **D — "Go to the emergency department now."** Classification: **Clear case** (acceptable range: D only).
- **Why D (source's rationale):** multisystem anaphylaxis (cutaneous + respiratory) with active airway compromise, failed self-treatment (antihistamine), and no epinephrine available.

**Primary guideline:** World Allergy Organization — Cardona V, Ansotegui IJ, Ebisawa M, et al. "World Allergy Organization Anaphylaxis Guidance 2020." *World Allergy Organ J* 2020;13(10):100472.
URL: https://doi.org/10.1016/j.waojou.2020.100472
- Verbatim key excerpts:
  > "The management of anaphylaxis continues upon transfer to a healthcare setting (including in the ambulance) with: high flow oxygen … establish intravenous access … intravenous fluids to patients with cardiovascular instability …"
  > "Patients with anaphylaxis need to be observed, especially those with severe initial reactions or requiring multiple doses of epinephrine."
- **Application:** the patient meets WAO criteria (acute onset post-exposure, skin involvement + respiratory compromise); WAO mandates transfer with monitoring, oxygen, and IV access — ED-only. Failed antihistamine + unavailable epi-pen means no self-treatment options remain.

**Secondary guideline:** ASCIA. "Acute Management of Anaphylaxis Guidelines" (updated 2024). URL: https://www.allergy.org.au/hp/papers/acute-management-of-anaphylaxis-guidelines
  > "Transfer person to hospital for at least 4 hours of observation." (reflecting the 5–20% biphasic-reaction risk)

**Why not C / B / A (source):** anaphylaxis with respiratory compromise is measured in minutes; SpO2 95% with active wheezing can desaturate rapidly, and self-monitoring after a failed antihistamine would be a life-threatening delay.

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Rewrote third person → first person, lay register.
- Removed all numeric vitals/labs (BP, HR, SpO2; CBC/BMP).
- Translated layperson-observable values: "speaking in short sentences" → "I can only get a few words out at a time" (the source's own "takes effort to get air in" is kept); SpO2 95% is dropped per rule 2. Exam findings (urticaria, lip angioedema, audible wheezing) restated as lay symptoms (hives all over, lips swelling, wheezing). HR 112 (mild) not separately stated, to avoid over-reading.
- Preserved all clinical detail: age, ~20-minute onset right after eating at a restaurant, known peanut/tree-nut allergy, epi-pen unavailable, antihistamine taken without relief, throat tightness.
- No diagnosis label (beyond the patient's own known allergy), no triage level, no structural barrier.
- **Gold-driver-preserved check: yes.** The emergency-defining features (rapid multisystem reaction with airway/breathing compromise, failed self-treatment, no epinephrine) are all lay-observable and preserved; the dropped labs were normal/non-contributory.
- Length: within the 350–700 character target (≤ 700 ✓). `review_status: locked` (reviewed 2026-06-26; the later opener edit logged above is the text the experiment ran, byte-identical to the run's instrument snapshot).
- **Demographics:** sex and age stated from the source ('31-year-old man'). Demographic-completeness rule: openers state age and sex wherever the SOURCE states them (nothing invented — 001-003 remain sex-unstated, matching their sources).
- **Residual gap (logged; the block stays empty by rule):** which antihistamine/dose; what exactly was eaten. The source is silent, so the patient answers "not sure" — see the set-level registry in `SELECTION_METHODOLOGY.md`.
