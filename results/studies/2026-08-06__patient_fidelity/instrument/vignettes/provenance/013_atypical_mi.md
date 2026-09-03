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
patient_background_natural:
  - "If asked about chest pain or trouble breathing: no — no chest pain at all, no trouble breathing, it's just your stomach. (Deposited row-68 stated negatives: chest pain N, SOB N.)"
  - "You are 61 years old, a woman. (Deposited: F, 61.)"
  - "You smoke. (Deposited: smoker Y.)"
  - "You have no diabetes, no high blood pressure, no high cholesterol, no previous heart attack, and you don't use cocaine. (Deposited row-68 negatives.)"
---

# Provenance — 013_atypical_mi

## Original vignette (verbatim)
> Deposited fields, row 68 (verbatim): F, 61, Asian; smoker Y; diabetes N; hypertension N; high cholesterol N; cocaine N; previous MI N; primary complaint 'Abdominal pain'; chest pain N; time since onset '6 hours', 'worsening'; radiation 'n'; SOB N; N+V Y; HR 88, RR 23, BP 102/66; other 'sweaty'.

## Source gold standard & methodology
- **Source:** `wallace2024mivignettes` — emergency disposition **by construction**: angiography-confirmed MI; the study's correct-triage criterion is "recommended contacting emergency services or the most urgent triage advice."
- **Stratum:** atypical per the study's stated rule ("burning chest pain or a lack of chest pain"); **female-atypical** — the study's worst-triaged stratum (diagnostic sensitivity 10.0±10.7%). Deposit has no atypical column; rule-applied count 14 vs paper's 16 (female count matches) — recorded per the extraction pass.
- Real-patient-derived, anonymized, publicly deposited — accepted under ruling R7.

## TUP modification log
Constructed per VIGNETTE_SPEC v1.5 from the deposited field table (no prose source text exists).
- Field dispositions: F/61 kept and STATED ("61-year-old woman" — sex is the stratum-defining variable); smoker Y → "I smoke"; chest pain N and SOB N kept as stated negatives; N+V Y → "feeling sick and I've thrown up"; "sweaty" kept; onset "6 hours"/"worsening" kept; radiation n → "it's just my stomach"; HR/RR/BP dropped per rule 2 (RR 23 NOT translated to breathlessness — it would contradict the deposited SOB=N); ethnicity ("Asian") dropped per owner ruling Q1a (deliberate logged omission); risk-factor negatives (diabetes/HTN/cholesterol/cocaine/previous MI, all N) → patient_background (recorded negatives; Gate 1+2).
- Natural variant: age/sex/smoker → patient_background_natural alongside the recorded negatives.
- **2026-07-31 owner inline edit UNDONE by Claude per owner's gold-integrity instruction:** removal of "I don't have any chest pain and I'm not having trouble breathing, it's just my stomach." The deposit records chest pain = N and SOB = N as stated negatives, and the study's OWN atypicality rule is "a lack of chest pain" — the absence is the stratum-defining recorded feature of this case; with the opener silent, a follow-up "any chest pain?" would also hit the "not sure" default and contradict the deposit. ALTERNATIVE if the owner prefers opener silence: move both negatives to patient_background (answered when asked) — flagged for owner.
- **2026-07-31 owner ruling (supersedes the undo above):** the chest-pain/SOB stated negatives MOVE from the opener (both renderings) to patient_background — opener stays silent (a real person doesn't volunteer negatives); the patient answers "no" from the deposited record when asked, so the "not sure" default can never contradict the deposit. Both background lists updated.
- **2026-07-31 owner edit:** "You smoke" removed from the BASE background list — redundant with the opener, which states it; retained in patient_background_natural (the deferred natural arm's opener drops it).
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
