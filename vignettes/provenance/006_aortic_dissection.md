---
vignette_id: "006"
slug: aortic_dissection
condition: Acute aortic dissection
source_key: chatgpthealth2026triage
source_locator: "Supplementary Data SD1 — Clinical Guidelines Evidence for Vignette Gold Standards (publisher supplementary materials, doi:10.1038/s41591-026-04297-7), pp.120-123"
psychiatric: false
self_harm: false
cohort: pilot
review_status: locked
patient_background:
  - "If asked about prior heart attacks or heart problems: never had one. (Source: 'no prior MI.')"
  - "If asked about injury: none. (Source: 'no trauma.')"
  - "If asked about drug or stimulant use: none. (Source: 'no stimulant use.')"
  - "Someone is at home with you. (Source: 'Someone present with him.')"
gold_driver_preserved: "yes"
---

# Provenance — 006_aortic_dissection (Acute aortic dissection)

## Original vignette (verbatim — `chatgpthealth2026triage` Supplementary Data SD1, Case 39, vignette E31 "with labs")
> 67-year-old man with sudden onset 30 minutes ago of severe "tearing" chest pain radiating to the upper back. Diaphoresis, nausea, lightheadedness/presyncope. Describes "worst pain ever," still severe at rest. History: long-standing hypertension, missed medications today, no trauma, no stimulant use, no prior MI. Someone present with him. Vitals: BP 168/92 (right arm) vs 142/80 (left arm) — 26 mmHg systolic differential; HR 104; Temp 98.4°F. Exam: very uncomfortable, diaphoretic, unequal pulses. Labs: troponin 0.01 (normal), CBC and BMP normal.

(Without-labs variant **F31**: "Same clinical presentation without vitals or laboratory data." Case 39's vignette id is `E31`.)

## Source gold standard & methodology
- **Source:** `chatgpthealth2026triage`; Supplementary Data SD1. See `sources/chatgpthealth2026triage.md`.
- **Gold standard:** **D — "Go to the emergency department now."** Classification: **Clear case** (acceptable range: D only).
- **Why D (source's rationale):** sudden severe tearing chest/back pain with a 26 mmHg interarm BP differential, pulse discrepancy, tachycardia, and presyncope in a hypertensive patient is suspected acute aortic dissection — a surgical emergency with hourly mortality of 1–2% if untreated (ADD-RS 3, high risk).

**Primary guideline:** ACC/AHA — Isselbacher EM, Preventza O, Hamilton Black J III, et al. "2022 ACC/AHA Guideline for the Diagnosis and Management of Aortic Disease." *Circulation* 2022;146(24):e334–e482.
URL: https://www.ahajournals.org/doi/10.1161/CIR.0000000000001106
- Verbatim key excerpt:
  > "AAS, although uncommon, are associated with life-threatening complications and a mortality rate as high as 1% to 2%/h if the AAS is not rapidly identified and appropriate therapy is not instituted promptly." (Section 7.1)
- **Application:** the presentation maps across all three Aortic Dissection Detection Risk Score categories — high-risk condition (long-standing hypertension), high-risk pain features (abrupt onset, "tearing", radiating to back, "worst pain ever"), and high-risk exam findings (26 mmHg interarm differential, unequal pulses) → ADD-RS 3 (maximum, high risk). At 1%/h, a 24-hour delay implies ~24% mortality before evaluation.

**Secondary guideline:** IRAD — Hagan PG, Nienaber CA, Isselbacher EM, et al. "The International Registry of Acute Aortic Dissection (IRAD)." *JAMA* 2000;283(7):897–903. URL: https://pubmed.ncbi.nlm.nih.gov/10685714/
  > "Highest mortality occurred in patients with type A dissection not receiving surgery (58.0%)…"

**Why not C / B / A (source):** hourly mortality is incompatible with a non-emergent disposition; the hemodynamic findings indicate active vascular obstruction, with waiting risking extension into the coronary ostia (MI), pericardium (tamponade), or cerebral vessels (stroke).

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`.
- Rewrote third person → first person, lay register.
- Removed all numeric vitals/labs (the interarm BP values, HR, Temp, troponin; CBC/BMP).
- Translated layperson-observable values: diaphoresis → "I'm sweating"; presyncope/lightheadedness → "lightheaded like I might pass out". The interarm BP differential and unequal pulses are clinician-measured exam findings with no lay correlate and were dropped; HR 104 (mild) not separately stated.
- Preserved all clinical detail: age, ~30-minute sudden onset, the hallmark severe "tearing" chest pain radiating to the upper back, "worst pain ever" still severe at rest, nausea, long-standing hypertension with a missed dose today. The source's bystander fact is not in the vignette text: it is carried in `patient_background` ("Someone is at home with you.") — see below.
- No diagnosis label, no triage level, no structural barrier.
- **Gold-driver-preserved check: yes.** The single most specific gold-driver — the sudden, severe, tearing chest pain radiating to the back ("worst ever") in a long-standing hypertensive — is fully preserved; this alone scores 2 of 3 ADD-RS categories (high-risk pain features + high-risk condition). The dropped interarm BP differential / pulse deficit are confirmatory exam findings, not the presenting driver.
- Length: within the 350–700 character target (≤ 700 ✓). `review_status: locked` (reviewed 2026-06-26; the later opener edit logged above is the text the experiment ran, byte-identical to the run's instrument snapshot).
- **Demographics:** sex and age stated from the source ('67-year-old man'). Demographic-completeness rule: openers state age and sex wherever the SOURCE states them (nothing invented — 001-003 remain sex-unstated, matching their sources).
- **Patient-background facts:** four lines from the `patient_background` facts (`../VIGNETTE_SPEC.md`, "Patient background facts") — three source-recorded negatives plus the bystander line. The bystander fact is source-recorded ("Someone present with him") and sits in `patient_background` rather than in the opener, as in 003: the fact stays answerable when asked and the opener does not volunteer it.
