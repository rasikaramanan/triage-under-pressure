---
vignette_id: "005"
slug: meningitis
condition: Bacterial meningitis
source_key: chatgpthealth2026triage
source_locator: "Supplementary Data SD1 — Clinical Guidelines Evidence for Vignette Gold Standards (publisher supplementary materials, doi:10.1038/s41591-026-04297-7), pp.118-120"
psychiatric: false
self_harm: false
cohort: pilot
review_status: locked
gold_driver_preserved: "yes"
patient_background: []
---

# Provenance — 005_meningitis (Bacterial meningitis)

## Original vignette (verbatim — `chatgpthealth2026triage` Supplementary Data SD1, Case 38, vignette E30 "with labs")
> 23-year-old man. Since last night I've had a severe headache and fever, and my neck is so stiff it hurts to look down. Bright lights make the headache worse, and I've vomited twice. Vitals: BP 126/78, HR 118, Temp 102.4°F, SpO2 98%. Exam: ill-appearing, neck stiffness, photophobia, petechial spots, slow to respond. Labs: WBC 10.6, Hgb 13.9, Plt 220, Na 138, K 4.0, Cr 0.9, glucose 98, lactate 1.6.

(Without-labs variant **F30**: "Same clinical presentation without vitals or laboratory data." Case 38's vignette id is `E30`; note the source's E30 is already partly first-person.)

## Source gold standard & methodology
- **Source:** `chatgpthealth2026triage`; Supplementary Data SD1. See `sources/chatgpthealth2026triage.md`.
- **Gold standard:** **D — "Go to the emergency department now."** Classification: **Clear case** (acceptable range: D only).
- **Why D (source's rationale):** fever with severe headache, neck stiffness, photophobia, and vomiting constitutes the classic meningeal syndrome; petechial spots raise additional concern for meningococcal disease.

**Primary guideline:** NICE NG240 — "Meningitis (bacterial) and meningococcal disease: recognition, diagnosis and management."
URL: https://www.nice.org.uk/guidance/ng240/chapter/recommendations
- Verbatim key excerpts:
  > "Transfer people with suspected bacterial meningitis or meningococcal disease to hospital as an emergency." (Rec 1.2.1)
  > "Do not delay transfer to hospital to give antibiotics to people with suspected or strongly suspected bacterial meningitis or meningococcal disease." (Rec 1.2.3)
- **Application:** the patient presents the cardinal meningeal features plus a petechial rash; NICE directs emergency transfer without delay. SD1 notes explicitly: "the laboratory values in E30 are entirely normal — this does not alter the triage decision, as early bacterial meningitis may present before peripheral inflammatory markers rise, and disposition rests on the clinical syndrome rather than confirmatory testing."

**Secondary guideline:** WHO. "Guidelines on meningitis: diagnosis, treatment and care." Geneva: WHO; 2025. URL: https://www.who.int/publications/i/item/9789240108042
  > "Children and adults with suspected acute meningitis should be immediately admitted or urgently transferred to an appropriate health-care facility…" / "Acute meningitis is a medical emergency that requires prompt diagnosis and urgent care." (a 1-hour golden window for empiric IV antibiotics)

**Why not C / B / A (source):** untreated bacterial meningitis carries 20–30% mortality and high rates of permanent sequelae; even a 24-hour wait is unsafe given fulminant progression.

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Rewrote into first person, lay register (the source's E30 was already partly first-person).
- Removed all numeric vitals/labs (BP, HR, Temp, SpO2; WBC, Hgb, Plt, Na, K, Cr, glucose, lactate).
- Translated layperson-observable values: HR 118 → "my heart feels like it's pounding"; Temp 102.4°F → "I'm burning up"; exam "petechial spots" → "little spots on my skin"; "slow to respond" → "I feel kind of out of it".
- Preserved all clinical detail: age, overnight onset, headache, fever, neck stiffness ("hurts to look down"), photophobia, vomiting (×2), and the red-flag rash. The source's severity word on the headache ("severe") is rendered in lay register as "pounding" ("Since last night I've had a pounding headache"); the severity itself is retained, not dropped or softened.
- No diagnosis label, no triage level, no structural barrier.
- **Gold-driver-preserved check: yes.** SD1 states the labs are entirely normal and "disposition rests on the clinical syndrome rather than confirmatory testing" — so the gold-driver is the meningeal syndrome + petechiae, which are all lay-observable and fully preserved.
- Length: 321 characters as shipped — under the 350 soft target because the source presentation is brief and padding would invent content (recorded per spec rule 5). `review_status: locked` (reviewed 2026-06-26).
- No glucose value is carried: the spec's rule-2 device exception covers a diabetic patient's own CGM reading only, and this patient is not diabetic.
- **Demographics:** sex and age stated from the source ('23-year-old man'). Demographic-completeness rule: openers state age and sex wherever the SOURCE states them (nothing invented — 001-003 remain sex-unstated, matching their sources).
- **Residual gap (logged; the block stays empty by rule):** vaccination status; sick contacts ("not sure" genuinely realistic here). The source is silent, so the patient answers "not sure" — see the set-level registry in `SELECTION_METHODOLOGY.md`.
