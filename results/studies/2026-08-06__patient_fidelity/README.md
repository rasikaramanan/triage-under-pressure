# 2026-08-06__patient_fidelity

status: STUDY — chose the patient simulator the experiment ran under

Five candidate patient models over one fixed 32-cell set. Moved the simulator off the advisor slate to llama-3.3-70b-instruct, which was best or tied-clean on every selection metric but one (audit-only cross-family flags, a log-only count outside the selection rule).

## Arms

- `incumbent_maverick/` — 32 conversations
- `llama33_70b/` — 32 conversations
- `mistral_small_32/` — 32 conversations
- `deepseek_v3/` — 32 conversations
- `qwen3_235b/` — 32 conversations

## Provenance

Migrated from the pre-store layout by `scripts/migrate_to_store.py`; every file was copied,
checksum-verified against its original (whole-file sha256, JSON line count, and the hashed
sorted set of conversation ids), and only then was the original removed. See
[docs/store_migration.md](../../../docs/store_migration.md).

**There is no `invocation.json`.** It records the fully-resolved INTENT of a run and is
written before the first dollar; it did not exist when this run executed, and it cannot be
reconstructed afterwards — a deliberately sliced grid and a crash part-way through one are
byte-identical on disk. Its absence is recorded rather than papered over, and it is why
`--continue` refuses a run that has none. The arms' `manifest.json` files record what each
arm actually DID, which is a different question.

The date in the run id is the date the run STARTED, from the earliest `metadata.started_at`
across its own records — not today's date and not a file mtime.

## Instrument snapshot

`instrument/` holds byte copies of the 35 prompt/config/vignette files this dataset's records were produced under. Every hash recorded in the 160 records (families bytes, rendered patient prompts, judge template, advisor context profiles where present) reproduces from the copied tree — the snapshot is proven, not asserted. Verification reads it instead of the working tree.
