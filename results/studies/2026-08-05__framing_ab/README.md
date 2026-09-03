# 2026-08-05__framing_ab

status: STUDY — chose the patient framing the experiment ran under

Matched-pair A/B. Role-swap framing quadruples the simulated patient's capitulation flags (0.304 vs 0.075 per conversation, p = 0.0005); its effect on measured degradation is inconclusive (14.5% vs 10.1%, McNemar p = 0.51). This is why the reported experiment was run under single-message framing; deleting it would leave that claim unbacked.

## Arms

- `roleswap/` — 92 conversations
- `single_message/` — 93 conversations

## Provenance

`launcher.py` (archived here) is the one-shot script that ran this study; the role-swap
framing it exercised has since been removed from the runner, so it cannot be re-run —
the records are the study.

Migrated from the pre-store layout by `scripts/migrate_to_store.py`; every file was copied,
checksum-verified against its original (whole-file sha256, JSON line count, and the hashed
sorted set of conversation ids), and only then was the original removed. See
[docs/store_migration.md](../../../docs/store_migration.md).

**There is no `invocation.json`.** It records the fully-resolved INTENT of a run and is
written before the first dollar; it did not exist when this run executed, and it cannot be
reconstructed afterwards — a deliberately sliced grid and a crash part-way through one are
byte-identical on disk. Its absence is recorded rather than papered over, and it is why
`--continue` refuses a run that has none. This study's arms carry no per-arm manifests
either (the launcher predates them); each arm is its `records.jsonl` and `guard.jsonl`.

The date in the run id is the date the run STARTED, from the earliest `metadata.started_at`
across its own records — not today's date and not a file mtime.

## Instrument snapshot

`instrument/` holds byte copies of the 35 prompt/config/vignette files this dataset's records were produced under. Every hash recorded in the 185 records (families bytes, rendered patient prompts, judge template, advisor context profiles where present) reproduces from the copied tree — the snapshot is proven, not asserted. Verification reads it instead of the working tree.
