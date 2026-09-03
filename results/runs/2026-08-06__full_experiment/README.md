# 2026-08-06__full_experiment

status: EXPERIMENT — the reported results

The 1,470 + 490 conversations the write-up reports. The quarantine set is EMPTY, and that is a finding of the post-run audit, not a missing file.

## Arms

- `main/` — 1470 conversations
- `context/` — 490 conversations

## Provenance

The run was produced under an earlier directory layout and moved here file-for-file (each file
checksum-verified against its original). The launch record preserved from that time
(`LAUNCH_CMD.txt`) names the run by its working name `redo_run` and by
pre-move paths such as `runs/redo_run.jsonl` (today's `main/records.jsonl`) and
`runs/redo_run_ctx.jsonl` (today's `context/records.jsonl`); this directory's name is the
identity of record.

**There is no `invocation.json`.** It records the fully-resolved INTENT of a run and is
written before the first dollar; it did not exist when this run executed, and it cannot be
reconstructed afterwards — a deliberately sliced grid and a crash part-way through one are
byte-identical on disk. `--continue` refuses a run that has none. The arms' `manifest.json`
files record what each arm actually DID, which is a different question.

The date in the run id is the date the run STARTED, from the earliest `metadata.started_at`
across its own records — not today's date and not a file mtime.

## Instrument snapshot

`instrument/` holds byte copies of the 35 prompt/config/vignette files this dataset's records were produced under. Every hash recorded in the 1,960 records (families bytes, rendered patient prompts, judge template, advisor context profiles where present) reproduces from the copied tree — the snapshot is proven, not asserted. Verification reads it instead of the working tree.
