# `vignettes/` — the 14 emergency scenarios

The stimuli of the evaluation: fourteen first-person patient scenarios (`001`–`014`), each
describing symptoms whose clinician-vetted disposition — assigned by an **external published
source**, never by this project — is *seek emergency care now*. The set is closed: it is the
exact set the reported experiment ran on, byte-snapshotted into the run's `instrument/`
directory (`results/runs/2026-08-06__full_experiment/instrument/`); the snapshot is the byte
authority for WHAT THE RUN LOADED. The working-tree dossiers are the corrected READING: where the two
disagree on prose (a length figure, a quoted line) the working tree is right; eight
snapshot dossiers also carry a `patient_background_natural` frontmatter field that no code
reads. Vignette texts are byte-identical in both places.

## The binding validity rule

Degradation is only definable as a downgrade from the officially-recommended treatment, so
**every gold standard comes from an external clinician-vetted source** (a published study or
guideline), and vignettes are *adapted into first person* from those sources — never invented
clinically. No clinical judgment inside this project, human or model, ever sets or overrides a
gold standard.

## Layout

| path | what it is |
|---|---|
| `<id>_<slug>.md` | the adapted first-person vignette; the harness authors the patient's first message as this text plus a fixed "what should i do?" suffix |
| `index.csv` | one-row-per-vignette master index (id, source key, clinical condition, cohort — `pilot` for 001–006, adapted from `chatgpthealth2026triage`; `expansion` for 007–014, from the four further sources — review status, gold-driver flag), machine-checked against the dossier frontmatter by the test suite; where a source publishes no condition label the condition cell says so |
| `VIGNETTE_SPEC.md` | the construction rules: adaptation constraints, what may/may not be dropped, the conformance checklist, the patient-background mechanism |
| `provenance/<id>_<slug>.md` | per-vignette dossier: source citation + exact locator, the source's gold standard and rationale, primary guideline evidence where the source publishes it (cases 001–006); expansion-source cases carry their source's own disposition gold instead — urgency-only for the four adverse-event-derived cases — plus the full adaptation log |
| `provenance/sources/<bib-key>.md` | per-source dossier: citation, the source's own triage scale, and the inclusion rule applied to it |
| `provenance/SELECTION_METHODOLOGY.md` | how the set was selected: the five adopted sources and their adoption rules, inclusion rules, difficulty ("less obvious") criteria, the patient-background verdicts, honest-gap registry |

## Scope facts

- **Adult-only, true emergencies only, first person.** Includes OB-GYN (ectopic pregnancy,
  reduced fetal movements).
- **No mental-health vignette** — a documented literature gap, recorded as a limitation: no
  openly published, human-authored, non-self-harm psychiatric scenario with an unambiguous
  external emergency-disposition gold standard was available to adapt (the eight psychiatric
  scenarios in `chatgpthealth2026triage` are not among its six "D / Clear case" emergencies).
- **Five sources contributed vignettes** (attribution in `NOTICE.md` at the repo root); two are
  real-patient-derived (anonymized, ethics-noted, published by their original investigators).
- The operative gold is a **single constant** — "seek emergency care now" — stated in the judge
  rubric with an anti-re-triage rule. The differently-worded dispositions recorded in the
  dossiers ("Immediate", "Emergency department", …) are each source's own scale: citation, not
  disagreement.
