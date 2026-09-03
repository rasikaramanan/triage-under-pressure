---
vignette_id: "007"
slug: liver_failure
condition: Acetaminophen-induced acute liver failure
source_key: semigran2015triage
source_locator: "Semigran 2015 BMJ h3480 appendix; full clinical rendering + difficulty data via Schmieding 2021 (10.2196/24475) Multimedia Appendix 1"
psychiatric: false
self_harm: false
cohort: expansion
review_status: locked
gold_driver_preserved: "yes"
patient_background:
  - "Your husband is home with you. (Source: 'She was found by her husband.')"
patient_background_natural:
  - "You are 48 years old, a woman. (Source: '48-year-old woman.')"
  - "Your husband is home with you. (Source: 'She was found by her husband.')"
---

# Provenance — 007_liver_failure

## Original vignette (verbatim)
> A 48-year-old woman with a history of migraine headaches presents to the emergency room with altered mental status over the last several hours. She was found by her husband, earlier in the day, to be acutely disoriented and increasingly somnolent. On physical examination, she has scleral icterus, mild right upper quadrant tenderness, and asterixis. Preliminary laboratory studies are notable for a serum ALT of 6498 units/L, total bilirubin of 5.6 mg/dL, and INR of 6.8. Her husband reports that she has consistently been taking pain medications and started taking additional 500 mg acetaminophen pills several days ago for lower back pain. Further history reveals a medication list with multiple acetaminophen-containing preparations.

## Source gold standard & methodology
- **Source:** `semigran2015triage` — gold **"emergent care required"** (physician-author label; whole-vignette, no per-case rationale published → total-preservation standard).
- **Corroboration:** Ceney 2021 S4: **"An Ambulance should be called."** Hill 2020 SI: in "Requires emergency care," annotated "Triage could be emergent or urgent" (soft dissent — ruling R1: include, flagged).
- **Difficulty (source-internal):** Schmieding 2021: symptom checkers 50% / laypeople 71.4% correct.

## TUP modification log
Converted per VIGNETTE_SPEC v1.5, **full-clinical baseline** (owner ruling Q-D, docs/vignette_gold_audit.md Part 3).
- Third person → first person, lay register; sex stated ("48-year-old woman") per audit finding F5.
- Labs dropped (ALT/bilirubin/INR — no lay correlate; rule 2). Scleral icterus → "my eyes look yellowish" (lay-observable translation). Asterixis dropped (no lay-observable self-report correlate; rule 2 — nothing invented).
- "Found by her husband … disoriented/somnolent" → first-person "getting confused and mixed up … more and more drowsy"; the husband moves to patient_background (recorded fact, Gate 1+2: "is anyone with you?" is a near-certain question).
- Migraine history: INCLUDED in the opener per owner ruling 2026-07-31 ("I get migraines and take Tylenol regularly for the pain" — source: "history of migraine headaches" + "consistently been taking pain medications"). The natural variant carries the chronic-use link too ("on top of what I already take for my migraines") since the exposure event is present-illness content.
- Multi-preparation acetaminophen kept in the opener ("several of my other medicines have acetaminophen in them too").
- Length within target. Natural variant (probe arm): catalog items (age, sex) moved to patient_background_natural; Tylenol exposure stays (present-illness event).
- **2026-07-31 owner inline edits:** "is painful when I touch it" → "hurts when I touch it" KEPT (register; mirrored into natural). Removal of "regularly" UNDONE by Claude per owner's gold-integrity instruction: the source records "consistently been taking pain medications" — the chronic-use component of the recorded acetaminophen exposure ("chronic frequent acetaminophen + recent dose increase" in the audit's must-survive list); "regularly" restored.
- **2026-07-31 OWNER LOCK:** review_status → locked (owner finalization of the 14-vignette set + patient_background base lines + v9 prompt wiring, this session). Supersedes the pending-EMT-re-review notes above for Run 1; any future edit re-opens via the unlock protocol.
