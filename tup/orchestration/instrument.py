"""The instrument snapshot: byte copies of the files a run's prompts were built from.

WHY THIS EXISTS

Without a snapshot, verifying a finished run would re-derive its prompt provenance from the
WORKING TREE — hashing today's ``prompts/patient/families.yaml`` and re-rendering the patient
prompts from today's files. That couples a finished, immutable run's verifiability to the current
state of the repo: editing a single comment in ``families.yaml`` (whose recorded hash covers raw
bytes) would make the run stop verifying, freezing the file; and the day the instrument
legitimately evolves, every check on an earlier run would go red.

So a run carries its own instrument: at preflight, before the first dollar, the launcher copies
the files below into ``<run>/instrument/``, mirroring the repo layout, and writes a manifest of
their sha256s. Verification reads the snapshot, never the working tree — the repo can move on, and
the run stays verifiable from its own directory alone (which is also what a public artifact needs:
no git archaeology, one command, offline).

WHAT IS SNAPSHOTTED — exactly the files prompt rendering and the lock consume:

  - ``prompts/patient/system.md``          the patient template (rendered hash recorded per record)
  - ``prompts/patient/families.yaml``      condition content (raw-byte hash recorded per record)
  - ``prompts/advisor/system.md``          empty body = the proof of advisor Option A
  - ``prompts/advisor/context_profiles.yaml``  the context arm's advisor system message
  - ``prompts/judge/system.md``            the rubric (template-body hash recorded per verdict)
  - ``config/locked_stack.yaml``           the lock the run was asserted against
  - ``config/models.yaml``                 the roster — the verifier checks recorded slugs against
    it, and reading the working tree's copy would re-couple a finished run to a roster that may
    legitimately change after a run
  - ``vignettes/*.md`` + ``vignettes/provenance/*.md``   opener text + patient_background — both
    are inputs to the rendered patient prompt (the provenance frontmatter carries the background
    facts and the pairing clauses)

Only files a run's rendering actually reads are snapshotted.

The snapshot is WRITE-ONCE. A resume verifies the working tree still byte-matches the snapshot and
refuses to mix instruments; it never rewrites. A run without a snapshot is legacy —
``verify_run.py`` says so and skips what it can no longer prove. (The released run of record
carries a backfilled, hash-validated snapshot; its own README records that provenance.)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from tup.data.prompts import REPO_ROOT

SCHEMA = "tup.instrument/1"

#: Repo-relative fixed files. Vignette files are globbed (the set is closed at 14, but a snapshot
#: records what is actually there rather than assuming).
FIXED_FILES = (
    "prompts/patient/system.md",
    "prompts/patient/families.yaml",
    "prompts/advisor/system.md",
    "prompts/advisor/context_profiles.yaml",
    "prompts/judge/system.md",
    "config/locked_stack.yaml",
    "config/models.yaml",
)


def _sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Repo-relative paths of every file the snapshot must carry."""
    out = list(FIXED_FILES)
    vdir = repo_root / "vignettes"
    for pattern in ("[0-9][0-9][0-9]_*.md", "provenance/[0-9][0-9][0-9]_*.md"):
        out += sorted(str(p.relative_to(repo_root)) for p in vdir.glob(pattern))
    return out


def write_snapshot(instrument_dir: Path, repo_root: Path = REPO_ROOT, *,
                   note: str | None = None) -> dict:
    """Copy the instrument into ``instrument_dir`` and write its manifest. Write-once.

    Returns the manifest. Raises ``FileExistsError`` if a manifest is already present — a snapshot
    is the record of what launch saw, and rewriting it would replace one run's provenance with
    another's, the same defect class ``invocation.json``'s exclusive create exists to prevent.
    """
    manifest_path = instrument_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"{manifest_path} already exists — a snapshot is write-once")
    files: dict[str, str] = {}
    for rel in source_files(repo_root):
        src = repo_root / rel
        dst = instrument_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        dst.write_bytes(data)
        files[rel] = hashlib.sha256(data).hexdigest()
    manifest = {"schema": SCHEMA,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": files}
    if note:
        manifest["note"] = note
    with open(manifest_path, "x", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return manifest


def read_manifest(instrument_dir: Path) -> dict | None:
    p = instrument_dir / "manifest.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def verify_integrity(instrument_dir: Path) -> list[str]:
    """The snapshot's own self-consistency: every manifest entry present and hash-true.

    Catches a snapshot that was tampered with or partially copied — the run-level provenance
    checks in ``scripts/verify_run.py`` then compare RECORDED hashes against these files.
    """
    manifest = read_manifest(instrument_dir)
    if manifest is None:
        return [f"no manifest at {instrument_dir / 'manifest.json'}"]
    problems = []
    for rel, want in sorted(manifest.get("files", {}).items()):
        p = instrument_dir / rel
        if not p.exists():
            problems.append(f"missing from snapshot: {rel}")
        elif _sha_file(p) != want:
            problems.append(f"snapshot file does not match its manifest hash: {rel}")
    return problems


def working_tree_divergence(instrument_dir: Path, repo_root: Path = REPO_ROOT) -> list[str]:
    """Which snapshot files the working tree no longer byte-matches.

    For a FINISHED run this is informational: a past run must keep verifying after the
    instrument legitimately evolves, so divergence is a statement about the repo's present,
    not about the run's integrity. A RESUME is different — mixing instruments within one run
    is forbidden, so the launcher treats a non-empty result as a hard error (scripts/
    run_experiment.py)."""
    manifest = read_manifest(instrument_dir)
    if manifest is None:
        return []
    diverged = []
    for rel, want in sorted(manifest.get("files", {}).items()):
        p = repo_root / rel
        if not p.exists() or _sha_file(p) != want:
            diverged.append(rel)
    return diverged
