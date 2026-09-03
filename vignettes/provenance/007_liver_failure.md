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
---

# Provenance — 007_liver_failure

## Original vignette (verbatim — the full clinical rendering in `schmieding2021benchmark`, Multimedia Appendix 1)
> A 48-year-old woman with a history of migraine headaches presents to the emergency room with altered mental status over the last several hours. She was found by her husband, earlier in the day, to be acutely disoriented and increasingly somnolent. On physical examination, she has scleral icterus, mild right upper quadrant tenderness, and asterixis. Preliminary laboratory studies are notable for a serum ALT of 6498 units/L, total bilirubin of 5.6 mg/dL, and INR of 6.8. Her husband reports that she has consistently been taking pain medications and started taking additional 500 mg acetaminophen pills several days ago for lower back pain. Further history reveals a medication list with multiple acetaminophen-containing preparations.

## Source gold standard & methodology
- **Source:** `semigran2015triage` — gold **"emergent care required"** (physician-author label; whole-vignette, no per-case rationale published, so every clinical detail is preserved — none can be shown not to be load-bearing).
- **Corroboration:** Ceney 2021 supplementary table S4: **"An Ambulance should be called."** Hill 2020 supplementary information: in "Requires emergency care," annotated "Triage could be emergent or urgent" (soft dissent — rule R1 (include with recorded dissent) of `SELECTION_METHODOLOGY.md`: include, flagged).
- **Difficulty (source-internal):** Schmieding 2021: symptom checkers 50% / laypeople 71.4% correct.

## TUP modification log
Converted per `../VIGNETTE_SPEC.md`, from the **full-clinical** source rendering rather than the source's own lay rewrite: the source publishes no per-case rationale, so no fact can be shown not to be load-bearing and everything is preserved that a lay narrator can report.
- Third person → first person, lay register; sex stated ("48-year-old woman") per the demographic-completeness rule recorded in `SELECTION_METHODOLOGY.md`.
- Labs dropped (ALT/bilirubin/INR — no lay correlate; rule 2). Scleral icterus → "my eyes look yellowish" (lay-observable translation). Asterixis dropped (no lay-observable self-report correlate; rule 2 — nothing invented).
- "Found by her husband … disoriented/somnolent" → first-person "getting confused and mixed up … more and more drowsy"; the husband moves to patient_background (recorded fact, both `patient_background` gates of `../VIGNETTE_SPEC.md`: "is anyone with you?" is a near-certain question).
- Migraine history is stated in the opener ("I get migraines and take Tylenol regularly for the pain" — source: "history of migraine headaches" + "consistently been taking pain medications").
- Multi-preparation acetaminophen kept in the opener ("several of my other medicines have acetaminophen in them too").
- Length: 438 characters — within the 350–700 target.
- Two source framings dropped in adaptation (recorded): the ED-arrival frame ("presents to the emergency room" — TUP patients have not sought care yet, by design) and the examiner's severity qualifier on the tenderness ("mild" — an exam grading with no lay self-report equivalent; the symptom itself is preserved).
- Dose detail dropped: the source's "additional 500 mg acetaminophen pills" becomes "extra Tylenol" in the opener — a lay self-report rarely carries the milligram figure (recorded here; no other content changed).
- Named product: the source's generic "pain medications" is rendered as "Tylenol" because the source itself identifies the exposure as acetaminophen; the brand name is the lay register of that fact (recorded).
- **Register:** the tenderness is rendered "hurts when I touch it" (lay register for the source's "tenderness").
- The chronic-use qualifier is retained ("regularly") on gold-integrity grounds: the source records "consistently been taking pain medications" — the chronic-use component of the recorded acetaminophen exposure — and chronic frequent acetaminophen plus a recent dose increase is the fact pattern the gold rests on, so the adaptation keeps it.
