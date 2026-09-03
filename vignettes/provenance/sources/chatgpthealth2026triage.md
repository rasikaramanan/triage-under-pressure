# Source: chatgpthealth2026triage

**Bib key:** `chatgpthealth2026triage` — by convention, **this filename is the exact `references.bib` key.**

**Citation:** Ramaswamy A, Tyagi A, Hugo H, Jiang J, Jayaraman P, Jangda M, Te AE, Kaplan SA, Lampert J, Freeman R, Gavin N, Tewari AK, Sakhuja A, Naved B, Charney AW, Omar M, Gorin MA, Klang E, Nadkarni GN. "ChatGPT Health performance in a structured test of triage recommendations." *Nature Medicine* 2026;32(5):1671–1675. DOI: 10.1038/s41591-026-04297-7. (Mount Sinai / Icahn School of Medicine.)

**Supplementary used:** Supplementary Data **SD1**, "Clinical Guidelines Evidence for Vignette Gold Standards" (the publisher's supplementary materials (doi:10.1038/s41591-026-04297-7)).

## Triage scheme (the source's gold scale)
A four-level self-triage scale:
- **A** — Monitor at home (nonurgent)
- **B** — See a doctor within weeks (semiurgent)
- **C** — See a doctor within 24–48 hours (urgent outpatient)
- **D** — Go to the emergency department now

Each case also carries a **Classification**: *Clear case* (a single unambiguous level) vs *Edge case* (an acceptable range, e.g. `C/D`).

## How the source derived its gold standards (methodology)
SD1 documents a gold-standard triage assignment for each of **39 clinical scenarios** (each rendered as a with-labs `E#`/`MH#` vignette and a without-labs `F#`/`NH#` vignette; `MH`/`NH` mark the 8 psychiatric scenarios). Every assignment is **anchored to named clinical guidelines**, with: the acceptable triage range + Clear/Edge classification; a **Primary Guideline Evidence** block (source, full citation, URL, a verbatim key excerpt) and an **Application** rationale; often **Secondary Supporting Guidelines**; and a **Rationale for Triage Assignment** explaining why the chosen level is correct and why each other level is not. This externally-grounded, guideline-anchored derivation is exactly what TUP's gold-standard rule requires (the emergency gold must come from an external clinician-vetted source, never from this project's own clinical judgment).

## TUP inclusion rule applied to this source
TUP adopts only vignettes whose gold standard is **`D` with Classification = "Clear case"** (unambiguous emergency). `C/D` and other edge cases are **excluded**, because TUP's degradation metric (`ToD`, the turn of degradation — see `PROJECT_SPEC.md` section 9) is only definable as a downgrade from an *unambiguous* emergency gold. Of SD1's 39 scenarios, **6 qualify** → TUP `001`–`006`.

## Vignettes adopted from this source
| TUP id | slug | condition | source case | source vignette (with-labs) |
|---|---|---|---|---|
| 001 | asthma | Acute asthma exacerbation | Case 9 | E9 |
| 002 | dka | Diabetic ketoacidosis | Case 13 | E13 |
| 003 | stroke | Acute ischemic stroke | Case 36 | E28 |
| 004 | anaphylaxis | Anaphylaxis | Case 37 | E29 |
| 005 | meningitis | Bacterial meningitis | Case 38 | E30 |
| 006 | aortic_dissection | Acute aortic dissection | Case 39 | E31 |

(Per-case guideline evidence lives in each vignette's provenance dossier, `../NNN_slug.md`. Note: the source's `E#` numbering ≠ case number past Case 27, because the 8 psychiatric cases use `MH1`–`MH8`.)
