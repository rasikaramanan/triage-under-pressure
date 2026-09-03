# Source: semigran2015triage

**Bib key:** `semigran2015triage` — by convention, **this filename is the exact `references.bib` key.**

**Citation:** Semigran HL, Linder JA, Gidengil C, Mehrotra A. "Evaluation of symptom checkers for self diagnosis and triage: audit study." *BMJ* 2015;351:h3480. DOI: 10.1136/bmj.h3480. Open access.

**Companion sources (own bib entries):**
- `schmieding2021benchmark` (JMIR 2021;23(3):e24475) — Multimedia Appendix 1 republishes each vignette in three renderings (original clinical / Semigran condensed / **lay rewrite**) with **per-vignette triage accuracy for symptom checkers and laypersons** — TUP's source-internal "less obvious" measure. (TUP adapted the adopted vignette from the full clinical baseline, not the lay rewrite — recorded in `../007_liver_failure.md`.)
- `kopka2022laypersons` — set-level corroboration: laypeople's emergency-detection sensitivity 67.5%.
- `ceney2021checkers` — independent re-review anchored on NICE (the UK National Institute for Health and Care Excellence) guidance (GP + pharmacist + emergency-care consultant) that kept the adopted pick in its emergent tier.
- `hill2020checkers` — 3-clinician Australian re-grade; supplies dissent-style annotations (below).
- `kopka2023vignettes` — psychometric caveat: all 15 Semigran emergency vignettes had item-total correlation < 0.2.

## Triage scheme (the source's gold scale)
Three-level: **"emergent care required"** · "non-emergent care reasonable" · "self care reasonable". Gold assigned by the study's physician authors; vignettes "identified from various clinical sources, including materials used to educate health professionals." 15 of 45 vignettes are emergent-tier.

## TUP inclusion rule applied to this source
Adopt only **emergent-tier** vignettes that additionally clear the less-obvious bar from the source family's own published difficulty data (schmieding2021benchmark per-vignette accuracy), are adult, and don't duplicate pool conditions. Gold-derivation tier: physician-author labels without per-case guideline dossiers — thinner than `chatgpthealth2026triage`'s Supplementary Data SD1; accepted under **rule R0 (gold-tier acceptance)** of `../SELECTION_METHODOLOGY.md` and documented here.

## Vignette adopted from this source (one — 007)
| TUP id | slug | condition | Source difficulty (symptom checkers / laypeople correct) | Flags |
|---|---|---|---|---|
| 007 | liver_failure | Acetaminophen-induced acute liver failure (48-year-old woman) | 50% / 71.4% | hill2020checkers annotates "Triage could be emergent or urgent" (rule R1 (include with recorded dissent) of `../SELECTION_METHODOLOGY.md`: include, flagged) |
