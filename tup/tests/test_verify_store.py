"""``scripts/verify_store.py`` — the store-wide integrity check, tested by breaking things.

A checker that cannot fail is not a checker. Each test here plants one specific corruption in a
synthetic store and asserts it is caught; the last few assert that legitimate historical shapes are
NOT reported as corruption, because a check that cries wolf on every old run gets switched off.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_store.py"


def _rec(cid, *, context_arm="none", include_context_key=True):
    md = {"complete": True}
    if include_context_key:
        md["context_arm"] = context_arm
    return {"conversation_id": cid, "metadata": md}


def _seed(root: Path, run_id="2026-08-06__t", arm="main", recs=None, **files):
    """A minimal but VALID run, plus whatever extra files a test wants to plant."""
    from tup.store import Store
    a = Store(root).run(run_id).arm(arm)
    a.mkdir()
    recs = recs if recs is not None else [_rec("001__control__openai__r0")]
    a.records_path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    run = Store(root).run(run_id)
    run.readme_path.write_text(f"# {run_id}\n\nstatus: test\n", encoding="utf-8")
    for name, payload in files.items():
        target = {"guard": a.guard_path, "failures": a.failures_path,
                  "manifest": a.manifest_path, "audit_sample": a.audit_sample_path}[name]
        if name in ("guard", "failures"):
            target.write_text("".join(json.dumps(x) + "\n" for x in payload), encoding="utf-8")
        else:
            target.write_text(json.dumps(payload), encoding="utf-8")
    return root


def _check(root: Path):
    env = {**os.environ, "TUP_RESULTS_ROOT": str(root)}
    return subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True,
                          env=env, cwd=str(REPO_ROOT), timeout=600)


# --------------------------------------------------------------------- corruption is caught
def test_a_clean_store_passes(tmp_path):
    out = _check(_seed(tmp_path))
    assert out.returncode == 0 and "STORE OK" in out.stdout


def test_a_torn_line_is_caught(tmp_path):
    from tup.store import Store
    _seed(tmp_path)
    p = Store(tmp_path).run("2026-08-06__t").arm("main").records_path
    p.write_text(p.read_text() + '{"conversation_id": "trunc"\n', encoding="utf-8")
    out = _check(tmp_path)
    assert out.returncode == 1 and "unparseable" in out.stdout


def test_a_duplicate_conversation_id_is_caught(tmp_path):
    out = _check(_seed(tmp_path, recs=[_rec("a"), _rec("a")]))
    assert out.returncode == 1 and "duplicate conversation_id" in out.stdout


def test_records_contradicting_their_own_arm_directory_are_caught(tmp_path):
    """The defect the store layout exists to prevent: a record that disagrees with where it lives."""
    out = _check(_seed(tmp_path, arm="main", recs=[_rec("a", context_arm="barrier")]))
    assert out.returncode == 1 and "context_arm" in out.stdout


def test_a_manifest_disagreeing_with_the_records_is_caught(tmp_path):
    out = _check(_seed(tmp_path, recs=[_rec("a")],
                       manifest={"cost": {"n_conversations": 99}}))
    assert out.returncode == 1 and "manifest counts 99" in out.stdout


def test_a_manifest_naming_the_wrong_arm_is_caught(tmp_path):
    out = _check(_seed(tmp_path, recs=[_rec("a")], manifest={"arm": "context"}))
    assert out.returncode == 1 and "manifest says arm" in out.stdout


def test_an_orphaned_guard_entry_is_caught(tmp_path):
    out = _check(_seed(tmp_path, recs=[_rec("a")],
                       guard=[{"conversation_id": "not_a_real_conversation"}]))
    assert out.returncode == 1 and "guard entr" in out.stdout


def test_an_audit_sample_naming_an_unknown_conversation_is_caught(tmp_path):
    out = _check(_seed(tmp_path, recs=[_rec("a")],
                       audit_sample={"conversation_ids": ["ghost__x__y__r0"]}))
    assert out.returncode == 1 and "not in records under any id form" in out.stdout


def test_an_empty_records_file_is_caught(tmp_path):
    from tup.store import Store
    _seed(tmp_path)
    Store(tmp_path).run("2026-08-06__t").arm("main").records_path.write_text("", encoding="utf-8")
    out = _check(tmp_path)
    assert out.returncode == 1


def test_a_run_with_no_readme_is_caught(tmp_path):
    """No README means index.json can report no status for the run — it becomes unclassifiable."""
    from tup.store import Store
    _seed(tmp_path)
    Store(tmp_path).run("2026-08-06__t").readme_path.unlink()
    out = _check(tmp_path)
    assert out.returncode == 1 and "no README.md" in out.stdout


def test_a_stale_index_is_caught(tmp_path):
    _seed(tmp_path)
    (tmp_path / "index.json").write_text(json.dumps({"schema": "tup-results-index/1",
                                                     "n_runs": 0, "runs": [],
                                                     "n_studies": 0, "studies": []}),
                                         encoding="utf-8")
    out = _check(tmp_path)
    assert out.returncode == 1 and "index.json disagrees" in out.stdout


def test_a_quarantine_naming_an_unknown_conversation_is_caught(tmp_path):
    from tup.store import Store
    _seed(tmp_path, recs=[_rec("a")])
    run = Store(tmp_path).run("2026-08-06__t")
    run.exclusions_dir.mkdir(parents=True, exist_ok=True)
    run.quarantine_path.write_text(json.dumps({"main": ["ghost"], "ctx": []}), encoding="utf-8")
    out = _check(tmp_path)
    assert out.returncode == 1 and "unknown conversation" in out.stdout


# --------------------------------------------------------------------- legitimate shapes are not
def test_records_predating_the_context_arm_field_are_a_note_not_a_failure(tmp_path):
    """Pilot-era records have no context_arm key at all. Absent is not wrong, and a check that
    conflates them would fail on every historical run until someone silenced it."""
    out = _check(_seed(tmp_path, recs=[_rec("a", include_context_key=False)]))
    assert out.returncode == 0
    assert "predate the context_arm field" in out.stdout


def test_a_missing_manifest_is_a_note_not_a_failure(tmp_path):
    """A hard crash leaves records with no manifest; the records are still the data of record."""
    out = _check(_seed(tmp_path))
    assert out.returncode == 0 and "no manifest" in out.stdout


def test_notes_become_failures_under_strict(tmp_path):
    root = _seed(tmp_path)
    env = {**os.environ, "TUP_RESULTS_ROOT": str(root)}
    out = subprocess.run([sys.executable, str(SCRIPT), "--strict"], capture_output=True,
                         text=True, env=env, cwd=str(REPO_ROOT), timeout=600)
    assert out.returncode == 1 and "under --strict" in out.stdout


def test_an_unresolvable_failures_entry_is_only_a_note(tmp_path):
    """A recorded failure with no matching record is normal for an unfinished run."""
    out = _check(_seed(tmp_path, recs=[_rec("a")],
                       failures=[{"conversation_id": "never_succeeded"}]))
    assert out.returncode == 0
