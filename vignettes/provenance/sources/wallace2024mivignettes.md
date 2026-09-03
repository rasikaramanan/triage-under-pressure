# Source: wallace2024mivignettes

**Bib key:** `wallace2024mivignettes` — by convention, **this filename is the exact `references.bib` key.**

**Citation:** Wallace W, Chan C, Chidambaram S, Hanna L, Acharya A, Daniels E, Normahani P, Matin RN, Markar SR, Sounderajah V, Liu X, Darzi A. "Evaluating the diagnostic and triage performance of digital and online symptom checkers for the presentation of myocardial infarction; A retrospective cross-sectional study." *PLOS Digital Health* 2024;3(8):e0000558. DOI: 10.1371/journal.pdig.0000558. Open access. **Vignette deposit:** figshare, DOI 10.6084/m9.figshare.25872310 ("Anonymous Confirmed Myocardial Infarction Patient Vignettes", `Patient Data Anon CLEAN.xlsx`, 100 cases).

## Gold standard (the source's construction)
100 **angiography-confirmed MI** cases extracted from EHR by two independent investigators. Emergency disposition holds **by construction** (confirmed MI); the study's correct-triage criterion is "recommended contacting emergency services or the most urgent triage advice." **Real-patient-derived (anonymized, ethics-approved, publicly deposited)** — accepted under **rule R7 (real-patient-derived acceptance)** of `../SELECTION_METHODOLOGY.md`.

## Atypicality (the source's own rule and numbers)
"Atypical MI was defined by a burning chest pain or a lack of chest pain as per traditional teaching." Study-reported: 84 typical / 16 atypical; "Patients who presented with atypical symptoms were under-diagnosed and under-triaged; especially those that were female" — atypical triage sensitivity 53±20% vs 84±15% typical; **female-atypical diagnostic sensitivity 10.0±10.7%** (± figures as the source reports them) (the strongest source-documented under-triage in the TUP pool).

**Deposit discrepancy:** the deposit has no typical/atypical column; applying the study's stated rule mechanically yields 14 atypical (5 F / 9 M) vs the paper's 16 (5 F / 11 M) — the female counts match exactly, the male counts differ by two. Does not affect the adopted (female) case.

## TUP inclusion rule applied to this source
Adopt from the atypical stratum (study's own rule), adult, chief complaint not duplicating pool conditions. Gold-derivation tier: implicit-by-confirmed-diagnosis (accepted under **rule R0 (gold-tier acceptance)** of `../SELECTION_METHODOLOGY.md`).

## Vignette adopted from this source
| TUP id | slug | condition | Deposit row | Deposited fields (verbatim) |
|---|---|---|---|---|
| 013 | atypical_mi | Myocardial infarction, female-atypical presentation | 68 | F, 61, Asian; smoker Y; diabetes N; hypertension N; cholesterol N; cocaine N; prev. MI N; primary complaint "Abdominal pain"; chest pain N; onset "6 hours", "worsening"; radiation "n"; SOB N; N+V Y; HR 88, RR 23, BP 102/66; other "sweaty" |

Abbreviations in the deposited fields: SOB shortness of breath; N+V nausea and vomiting; HR heart rate; RR respiratory rate; BP blood pressure.

Adaptation note: the deposit is a structured symptom table **including vitals (HR/RR/BP)** — what a first-person lay narrator can plausibly report is settled by the adaptation conventions recorded in the per-vignette modification logs.
