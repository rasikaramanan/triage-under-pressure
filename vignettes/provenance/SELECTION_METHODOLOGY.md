# How the 14-vignette set was selected — methodology and honest gaps

## Acceptance rules (four codes — R0, R1, R4, R7 — cited across the provenance files; the numbering gaps are inherited from a longer working list, and only these four apply to the released set)

This registry is the single definition of the R-codes. Dossiers cite a code wherever a rule
bound an adoption decision; every code defined below is cited in at least one per-vignette or
per-source dossier. The codes in use:

- **R0 — gold-tier acceptance.** A source whose emergency gold is assigned by clinician
  author(s) or a clinical panel against named guidelines, but without a per-case evidence
  dossier, is acceptable; the thinner vetting tier is recorded wherever the code is cited.
- **R1 — include with recorded dissent.** A vignette with a soft dissenting re-grade from a
  corroborating source is included, with the dissent quoted and flagged in its dossier.
- **R4 — salience not source-quantified.** A source publishing no per-vignette difficulty data
  may still contribute; the missing salience measure is flagged on each adopted vignette.
- **R7 — real-patient-derived acceptance.** Published, ethics-noted, anonymized
  real-patient-derived cases are acceptable sources.

> **Why the slate is what it is, and where the honest gaps are.** Per-vignette facts stay in
> `<id>_<slug>.md`; the formal rules stay in `../VIGNETTE_SPEC.md`.

## Selection rule

Every candidate had to carry an explicit emergent/ED-now disposition **from its external source's
own gold**, with the "less obvious" character documented from the source's own published difficulty
data or statements where the source provides them (rule R4 flags the adoptions where it does not) — no clinical judgment of ours anywhere. Adult-only, first-person-adaptable,
condition-level dedup across the set.

**Gold-tier decision:** the original source (`chatgpthealth2026triage`) backed
its gold with a per-case guideline-evidence dossier; the expansion sources use coarser
triage scales whose top tier ("emergent care required" / "Emergency department" / "Immediate",
or emergency by construction) is functionally equivalent but derived more thinly
(author-physician or small-panel gold). Accepted as-is —
consistent with never-re-litigating an external gold — with the weaker derivation documented per
source. **Real-patient-derived vignettes rule (R7):** published, ethics-approved,
de-identified vignettes derived from real patients (Wallace EHR extracts, Ilicki adverse-event
reports) pass the guardrail, documented per source.

## Sources

**Adopted (5):** `chatgpthealth2026triage` (cases 001–006: the 6 of its 39 scenarios that carry
gold "D / Clear case", all adopted) · `semigran2015triage` (+ Schmieding 2021 per-vignette
difficulty, Ceney 2021 / Hill 2020 re-reviews) · `brown2025selftriage` · `wallace2024mivignettes`
(atypical-MI, angiography-confirmed — emergency by construction; a structured symptom table on figshare, no prose texts) ·
`ilicki2025triageerrors` (Swedish adverse-event mis-triage vignettes — under-triage by
construction; 3-clinician "Immediate" gold).

## `patient_background` — origin, verdicts, and the residual-gap registry

**Why the mechanism exists:** multi-turn conversations let advisors ask follow-ups —
a surface the single-turn source studies never had. The anti-fabrication rule ("say you're not
sure") is correct for genuinely unrecorded clinical facts but implausible for facts a real person
always knows, and it can even force *invented negatives* — a simulated patient denying it owns a peak flow
meter when the source records a peak-flow reading against a personal best. The mechanism that
answers this is the two-gate, source-anchored background block formalized in `../VIGNETTE_SPEC.md`, "Patient background facts",
whose lines are injected only into the patient's prompt — never the advisor's or judge's.

**End state across the 14:** populated for asthma, stroke,
aortic dissection, liver failure, cold mottled leg, ectopic, atypical MI, no-fetal-movements — 8 of
14; deliberately empty for DKA, anaphylaxis, meningitis, blue-tinged dyspnea, transient vision
loss, glaucoma — 6 of 14. Two lines are **entailment-class** rather than source-recorded (ectopic's sexual
activity and no-fetal-movements' previously-felt movements, each entailed by the presenting
complaint or the source's own gold rationale), and four further lines are **minimal readings** of
a recorded value or of source silence (asthma's own-meter framing of a recorded peak flow,
cold-mottled-leg's deflection of unnamed comorbidities, ectopic's no-test clause and its no-medications half) — three flagged in their dossier annotation, and 012's no-medications half flagged in its
modification log.

**Residual gaps — Gate 2 trips but the source is silent, so the block stays empty by rule** (each
also logged in its dossier; listed here as the set-level registry):

| vignette | the implausible "not sure" |
|---|---|
| 002 DKA | took insulin today? pump or injections? how long diabetic? — the set's most painful honest gap |
| 004 anaphylaxis | which antihistamine/dose; what exactly was eaten |
| 005 meningitis | vaccination status; sick contacts ("not sure" genuinely realistic here) |
| 008 blue-tinged dyspnea | onset/duration of the breathlessness; temperature measured? — the second-largest gap |
| 010 transient vision loss | exactly when the episode happened and how long it lasted |
| 011 glaucoma | **which eye** (the source never says); exact onset time |

(009's dossier logs one further gap of the same kind — exactly which chronic conditions —
even though its background block is otherwise populated.)

**The single exception:** no-fetal-movements' gestational age is recorded nowhere in its source,
and "how far along are you?" is a certain first question — the deviation **inserted 32 weeks** into
`patient_background` (never the vignette text), with the guideline basis in that vignette's dossier
under "⚠ TUP-ADDED VALUE". It is the **only invented value in the set**.

**Demographic completeness (verified per source):** openers state age and sex wherever the
SOURCE states them (014's "pregnant" carries the source's "woman"). The asthma, DKA and stroke sources (001–003) state no sex, so none is added;
the anaphylaxis, meningitis and aortic-dissection sources DO state it ("31-year-old man", etc.),
and those openers carry it — the edits are recorded in their dossiers. No opener states ethnicity;
the only ethnicity value any source deposits (atypical MI) is recorded verbatim in
`sources/wallace2024mivignettes.md` and in `013_atypical_mi.md`, and is used in neither the
vignette text nor `patient_background`.

## Caveats registry (source-level, kept with selection rather than per-vignette)

- Kopka 2023 reports all 15 Semigran emergency vignettes had item-total correlation < 0.2 — a
  psychometric criticism of that set, noted here for the one adopted Semigran vignette.
- The Ilicki adoptions (008–010, 014) have **no per-case diagnosis published** — gold is
  urgency-only ("Immediate") and slugs are presentation-named. The write-up's vignette appendix
  (site/index.html) labels these four "Not published by source (urgency-only gold)" in place of a
  condition name.
- Every `references.bib` entry carries a VERIFIED note; most name the registry and date checked.
