"""``results/README.md`` is the store's contract. This makes it EXECUTABLE: the contract table is
parsed here and checked against what a launch ACTUALLY produces. Adding a row to that table
without wiring a producer fails; wiring a producer without documenting it also fails.

The launch is ``--dry-run``: offline, mock SDK, $0.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "run_experiment.py"


def _contract_path() -> Path:
    """The contract lives at the store root — asked of the ENVIRONMENT's store, not assembled here.

    ``from_env()`` rather than a hardcoded ``<repo>/results``: that is the rule
    tup/tests/test_no_absolute_paths.py enforces, and it means this file follows TUP_RESULTS_ROOT
    like everything else instead of being the one place that knows where results/ lives.
    """
    from tup.store import Store
    return Store.from_env().root / "README.md"


CONTRACT = _contract_path()

#: Rows whose "when" column says the file is conditional. They must NOT appear in a clean run, and
#: each is asserted separately below by the condition that produces it.
CONDITIONAL = {
    "failures.jsonl": "only written when a cell fails after retries",
    "quarantine.json": "written by the post-run audit, by hand — not by a run",
}


def _contract_rows() -> list[tuple[str, str]]:
    """(file, when) from the 'What a live run writes' table in results/README.md."""
    text = CONTRACT.read_text(encoding="utf-8")
    section = text.split("## What a live run writes", 1)
    assert len(section) == 2, "results/README.md lost its 'What a live run writes' section"
    rows = []
    for line in section[1].splitlines():
        m = re.match(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            rows.append((m.group(1).strip(), m.group(2).strip()))
    assert rows, "the contract table parsed to zero rows — did its format change?"
    return rows


def _expected_paths(rows) -> set[str]:
    """Expand the table's `<arm>/x` shorthand into concrete relative paths for a two-arm run."""
    out = set()
    for name, _ in rows:
        if any(c in name for c in CONDITIONAL):
            continue
        if name.startswith("<arm>/"):
            leaf = name.split("/", 1)[1]
            out |= {f"main/{leaf}", f"context/{leaf}"}
        elif name.startswith("instrument/"):
            # The snapshot row is executable through the code it cites: the documented set IS
            # source_files() + the manifest, so the table and the writer cannot drift apart.
            from tup.orchestration.instrument import source_files
            out.add("instrument/manifest.json")
            out |= {f"instrument/{rel}" for rel in source_files()}
        else:
            out.add(name)
    return out


@pytest.fixture(scope="module")
def produced(tmp_path_factory):
    """One real --dry-run launch; returns (run_dir, set of relative file paths)."""
    root = tmp_path_factory.mktemp("store")
    env = {**__import__("os").environ, "TUP_RESULTS_ROOT": str(root)}
    r = subprocess.run(
        [sys.executable, str(LAUNCHER), "--run-name", "contract_probe", "--dry-run",
         "--max-spend", "5", "--max-turns", "8", "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--replicates-main", "1", "--replicates-context", "1"],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=900)
    assert r.returncode == 0, f"the launcher failed:\n{r.stdout}\n{r.stderr}"
    runs = list((root / "dry_runs").iterdir())
    assert len(runs) == 1, f"expected exactly one run directory, got {runs}"
    run_dir = runs[0]
    files = {str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file()}
    return run_dir, files


def test_every_promised_file_is_actually_written(produced):
    """A row in the contract with no producer is the defect this test exists to catch. (This
    certifies what a CURRENT launch writes; the released run predates invocation.json and the
    standalone sidecars, as its README records.)"""
    _, files = produced
    missing = sorted(_expected_paths(_contract_rows()) - files)
    assert not missing, (
        "results/README.md promises these, but a real launch does not write them:\n  "
        + "\n  ".join(missing))


def test_every_written_file_is_documented(produced):
    """The converse: a file appearing in a run directory that the contract never mentions."""
    _, files = produced
    documented = _expected_paths(_contract_rows()) | {
        f"{arm}/{leaf}" for arm in ("main", "context") for leaf in CONDITIONAL}
    documented |= {f"exclusions/{k}" for k in CONDITIONAL}
    undocumented = sorted(files - documented)
    assert not undocumented, (
        "a launch writes these, but results/README.md does not document them:\n  "
        + "\n  ".join(undocumented))


def test_conditional_files_are_absent_from_a_clean_run(produced):
    """`failures.jsonl` and `quarantine.json` must not appear just because a run happened.

    An empty-but-present quarantine.json in particular would read as 'audited, excluded nothing'
    when the truth is 'never audited' — a different claim about the data."""
    _, files = produced
    assert "main/failures.jsonl" not in files
    assert "exclusions/quarantine.json" not in files


def test_the_contract_table_covers_every_path_the_store_exposes():
    """ArmDir/RunDir advertise these paths as the layout. Any property added without a
    corresponding contract row is an undocumented promise waiting to go unwired."""
    from tup.store import ArmDir, RunDir
    documented = {n for n, _ in _contract_rows()}
    documented_leaves = {n.split("/")[-1] for n in documented}
    exposed = set()
    for cls in (ArmDir, RunDir):
        for attr in dir(cls):
            if attr.endswith("_path") and isinstance(getattr(cls, attr, None), property):
                exposed.add(attr)
    # map property name -> the filename the contract would use
    leaf_for = {
        "records_path": "records.jsonl", "guard_path": "guard.jsonl",
        "failures_path": "failures.jsonl", "manifest_path": "manifest.json",
        "audit_sample_path": "audit_sample.json",
        "lock_verification_path": "lock_verification.json", "log_path": "run.log",
        "invocation_path": "invocation.json", "readme_path": "README.md",
        "launch_cmd_path": "LAUNCH_CMD.txt", "quarantine_path": "quarantine.json",
        # The snapshot's manifest lives inside the `instrument/…` contract row, whose file set is
        # source_files() + manifest.json (see _expected_paths) rather than a per-file row.
        "instrument_manifest_path": "manifest.json",
    }
    unmapped = sorted(exposed - set(leaf_for))
    assert not unmapped, (
        f"tup.store exposes {unmapped} with no entry in this test's map — add the file to "
        f"results/README.md's contract table and to leaf_for, or it will never be checked.")
    undocumented = sorted(leaf_for[a] for a in exposed if leaf_for[a] not in documented_leaves)
    assert not undocumented, (
        "tup.store exposes these paths but results/README.md's table does not list them:\n  "
        + "\n  ".join(undocumented))


def test_a_dry_run_writes_nothing_outside_the_store_root(produced):
    """The store root is the ONLY place a run may write; no flag may redirect it."""
    run_dir, _ = produced
    root = run_dir.parent.parent
    assert run_dir.is_relative_to(root)
    # dry runs live under dry_runs/, never alongside real runs
    assert run_dir.parent.name == "dry_runs"
    assert not (root / "runs").exists()
