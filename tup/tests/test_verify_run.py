"""``scripts/verify_run.py`` — the checks that certify a run, themselves put under test.

WHY THIS FILE EXISTS

A verifier no test can fail is a comment, not a check: verify_run.py is the script that says
the experiment is complete and internally consistent, so something has to prove IT right. A verifier that cannot fail is not a verifier — so most of what is here perturbs a run and
asserts the perturbation is CAUGHT.

The end-to-end checks work on a store of SYMLINKS to the real run, with one arm replaced by a
mutated copy. That keeps them honest (the real 1,960-conversation data) without duplicating 40MB
per case.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify_run.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify_run as V  # noqa: E402

RUN_ID = "2026-08-06__full_experiment"


def _real_run() -> Path:
    """Asked of the ENVIRONMENT's store rather than assembled by hand — the rule
    tup/tests/test_no_absolute_paths.py enforces, and the reason this file cannot drift if the
    layout moves. The end-to-end cases skip when the store has no such run."""
    from tup.store import Store
    return Store.from_env().run(RUN_ID).path


REAL_RUN = _real_run()


# --------------------------------------------------------------------- pure pieces
def test_expected_ids_is_the_full_cross_product():
    class _V:
        def __init__(self, i): self.id = i
    vigs = [_V("001"), _V("002")]
    fams = [{"name": "control"}, {"name": "work"}]
    ids = V.expected_ids(vigs, fams, ["openai", "meta"], 3)
    assert len(ids) == 2 * 2 * 2 * 3
    assert "001__control__openai__r0" in ids and "002__work__meta__r2" in ids


def test_expected_ids_with_zero_replicates_is_empty_not_an_error():
    class _V:
        def __init__(self, i): self.id = i
    assert V.expected_ids([_V("001")], [{"name": "control"}], ["openai"], 0) == set()


def test_load_reports_every_unparseable_line_rather_than_stopping(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_text('{"conversation_id": "a"}\nNOT JSON\n{"conversation_id": "b"}\n{oops\n',
                 encoding="utf-8")
    V.FAILURES.clear()
    recs, bad = V.load(p)
    assert [r["conversation_id"] for r in recs] == ["a", "b"]
    assert bad == 2 and len(V.FAILURES) == 2
    V.FAILURES.clear()


def test_check_records_a_failure_with_its_detail():
    V.FAILURES.clear()
    V.check(True, "fine")
    assert V.FAILURES == []
    V.check(False, "broken", "5 != 6")
    assert V.FAILURES == ["broken: 5 != 6"]
    V.FAILURES.clear()


# --------------------------------------------------------------------- replicate resolution
class _FakeArm:
    def __init__(self, man): self._man = man
    def manifest(self): return self._man


class _FakeRun:
    def __init__(self, inv=None, mans=None):
        self._inv, self._mans = inv, mans or {}
    def invocation(self): return self._inv
    def arm(self, a): return _FakeArm(self._mans.get(a))


def test_replicates_come_from_the_invocation_first():
    run = _FakeRun(inv={"grid": {"replicates": {"main": 5, "context": 2}}})
    assert V._replicates_from(run, None) == {"main": 5, "context": 2}


def test_replicates_fall_back_to_each_arms_manifest():
    """A migrated run has no invocation.json; its manifests still record what it DID."""
    run = _FakeRun(inv=None, mans={"main": {"grid": {"replicates": 3}},
                                   "context": {"grid": {"replicates": 1}}})
    assert V._replicates_from(run, None) == {"main": 3, "context": 1}


def test_an_explicit_override_wins_over_both():
    run = _FakeRun(inv={"grid": {"replicates": {"main": 5, "context": 2}}})
    assert V._replicates_from(run, 9)["main"] == 9


def test_the_replicate_defaults_are_a_last_resort_and_say_so():
    """Assuming a replicate count silently is how a verifier certifies the wrong grid."""
    V.NOTES.clear()
    run = _FakeRun(inv=None, mans={})
    assert V._replicates_from(run, None) == {"main": 3, "context": 1}
    assert any("assumed" in n for n in V.NOTES)
    V.NOTES.clear()


def test_the_expected_judge_version_is_read_off_the_snapshot_lock(tmp_path):
    """The rubric is the one instrument file a finished run may be re-scored under, so the
    verifier asks the SNAPSHOT which version every verdict must carry — never a literal here."""
    iroot = tmp_path / "instrument"
    (iroot / "config").mkdir(parents=True)
    (iroot / "config" / "locked_stack.yaml").write_text("lock:\n  name: t\n  judge_prompt_version: 42\n")
    assert V.expected_judge_version(iroot) == 42


def test_a_legacy_run_falls_back_to_the_working_tree_lock():
    from tup.orchestration.stack_lock import load_lock
    assert V.expected_judge_version(None) == load_lock()["judge_prompt_version"]


# --------------------------------------------------------------------- end to end
def _run_verifier(root: Path):
    env = {**os.environ, "TUP_RESULTS_ROOT": str(root)}
    return subprocess.run([sys.executable, str(SCRIPT), RUN_ID], capture_output=True, text=True,
                          env=env, cwd=str(REPO_ROOT), timeout=900)


def _store_with_mutated_main(tmp_path: Path, mutate) -> Path:
    """A store that symlinks the real run, except main/records.jsonl which `mutate` rewrites."""
    root = tmp_path / "store"
    dest = root / "runs" / RUN_ID
    (dest / "main").mkdir(parents=True)
    for arm in ("main", "context"):
        for f in (REAL_RUN / arm).iterdir():
            if arm == "main" and f.name == "records.jsonl":
                continue
            target = dest / arm / f.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(f)
    for extra in ("exclusions", "README.md", "LAUNCH_CMD.txt", "instrument", "logs"):
        src = REAL_RUN / extra
        if src.exists():
            (dest / extra).symlink_to(src)
    lines = (REAL_RUN / "main" / "records.jsonl").read_text(encoding="utf-8").splitlines(True)
    (dest / "main" / "records.jsonl").write_text("".join(mutate(lines)), encoding="utf-8")
    return root


pytestmark_slow = pytest.mark.skipif(not REAL_RUN.exists(),
                                     reason="the completed experiment is not in this store")


@pytestmark_slow
def test_the_verifier_passes_on_the_real_experiment(tmp_path):
    r = _store_with_mutated_main(tmp_path, lambda lines: lines)   # unmutated control
    out = _run_verifier(r)
    assert out.returncode == 0, out.stdout[-3000:]
    assert "ALL CHECKS PASSED" in out.stdout


@pytestmark_slow
def test_verification_is_decoupled_from_the_working_tree():
    """The standing proof of the instrument snapshot's whole purpose.

    The working-tree instrument files (families.yaml among them) HAVE been edited since the run
    of record's snapshot was taken — comment-level cleanups across prompts/ and config/ — so the
    working tree permanently diverges from that snapshot, and the verifier passing (the test
    above) is only possible because it reads the snapshot.
    This test pins both halves explicitly: if a future change quietly re-points a provenance check
    at the working tree, the pass above would start failing; if someone "helpfully" syncs the
    snapshot to the working tree, the divergence assertion here fails instead — either way the
    regression is named, not silent.
    """
    from tup.orchestration.instrument import working_tree_divergence
    from tup.store import Store
    run = Store.from_env().run(RUN_ID)
    assert run.has_instrument(), "the run of record lost its instrument snapshot"
    diverged = working_tree_divergence(run.instrument_dir)
    assert "prompts/patient/families.yaml" in diverged, (
        "expected the working tree to have moved past the run-of-record snapshot "
        "(comment-level instrument edits since the run); if the snapshot was regenerated to match, "
        "the run's provenance has been overwritten — restore instrument/ from git")


@pytestmark_slow
def test_a_missing_conversation_is_caught(tmp_path):
    r = _store_with_mutated_main(tmp_path, lambda lines: lines[:-1])
    out = _run_verifier(r)
    assert out.returncode == 1
    assert "record count == full grid" in out.stdout and "every grid cell present" in out.stdout


@pytestmark_slow
def test_a_duplicated_conversation_is_caught(tmp_path):
    r = _store_with_mutated_main(tmp_path, lambda lines: lines + [lines[0]])
    out = _run_verifier(r)
    assert out.returncode == 1
    assert "no duplicate conversation_ids" in out.stdout


@pytestmark_slow
def test_a_torn_line_is_caught(tmp_path):
    r = _store_with_mutated_main(tmp_path, lambda lines: lines[:-1] + [lines[-1][:200]])
    out = _run_verifier(r)
    assert out.returncode == 1
    assert "every line parses as JSON" in out.stdout


@pytestmark_slow
def test_an_instrument_deviation_in_the_records_is_caught(tmp_path):
    """The core defect class: records carrying a framing the lock forbids."""
    def flip(lines):
        rec = json.loads(lines[0])
        rec["metadata"]["patient_framing"] = "roleswap"
        return [json.dumps(rec) + "\n"] + lines[1:]
    out = _run_verifier(_store_with_mutated_main(tmp_path, flip))
    assert out.returncode == 1
    assert "patient_framing == single_message" in out.stdout


@pytestmark_slow
def test_a_verdict_under_another_rubric_version_is_caught(tmp_path):
    """A record re-scored under a rubric the snapshot does not hold contradicts the snapshot."""
    def bump(lines):
        rec = json.loads(lines[0])
        rec["judgment"]["judge_prompt"]["version"] = rec["judgment"]["judge_prompt"]["version"] + 1
        return [json.dumps(rec) + "\n"] + lines[1:]
    out = _run_verifier(_store_with_mutated_main(tmp_path, bump))
    assert out.returncode == 1
    assert "judge prompt version ==" in out.stdout and "the snapshot lock" in out.stdout


@pytestmark_slow
def test_an_unjudged_conversation_is_caught(tmp_path):
    def unjudge(lines):
        rec = json.loads(lines[0])
        rec["judgment"] = {"status": "unparseable"}
        return [json.dumps(rec) + "\n"] + lines[1:]
    out = _run_verifier(_store_with_mutated_main(tmp_path, unjudge))
    assert out.returncode == 1
    assert "every record status == 'judged'" in out.stdout


def test_an_unknown_run_id_exits_cleanly_with_near_matches(tmp_path):
    env = {**os.environ, "TUP_RESULTS_ROOT": str(tmp_path)}
    out = subprocess.run([sys.executable, str(SCRIPT), "2026-08-06__no_such_run"],
                         capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=300)
    assert out.returncode == 2 and "no run" in out.stdout
