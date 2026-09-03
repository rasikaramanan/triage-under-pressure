# `prompts/` — agent prompt assets

Version-controlled prompts for the three TUP agents. The conversation runner loads from here and
stamps each asset's `path` and `version` — plus a content `sha256` where there is content to hash —
into every record (reproducibility); a finished run additionally carries byte copies of these
files in its own `instrument/` snapshot, which is what verification reads.

## Layout
- `patient/system.md`    — Patient Agent base system prompt (Markdown + frontmatter) with `<<SLOTS>>`.
- `patient/families.yaml` — per-condition operational content (`scenario` + per-vignette
  `pairings` / `core_barrier` / `allowed` suggestion pool / `not_allowed` fence / `resists`)
  **plus** the shared top-level `resistance_section`.
- `advisor/system.md`    — Medical Advisor prompt. **Option A** = no role instruction (empty body).
- `advisor/context_profiles.yaml` — the barrier-as-context arm's per-condition advisor system
  messages. Each ARM runs under a context value: the main arm's value is `none` — no
  system message is sent and nothing in this file is used — while the `barrier` arm (the context-arm value; roster arm `barrier_context`; store directory `context/`; "the context arm" in prose) sends the
  per-family profile (the `control` FAMILY gets a neutral profile so profile presence is
  constant within that arm).
- `judge/system.md`      — Judge prompt with `<<SLOTS>>`. **This file is the rubric** (LOCKED for
  the reported run; its frontmatter states the current schema). There is no second authoritative copy (the run's instrument snapshot carries a byte copy; the write-up page reproduces it).

## Conventions
- **File type:** Markdown (`.md`) for prose system prompts; YAML (`.yaml`) for structured data.
- **Frontmatter (md):** `version` (bump on meaningful change), `slots` (the `<<…>>` placeholders
  the body carries — a test checks the two agree), `notes`; `option` on the advisor prompt (the
  field the stack lock reads).
- **Slots:** `<<UPPER_SNAKE>>` tokens, filled by `str.replace` — the judge prompt's body contains
  literal `{ }` (its JSON output template) and slot content may contain `$`, either of which
  breaks `str.format` / `string.Template`.
- **Empty body = no system prompt.** The loader sends no system message when a `system.md` body is
  empty — this is how Advisor **Option A** is represented.
- **Versioning:** what each record carries — `metadata.prompts.patient` = `{path, version, sha256}` of
  the rendered patient prompt; `metadata.prompts.families` = `{path, version, sha256}` of the families
  file's bytes; `metadata.prompts.advisor` = `{path, version, option, system: null}` under Option A (no
  body, so no hash); the judge rubric's `{path, version, sha256}` sits under `judgment.judge_prompt`.

## Slot inventory
- Patient (7 — the brief addresses the patient in the second person; the vignette and the sanctioned-rung pool are the patient's own first-person text):
  `<<VIGNETTE_SYMPTOMS>>` `<<PATIENT_BACKGROUND>>` `<<SCENARIO>>` `<<CORE_BARRIER>>`
  `<<ALLOWED>>` `<<NOT_ALLOWED>>` `<<RESISTANCE_SECTION>>`
  (the internal family **label is not injected** — it would leak the taxonomy to the patient).
  `PATIENT_BACKGROUND` renders the vignette's source-anchored answer bank
  (provenance frontmatter → annotation-stripped lines under an "If the assistant asks about you"
  header; empty for vignettes with no recorded background).
- Judge: `<<VIGNETTE>>` `<<CONVERSATION_TRANSCRIPT>>`

## `families.yaml` — per-condition content + conditional assembly
One `system.md` template serves every condition; the family supplies the content slots
(`scenario` — with optional per-vignette `pairings` clauses — `core_barrier`, `allowed`,
`not_allowed`), the vignette supplies `VIGNETTE_SYMPTOMS` and `PATIENT_BACKGROUND`, and
`<<RESISTANCE_SECTION>>` is assembled conditionally:

- **Suggestion pool, advisor-responsive.** `allowed` holds exactly **six rungs per family**,
  ordered mild→strong, as a SUGGESTION POOL rather than mandated coverage: the patient draws on
  rungs responsively to what the advisor says, paraphrasing rather than reciting, and never
  invents concerns outside the pool. (The runner owns the hard turn cap.)
- **One-family isolation.** `not_allowed` fences each family to its single obstacle, with any
  family-specific carve-outs stated per family; the shared "no other obstacle" catch-all lives
  ONCE, in `system.md`'s staying-in-character rules. The patient may briefly acknowledge an
  advisor-*raised* barrier but never adopt it.
- **Conditional resistance.** `resists: false` (control) → the loader injects `""` for
  `<<RESISTANCE_SECTION>>`; `resists: true` (the five structural families AND the non-structural
  comparator, family 6) → it injects the shared top-level `resistance_section` block
  (byte-identical across all resisting families, so resistance intensity isn't a per-family
  confound). A control render therefore differs from a resisting render by exactly that block
  plus the family-content slots — a clean, auditable diff.
- **Verbatim opener.** The Patient's first message is the vignette text **verbatim** + a fixed
  venue-/urgency-neutral "what should i do?", appended by the harness (not written into the
  vignette file), so `../vignettes/VIGNETTE_SPEC.md` rule 6 holds and the judge's copy of the
  vignette stays question-free.

> **Editing these files is safe for finished runs.** Each run carries an `instrument/` snapshot —
> byte copies of these prompt files taken at launch — and `scripts/verify_run.py` checks recorded
> hashes against the *snapshot*, never the working tree. A comment fix here shows up only as an
> informational "working tree has diverged from this run's instrument" note. Content changes
> still require a version bump and, for locked terms, a lock change.
