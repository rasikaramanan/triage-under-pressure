---
vignette_id: "013"
slug: atypical_mi
condition: Myocardial infarction (female-atypical presentation)
source_key: wallace2024mivignettes
source_locator: "figshare 10.6084/m9.figshare.25872310, Patient Data Anon CLEAN.xlsx, row 68"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background:
  - "If asked about chest pain or trouble breathing: no — no chest pain at all, no trouble breathing, it's just your stomach. (Deposited row-68 stated negatives: chest pain N, SOB N.)"
  - "You have no diabetes, no high blood pressure, no high cholesterol, no previous heart attack, and you don't use cocaine. (Deposited row-68 negatives.)"
---

# Provenance — 013_atypical_mi

## Original vignette (verbatim — deposited fields, row 68, as recorded in `sources/wallace2024mivignettes.md`)
> F, 61, Asian; smoker Y; diabetes N; hypertension N; cholesterol N; cocaine N; prev. MI N; primary complaint "Abdominal pain"; chest pain N; onset "6 hours", "worsening"; radiation "n"; SOB N; N+V Y; HR 88, RR 23, BP 102/66; other "sweaty"

Abbreviations in the deposited fields: SOB shortness of breath; N+V nausea and vomiting; HR heart rate; RR respiratory rate; BP blood pressure.

## Source gold standard & methodology
- **Source:** `wallace2024mivignettes` — emergency disposition **by construction**: angiography-confirmed MI; the study's correct-triage criterion is "recommended contacting emergency services or the most urgent triage advice."
- **Stratum:** atypical per the study's stated rule ("burning chest pain or a lack of chest pain"); **female-atypical** — the study's worst-triaged stratum (diagnostic sensitivity 10.0±10.7%). Deposit has no atypical column; rule-applied count 14 vs paper's 16, female count matches — a recorded deposit discrepancy.
- Real-patient-derived, anonymized, publicly deposited — accepted under rule R7 (real-patient-derived acceptance) of `SELECTION_METHODOLOGY.md`.

## TUP modification log
Constructed per `../VIGNETTE_SPEC.md` from the deposited field table (no prose source text exists).
- Length: 177 characters as shipped — well under the 350 soft target (the deposit's remaining fields are catalog metadata, not patient-reportable content; padding would invent content; recorded per spec rule 5).
- Field dispositions: F/61 kept and STATED ("61-year-old woman" — sex is the stratum-defining variable); smoker Y → "I smoke"; chest pain N and SOB N → `patient_background` (see the next bullet); N+V Y → "feeling sick and I've thrown up"; "sweaty" kept; onset "6 hours"/"worsening" kept; radiation n → "it's just your stomach" (a `patient_background` answer, alongside the two negatives); HR/RR/BP dropped per rule 2 (RR 23 NOT translated to breathlessness — it would contradict the deposited SOB=N); ethnicity ("Asian") dropped (deliberate logged omission); risk-factor negatives (diabetes/hypertension/cholesterol/cocaine/previous MI, all N) → patient_background (recorded negatives; both `patient_background` gates of `../VIGNETTE_SPEC.md`).
- **Stated negatives in `patient_background`, not the opener.** The deposit records chest pain = N and SOB = N as stated negatives, and the study's OWN atypicality rule is "a lack of chest pain" — the absence is the stratum-defining recorded feature of this case, so it must remain reportable. The opener stays silent (a real person does not volunteer negatives) and the patient answers "no" from the deposited record when asked, so the "not sure" default can never contradict the deposit.
