"""The instrument snapshot: write-once byte copies that decouple verification from the working tree.

A run carries its own instrument under ``<run>/instrument/``, and ``verify_run.py`` proves prompt
provenance against that snapshot, never the working tree. The end-to-end proof lives in the repo's
standing state: the working-tree instrument files diverge from the run of record's snapshot and
``test_verify_run.py`` still passes on the real run. What this file covers is the machinery: write-once semantics, integrity, divergence reporting,
snapshot-rooted rendering, and the store-level reservation of the ``instrument/`` name.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tup.data.prompts import REPO_ROOT, load_families, render_patient_system
from tup.data.vignettes import load_vignette
from tup.orchestration.instrument import (source_files, verify_integrity, working_tree_divergence,
                                          write_snapshot)
from tup.store import StudyDir


@pytest.fixture(scope="module")
def snap(tmp_path_factory) -> Path:
    """One real snapshot of the repo's current instrument, shared by the read-only tests."""
    d = tmp_path_factory.mktemp("instr") / "instrument"
    write_snapshot(d)
    return d


def test_snapshot_carries_every_source_file_plus_manifest(snap):
    on_disk = {str(p.relative_to(snap)) for p in snap.rglob("*") if p.is_file()}
    assert on_disk == set(source_files()) | {"manifest.json"}


def test_snapshot_is_write_once(snap):
    with pytest.raises(FileExistsError):
        write_snapshot(snap)


def test_integrity_passes_on_a_fresh_snapshot(snap):
    assert verify_integrity(snap) == []


def test_integrity_catches_a_tampered_file(tmp_path):
    d = tmp_path / "instrument"
    write_snapshot(d)
    target = d / "prompts" / "patient" / "families.yaml"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    problems = verify_integrity(d)
    assert any("families.yaml" in p and "does not match" in p for p in problems)


def test_integrity_catches_a_missing_file(tmp_path):
    d = tmp_path / "instrument"
    write_snapshot(d)
    (d / "config" / "locked_stack.yaml").unlink()
    problems = verify_integrity(d)
    assert any("missing" in p and "locked_stack.yaml" in p for p in problems)


def test_integrity_without_a_manifest_is_a_named_problem(tmp_path):
    assert verify_integrity(tmp_path) == [f"no manifest at {tmp_path / 'manifest.json'}"]


def test_divergence_is_empty_when_the_tree_matches(snap):
    # The snapshot was just taken from this repo, so the repo trivially matches it.
    assert working_tree_divergence(snap, REPO_ROOT) == []


def test_divergence_names_exactly_the_drifted_file(snap, tmp_path):
    # Simulate a repo that moved on: a copy of the snapshot's own files IS a valid repo layout,
    # with one file edited the way a future instrument bump would edit it.
    fake_repo = tmp_path / "repo"
    for rel in source_files():
        dst = fake_repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((snap / rel).read_bytes())
    fam = fake_repo / "prompts" / "patient" / "families.yaml"
    fam.write_bytes(fam.read_bytes() + b"\n# a comment the run never saw\n")
    assert working_tree_divergence(snap, fake_repo) == ["prompts/patient/families.yaml"]


def test_rendering_from_the_snapshot_ignores_the_caller_repo(snap, tmp_path):
    """The decoupling in miniature: the render is a pure function of the ROOT it is given.

    Rendering twice from the same snapshot is byte-identical; rendering from a MUTATED copy of
    the snapshot changes the hash. Together these prove the passed root — never the caller's
    repo — is the render's input."""
    import shutil
    fams = load_families(root=snap)
    v = load_vignette("001", root=snap)
    fam = next(f for f in fams["families"] if f["name"] == "control")
    before = render_patient_system(v, fam, fams, root=snap).sha256
    again = render_patient_system(v, fam, fams, root=snap).sha256
    assert before == again
    assert before == hashlib.sha256(
        render_patient_system(v, fam, fams, root=snap).text.encode()).hexdigest()
    # mutate a COPY of the snapshot: the root is the input, so the hash must move
    snap2 = tmp_path / "mutated_snapshot"
    shutil.copytree(snap, snap2)
    fpath = snap2 / "prompts" / "patient" / "system.md"
    fpath.write_text(fpath.read_text(encoding="utf-8") + "\nEXTRA LINE", encoding="utf-8")
    fams2 = load_families(root=snap2)
    v2 = load_vignette("001", root=snap2)
    fam2 = next(f for f in fams2["families"] if f["name"] == "control")
    assert render_patient_system(v2, fam2, fams2, root=snap2).sha256 != before


def test_a_resume_refuses_a_snapshot_that_fails_its_own_manifest(tmp_path):
    """The launcher's resume gate: a tampered/rotted snapshot must stop a --continue cold —
    resuming would append conversations whose provenance the snapshot could no longer vouch for."""
    import os
    import subprocess
    import sys
    launcher = REPO_ROOT / "scripts" / "run_experiment.py"
    env = {**os.environ, "TUP_RESULTS_ROOT": str(tmp_path)}
    base = [sys.executable, str(launcher), "--dry-run", "--max-spend", "5", "--max-turns", "8",
            "--vignettes", "001", "--families", "control", "--advisors", "openai",
            "--replicates-main", "1", "--replicates-context", "1"]
    r = subprocess.run([*base, "--run-name", "gate_probe"], capture_output=True, text=True,
                       env=env, cwd=str(REPO_ROOT), timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    run_dir = next((tmp_path / "dry_runs").iterdir())
    # Make the run resumable (empty an arm's records) and rot the snapshot.
    (run_dir / "main" / "records.jsonl").write_text("")
    rubric = run_dir / "instrument" / "prompts" / "judge" / "system.md"
    rubric.write_bytes(rubric.read_bytes() + b"\n<!-- rot -->\n")
    r2 = subprocess.run([*base, "--continue", run_dir.name], capture_output=True, text=True,
                        env=env, cwd=str(REPO_ROOT), timeout=900)
    assert r2.returncode == 2, r2.stdout + r2.stderr
    assert "fails its own manifest" in r2.stdout


def test_study_arms_never_read_the_instrument_dir_as_an_arm(tmp_path):
    sd = StudyDir(tmp_path / "2026-01-01__probe", "2026-01-01__probe")
    (sd.path / "real_arm").mkdir(parents=True)
    (sd.path / "instrument").mkdir()
    assert [a.arm for a in sd.arms()] == ["real_arm"]
    with pytest.raises(ValueError, match="reserved"):
        sd.arm("instrument")
