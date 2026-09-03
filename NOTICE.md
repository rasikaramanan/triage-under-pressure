# NOTICE — third-party attribution

TUP's 14 emergency vignettes are **adaptations** of scenarios published in external,
clinician-vetted studies. The adaptation (first-person rendering, removal of numeric
vitals/labs, lay register) is TUP-authored; the underlying scenarios, their gold-standard
emergency dispositions, and any quoted guideline excerpts belong to their publishers and
authors, are used here with citation, and are **not** relicensed by this repository's
licenses. Per-vignette derivation detail lives in `vignettes/provenance/<id>_<slug>.md`; the exact
inclusion rules per source live in `vignettes/provenance/sources/<bib-key>.md`.

## Vignette sources (what each contributed)

| bib key | citation | DOI | vignettes |
|---|---|---|---|
| `chatgpthealth2026triage` | Ramaswamy A, et al. "ChatGPT Health performance in a structured test of triage recommendations." *Nature Medicine* 2026;32(5):1671–1675 | [10.1038/s41591-026-04297-7](https://doi.org/10.1038/s41591-026-04297-7) | 001–006 (from Supplementary Data SD1) |
| `ilicki2025triageerrors` | Ilicki J, Edman S, Stalfors J, Molin CJ. "Evaluating digital triage symptom checker with historical triage-related adverse events." *Scand J Prim Health Care* 2025;44(1):1–14 | [10.1080/02813432.2025.2563517](https://doi.org/10.1080/02813432.2025.2563517) | 008–010, 014 |
| `brown2025selftriage` | Brown HL. "Evaluation of Artificial Intelligence for Patient Self-Triage…" *Cureus* 2025;17(11):e97834 | [10.7759/cureus.97834](https://doi.org/10.7759/cureus.97834) | 011, 012 |
| `semigran2015triage` | Semigran HL, Linder JA, Gidengil C, Mehrotra A. "Evaluation of symptom checkers for self diagnosis and triage: audit study." *BMJ* 2015;351:h3480 | [10.1136/bmj.h3480](https://doi.org/10.1136/bmj.h3480) | 007 |
| `wallace2024mivignettes` | Wallace W, et al. "Evaluating the diagnostic and triage performance of digital and online symptom checkers for the presentation of myocardial infarction." *PLOS Digital Health* 2024;3(8):e0000558 | [10.1371/journal.pdig.0000558](https://doi.org/10.1371/journal.pdig.0000558) | 013 (deposit: figshare [10.6084/m9.figshare.25872310](https://doi.org/10.6084/m9.figshare.25872310)) |

Two sources are **real-patient-derived** (anonymized, ethics-noted, published):
`ilicki2025triageerrors` (adverse-event reports) and `wallace2024mivignettes`
(angiography-confirmed MI cases from a public deposit). They are named here explicitly
because their scenarios describe real people's presentations, in de-identified form, as
published by the original investigators.

## Corroborating and companion sources (cited, nothing redistributed)

`ceney2021checkers`, `hill2020checkers`, `schmieding2021benchmark`, `kopka2022laypersons`,
`kopka2023vignettes` — independent re-grades, difficulty data, and psychometric caveats used
in vignette selection. Clinical guideline excerpts quoted in the provenance dossiers
(AHA/ASA, NICE, and others, each cited in place) remain the property of their publishers.

## What this repository redistributes vs. cites

- **Redistributed (adapted):** the 14 first-person vignette texts in `vignettes/`, each a
  TUP-authored adaptation of its cited source scenario.
- **Redistributed (quoted):** short verbatim excerpts of source scenarios and guideline
  language inside the provenance dossiers, marked as quotations, for gold-standard
  verification.
- **Cited only:** everything else — full source texts, supplements, and deposits are reached
  through the DOIs above, never re-hosted here.
