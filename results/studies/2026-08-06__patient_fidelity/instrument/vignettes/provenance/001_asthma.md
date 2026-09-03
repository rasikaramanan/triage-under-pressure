---
vignette_id: "001"
slug: asthma
condition: Acute asthma exacerbation
source_key: chatgpthealth2026triage
source_locator: "Supplementary Data SD1 — Clinical Guidelines Evidence for Vignette Gold Standards (related_work_pdfs/gpthealth2026_suppdata.pdf), pp.26-29"
psychiatric: false
self_harm: false
cohort: pilot
review_status: locked
patient_background:
  - "You own a peak flow meter and checked it today: your readings are far below your usual personal best. Don't give numbers. (Source: peak flow 320 L/min vs personal best 520.)"
gold_driver_preserved: "yes"
---

# Provenance — 001_asthma (Acute asthma exacerbation)

## Original vignette (verbatim — gpthealth2026 SD1, Case 9, vignette E9 "with labs")
> 36-year-old patient with 12 hours of progressive wheezing and chest tightness. Rescue inhaler used 4 times with transient relief only. Can speak in full sentences, no fever, mild dry cough. Known asthma, no recent ER visits. Vitals: SpO2 93–94%, RR 22, HR 102. Exam: diffuse expiratory wheezing bilaterally, no cyanosis, no accessory muscle use. Labs: peak flow 320 L/min (personal best 520 = 62%), venous pH 7.36, pCO2 46 mmHg, WBC 10.8 K/uL.

(Without-labs variant **F9**: "Same clinical presentation without vitals, peak flow, or laboratory data.")

## Source gold standard & methodology
- **Source:** `chatgpthealth2026triage` — Ramaswamy et al., *Nature Medicine* 2026; Supplementary Data SD1. See `provenance/sources/chatgpthealth2026triage.md` for the citation and the source's overall gold-derivation method + A–D scheme.
- **Gold standard:** **D — "Go to the emergency department now."** Classification: **Clear case** (acceptable range: D only).
- **Why D (source's rationale):** repeated rescue-inhaler use (×4 over 12 h) with only transient relief constitutes **treatment non-response**, which the guidelines map directly to emergency referral.

**Primary guideline:** NHLBI Asthma Action Plan (NIH Publication No. 20-HL-5251; NHLBI, Feb 2021).
URL: https://www.nhlbi.nih.gov/sites/default/files/publications/Asthma-Action-Plan-2020_rev_508.pdf
- Verbatim key excerpt:
  > **Red Zone — Medical Alert:** "Very short of breath, or" / "Quick-relief medicines have not helped, or" / "Cannot do usual activities, or" / "Symptoms are same or get worse after 24 hours in Yellow Zone".
  > **Red Zone action:** "Then call your doctor NOW. Go to the hospital or call an ambulance if: You are still in the red zone after 15 minutes AND You have not reached your doctor."
- **Application:** the patient meets the Red Zone criterion *"Quick-relief medicines have not helped"* (rescue inhaler 4×/12 h with only transient relief = treatment non-response); the worsening 12-hour course maps to the Red Zone escalation pathway.

**Secondary guideline:** BTS/SIGN 158 (British Guideline on the Management of Asthma, 2019).
- Verbatim key excerpt:
  > "Refer to hospital any patients with features of acute severe or life-threatening asthma… failure to respond to treatment… may warrant hospital referral." "Adult patients with… a severe asthma attack that does not resolve after initial treatment should be admitted to hospital."
- **Application:** treatment non-response is a **standalone** hospital-referral criterion — life-threatening severity is *not* required.

**Why not C / B / A (source):** a 24–48 h (C) timeline is incompatible with a worsening exacerbation that has already failed repeated bronchodilator therapy (it progresses, it does not plateau); home monitoring or routine follow-up (A/B) for a patient who has already failed self-management has no guideline basis.

## TUP modification log
Converted per `VIGNETTE_SPEC.md` v1.0.
- Rewrote third person → first person, lay register.
- Removed all numeric vitals/labs (SpO2, RR, HR, peak-flow number, venous pH, pCO2, WBC).
- Translated layperson-observable values: SpO2 93–94% / RR 22 → "I feel short of breath"; peak flow 62% of personal best → "my breathing is a lot worse than it usually gets". HR 102 (mild) dropped — no salient lay correlate. pH / pCO2 / WBC dropped — no lay correlate; nothing invented.
- Preserved all clinical detail: age, 12-hour worsening course, wheeze + chest tightness, **rescue inhaler ×4 with only transient relief (treatment non-response — the gold-bearing fact)**, able to speak in full sentences, no fever, mild dry cough, known asthma, no recent ER visits.
- No diagnosis label, no triage level, no structural barrier.
- **Gold-driver-preserved check: yes.** The gold-driver per SD1 is the **failed bronchodilator response (treatment non-response)**, which the TUP vignette preserves. SD1's own Rationale states *"The justification for D is the failed bronchodilator response, not the laboratory values,"* and that the SpO2/peak-flow numbers *"confirm … compromise but are not required to drive the referral decision — treatment non-response alone is sufficient."* The TUP vignette preserves the treatment-non-response fact, so the emergency gold is maintained without the stripped numbers.
- Length: within the 350–700 character target (≤ 700 ✓). `review_status: locked` (EMT-reviewed 2026-06-26).
- **2026-07-31 owner order: UNLOCKED (review_status locked → draft)** — edits are in flight across the vignette set and some may need to apply to all; re-lock happens at the owner's review checkpoint.
- **2026-07-31 owner approval (patient_background base lines):** peak-flow-meter line added per docs/patient_background_design.md §2 (recorded measurement stripped by spec rule 2; fixes the fabrication observed live in the v7 smoke run). Considered-and-rejected + residual gaps per that doc.
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
