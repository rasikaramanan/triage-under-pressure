"""Tests for scripts/run_experiment.py's ``main()`` — the CLI layer itself.

``run_experiment.py`` assembles every parameter the run executes with, and ``test_harness.py``
calls ``driver.run_arm`` directly, so argument plumbing, preflight ordering, slice shapes, and
the resume guard are covered here and nowhere else.

The CLI under test takes ``--run-name`` XOR ``--continue``, mandatory
``--max-spend``/``--max-turns``, and runs BOTH arms (main then context) of ONE run in a single
invocation unless ``--arms`` narrows it. Every data path resolves through ``tup.store.Store``,
whose root is ``TUP_RESULTS_ROOT`` — never a flag.

Everything here runs OFFLINE via ``--dry-run`` (mock SDK, $0) and writes only under ``tmp_path``
(via ``TUP_RESULTS_ROOT``). Most tests stub the driver (``cli.run_arm``)
so no conversations are generated; the last one exercises the whole path end to end so the plumbing
is proven, not just inspected.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import run_experiment as cli  # noqa: E402

from tup.client.config import load_config  # noqa: E402
from tup.data.prompts import load_families  # noqa: E402
from tup.data.vignettes import load_vignettes  # noqa: E402
from tup.store import Store  # noqa: E402

LOCKED_MAX_TURNS = "8"  # config/locked_stack.yaml — every test that isn't testing the lock itself
#                         must pass this or the general assert_locked_stack() preflight refuses it.


# ---- environment ------------------------------------------------------------

@pytest.fixture(autouse=True)
def _store_root(tmp_path, monkeypatch):
    """Every path in the new API resolves through TUP_RESULTS_ROOT — never a flag (tup/store.py).

    Autouse so every test in this file writes only under its own tmp_path, with no per-test
    boilerplate; tests that need to inspect the store construct ``Store(tmp_path)`` directly.
    """
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))


# ---- harness ---------------------------------------------------------------

class _FakeCost:
    def __init__(self, total_usd: float = 0.0):
        self.total_usd = total_usd


class _FakeReport:
    """Minimal stand-in for driver.RunReport — main() reads .aborted, .failed, .cost.total_usd,
    .summary() (the ``.cost.total_usd`` read matters: the launcher accumulates spend across
    arms within one invocation via ``prior_spend``, so the fake must carry a cost object too)."""

    def __init__(self, *, aborted: bool = False, failed: int = 0, total_usd: float = 0.0):
        self.aborted = aborted
        self.failed = failed
        self.cost = _FakeCost(total_usd)

    def summary(self) -> str:
        return "fake report"


@pytest.fixture
def capture_driver(monkeypatch):
    """Stub ``driver.run_arm`` (imported into the CLI module as ``cli.run_arm``) and record every
    call main() makes to it, as a LIST of ``{"client", "arm_dir", "kwargs"}``.

    A list, not a single dict: the new launcher can call run_arm once PER ARM in one invocation
    (main then context — see scripts/run_experiment.py's module docstring), so a test asserting "the CLI
    never reached the driver" checks ``capture_driver == []`` and a test asserting per-arm wiring
    indexes ``capture_driver[i]``. ``arm_dir`` is the second positional arg — a ``tup.store.ArmDir``
    — a store-owned ArmDir, never a caller-chosen path.
    """
    calls: list = []

    def _fake(client, arm_dir, **kw):
        calls.append({"client": client, "arm_dir": arm_dir, "kwargs": kw})
        return _FakeReport()

    monkeypatch.setattr(cli, "run_arm", _fake)
    return calls


def _cli(monkeypatch, capsys, *argv) -> tuple[int, str]:
    """Invoke main() with the given argv; return (exit code, combined stdout+stderr)."""
    monkeypatch.setattr(sys, "argv", ["run_experiment.py", *argv])
    code = 0
    try:
        cli.main()
    except SystemExit as e:  # main() always exits
        code = 0 if e.code is None else int(e.code)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _sole_run_id(tmp_path, *, dry_run: bool = True) -> str:
    ids = Store(tmp_path).list_runs(dry_run=dry_run)
    assert len(ids) == 1, f"expected exactly one run, found {ids}"
    return ids[0]


def _edit_invocation(tmp_path, run_id: str, **stack_lock_checked_overrides) -> None:
    """Hand-edit a written invocation.json's ``stack_lock.checked`` — simulating a run that was
    ORIGINALLY commissioned under a different instrument than the one resolved right now. The
    write-once invocation record carries the commissioned instrument, so the only way to test "resuming a run commissioned differently" is to seed a
    plausible history rather than pass conflicting flags to a fresh launch."""
    inv_path = Store(tmp_path).run(run_id, dry_run=True).invocation_path
    inv = json.loads(inv_path.read_text(encoding="utf-8"))
    inv.setdefault("stack_lock", {}).setdefault("checked", {}).update(stack_lock_checked_overrides)
    inv_path.write_text(json.dumps(inv), encoding="utf-8")


# ---- slice-filter validation (the --families crash class) ------------------

def test_unknown_family_name_is_rejected_before_any_spend(monkeypatch, capsys, capture_driver):
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--families", "bogus_family")
    assert code == 2
    assert "unknown condition name(s)" in out    # user-facing vocabulary is "condition", not "family"
    assert "hospital_fear" in out                # the message lists what IS known
    assert capture_driver == []                  # aborted before the driver was reached


def test_unknown_vignette_id_is_rejected_before_any_spend(monkeypatch, capsys, capture_driver):
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "999")
    assert code == 2
    assert "unknown vignette id(s)" in out
    assert capture_driver == []


def test_family_slice_reaches_the_driver_as_dicts_not_names(monkeypatch, capsys, capture_driver):
    """The driver indexes fam["name"], so a family slice must reach it as dicts, never as names."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "hospital_fear,control", "--advisors", "openai",
                   "--replicates-main", "1")
    assert code == 0
    fams = capture_driver[0]["kwargs"]["families"]
    assert [f["name"] for f in fams] == ["hospital_fear", "control"]  # indexable, not str; order kept


def test_vignette_slice_reaches_the_driver_as_objects_not_ids(monkeypatch, capsys, capture_driver):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    assert [v.id for v in capture_driver[0]["kwargs"]["vignettes"]] == ["001"]


def test_no_slice_flags_passes_the_full_roster_to_the_driver(monkeypatch, capsys, capture_driver):
    """The CLI always resolves vignettes/families/advisors to concrete objects and always
    passes them — there is no "omit the kwarg and let the driver default" path. The property
    that matters: an unsliced launch touches every vignette/family/advisor, not a silently
    shrunk subset. --max-spend is generous (1,470 main-arm cells at the deliberately-high estimate)."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "200",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main")
    assert code == 0
    kw = capture_driver[0]["kwargs"]
    assert sorted(v.id for v in kw["vignettes"]) == sorted(v.id for v in load_vignettes())
    assert [f["name"] for f in kw["families"]] == [f["name"] for f in load_families()["families"]]
    assert kw["advisors"] == list(load_config().advisors)


# ---- the locked stack is actually PASSED, not merely defaulted -------------

def test_launcher_asserts_patient_framing_explicitly(monkeypatch, capsys, capture_driver):
    """patient_framing is the one lock term with no resolver in resolve_current(), so enforcement
    depends entirely on the launcher asserting it. Assert it does — by value, in the lock record
    handed to the driver.
    """
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    assert capture_driver[0]["kwargs"]["stack_lock"]["checked"]["patient_framing"] == "single_message"


def test_launcher_passes_the_lock_record_through_to_the_run(monkeypatch, capsys, capture_driver):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    lock = capture_driver[0]["kwargs"]["stack_lock"]
    assert lock["mismatches"] == [] and lock["overridden"] is False
    for term in ("patient_framing", "max_turns", "n_families", "guard_version"):
        assert term in lock["checked"]


def test_an_unlocked_deviation_is_refused_without_the_unlock_flag(monkeypatch, capsys,
                                                                  capture_driver):
    # Sliced + --arms main so the budget preflight (which runs BEFORE the instrument-lock
    # check) clears comfortably on the small grid, and the lock violation is what actually fires.
    # --max-turns 2 deviates from the locked 8.
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", "2", "--arms", "main",
                     "--vignettes", "001", "--families", "control", "--advisors", "openai",
                     "--replicates-main", "1")
    assert code == 2
    assert "LOCKED STACK VIOLATION" in out
    assert capture_driver == []


def test_a_deviation_with_unlock_is_recorded_as_an_override(monkeypatch, capsys,
                                                            capture_driver):
    """A deliberate deviation must run, and must be permanently self-identifying in the output."""
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", "2",
                     "--unlock-stack", "--arms", "main", "--vignettes", "001",
                     "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    assert "OVERRIDDEN" in out
    assert capture_driver[0]["kwargs"]["max_turns"] == 2
    lock = capture_driver[0]["kwargs"]["stack_lock"]
    assert lock["overridden"] is True and lock["mismatches"]


# ---- the resume/continue instrument guard (the launch-blocking defect) -----
#
# A run's commissioned intent lives once, write-only, in invocation.json
# (tup/harness/invocation.py), and --continue re-reads it. To simulate "this run
# was commissioned under a different instrument" we launch a real run and then hand-edit its
# invocation.json's stack_lock.checked block (see ``_edit_invocation`` above).

def test_continue_refuses_a_run_with_no_invocation_json(monkeypatch, capsys, tmp_path,
                                                         capture_driver):
    """A run directory with no invocation.json at all (e.g. a crash before the write-once
    record landed) is refused rather than guessed at, because a sliced grid and a crash are
    byte-identical on disk without the recorded intent."""
    run_id = "2026-01-01__ghost"
    Store(tmp_path).run(run_id, dry_run=True).path.mkdir(parents=True)
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "no invocation.json" in out
    assert capture_driver == []


def test_continue_instrument_guard_catches_a_files_derived_drift(monkeypatch, capsys, tmp_path,
                                                                  capture_driver):
    """families_version is resolved live from the files every launch (tup.orchestration.stack_lock.
    resolve_current) — so a run recorded as commissioned under an older families_version than the
    code now resolves must be refused, not silently resumed under the new instrument."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "3")
    assert code == 0
    run_id = _sole_run_id(tmp_path)
    _edit_invocation(tmp_path, run_id, families_version=1)   # any value differing from the live families version (16) trips the guard

    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "different instrument" in msg and "families_version" in msg
    assert len(capture_driver) == 1   # only the first (seeding) launch reached the driver


def test_continue_refuses_a_patient_framing_drift(monkeypatch, capsys, tmp_path, capture_driver):
    """The resume guard compares this invocation's own resolved lock record — which carries every
    term actually asserted, ``patient_framing`` included — against the commissioned run's, so a
    framing drift is refused even though the framing is a property of the invocation, not of any
    file."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "3")
    assert code == 0
    run_id = _sole_run_id(tmp_path)
    _edit_invocation(tmp_path, run_id, patient_framing="roleswap")

    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "different instrument" in msg and "patient_framing" in msg


def test_continue_cannot_resume_an_arm_the_run_was_not_commissioned_with(monkeypatch, capsys,
                                                                         tmp_path, capture_driver):
    """Arm/context mixing across a resume is structurally guarded: an arm's context condition
    is derived from its NAME
    (tup.harness.invocation.ARM_CONTEXT), so the two cannot disagree — the analogous risk left
    at the CLI layer is --continue naming an arm the run's invocation.json never included, which
    resolve_arms_to_continue refuses (tested directly in test_invocation.py; this proves the CLI
    surfaces that refusal correctly)."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    run_id = _sole_run_id(tmp_path)

    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--arms", "context")
    assert code == 2
    assert "never included" in msg
    assert len(capture_driver) == 1


def test_continue_accepts_an_unmodified_run_and_resumes_it(monkeypatch, capsys, tmp_path,
                                                             capture_driver):
    """The guard must not be so strict it refuses a legitimate resume of its own run."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "3")
    assert code == 0
    run_id = _sole_run_id(tmp_path)

    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS)
    assert code == 0
    assert len(capture_driver) == 2   # seed launch + resume
    resumed = capture_driver[1]
    assert resumed["arm_dir"].arm == "main"
    assert resumed["kwargs"]["replicates"] == 3


# ---- never overwrite: relaunching a taken run name mints a new run ---------

def test_relaunching_the_same_run_name_mints_a_new_run_instead_of_overwriting(monkeypatch, capsys,
                                                                          tmp_path,
                                                                          capture_driver):
    """There is no --no-resume: nothing in the store ever truncates (tup/store.py's module
    docstring); the capability in its place is minting. Proven here by seeding real records (the
    stub never writes any) under the first run's main arm, relaunching with the identical
    --run-name, and checking (a) a SECOND run id is minted rather than the first one gaining
    more records, and (b) the first run's file is byte-identical afterwards."""
    args = ("--dry-run", "--run-name", "full_experiment", "--max-spend", "5", "--max-turns", LOCKED_MAX_TURNS,
            "--arms", "main", "--vignettes", "001", "--families", "control",
            "--advisors", "openai", "--replicates-main", "1")
    code, _ = _cli(monkeypatch, capsys, *args)
    assert code == 0
    first_id = _sole_run_id(tmp_path)
    first_arm = Store(tmp_path).run(first_id, dry_run=True).arm("main")
    first_arm.mkdir()
    first_arm.records_path.write_text(json.dumps({"conversation_id": "001__control__openai__r0"})
                                      + "\n", encoding="utf-8")
    before = first_arm.records_path.read_text(encoding="utf-8")

    code, out = _cli(monkeypatch, capsys, *args)
    assert code == 0
    assert "already has records" in out
    assert f"creating {first_id}__2" in out
    ids = Store(tmp_path).list_runs(dry_run=True)
    assert set(ids) == {first_id, f"{first_id}__2"}
    assert first_arm.records_path.read_text(encoding="utf-8") == before   # untouched, not overwritten


# ---- arm / execution-mode wiring ------------------------------------------

def test_context_arm_is_written_to_its_own_arm_directory(monkeypatch, capsys, capture_driver):
    """An arm's identity is the ArmDir the store hands the driver (tup/store.py: `main/` and
    `context/` are sibling directories under one run), so arms cannot collide on one path by
    construction. --replicates-context is its own flag — each arm gets its own replicate count,
    per the design docstring."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "context", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-context", "2")
    assert code == 0
    assert len(capture_driver) == 1
    arm_dir = capture_driver[0]["arm_dir"]
    assert arm_dir.arm == "context" and arm_dir.path.name == "context"
    assert capture_driver[0]["kwargs"]["replicates"] == 2


def test_default_launch_runs_both_arms_main_first_with_their_own_replicate_counts(monkeypatch,
                                                                                   capsys,
                                                                                   capture_driver):
    """Without --arms the launcher runs BOTH arms of one run, main first —
    "if the cap or a crash bites, the primary estimand survives" (module docstring) — each with its
    own --replicates-main / --replicates-context (defaults 3 / 1)."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai")
    assert code == 0
    assert len(capture_driver) == 2
    main_call, context_call = capture_driver
    assert main_call["arm_dir"].arm == "main"
    assert main_call["kwargs"]["replicates"] == 3          # --replicates-main default
    assert context_call["arm_dir"].arm == "context"
    assert context_call["kwargs"]["replicates"] == 1        # --replicates-context default


def test_concurrency_is_passed_through_to_the_driver(monkeypatch, capsys, capture_driver):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1",
                   "--concurrency", "4")
    assert code == 0
    assert capture_driver[0]["kwargs"]["concurrency"] == 4


# ---- end to end through the real driver ------------------------------------

def test_a_sliced_dry_run_completes_end_to_end(monkeypatch, capsys, tmp_path):
    """No stub: the real driver runs a 2-cell slice offline, proving the whole CLI path works."""
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "slice", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                     "--families", "hospital_fear", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0, msg
    assert "cells considered: 2" in msg
    run_id = _sole_run_id(tmp_path)
    arm = Store(tmp_path).run(run_id, dry_run=True).arm("main")
    records = arm.records()
    assert len(records) == 2
    for r in records:
        assert r["metadata"]["patient_framing"] == "single_message"
        assert "hospital_fear" in r["conversation_id"]


# ---- new CLI surface: --run-name XOR --continue, mandatory budget/turns --------

def test_run_name_and_continue_are_mutually_exclusive(monkeypatch, capsys, capture_driver):
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--continue",
                     "2026-08-06__t", "--max-spend", "5", "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "not allowed with argument" in out
    assert capture_driver == []


def test_run_name_or_continue_is_required(monkeypatch, capsys, capture_driver):
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert capture_driver == []


@pytest.mark.parametrize("argv", [
    ["--dry-run", "--run-name", "t", "--max-turns", LOCKED_MAX_TURNS],   # missing --max-spend
    ["--dry-run", "--run-name", "t", "--max-spend", "5"],                 # missing --max-turns
    ["--dry-run", "--run-name", "t"],                                     # missing both
], ids=["no-max-spend", "no-max-turns", "no-budget-flags"])
def test_missing_max_spend_or_max_turns_exits_nonzero(monkeypatch, capsys, capture_driver, argv):
    code, _ = _cli(monkeypatch, capsys, *argv)
    assert code != 0
    assert capture_driver == []


def test_run_name_containing_double_underscore_is_rejected(monkeypatch, capsys, capture_driver):
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "redo__run", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "reserved as the run-id field separator" in out
    assert capture_driver == []


def test_continue_on_unknown_run_id_fails_with_near_matches(monkeypatch, capsys, tmp_path,
                                                             capture_driver):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "full_experiment", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    real_id = _sole_run_id(tmp_path)
    typo_id = real_id[:-1]   # a one-character-short typo of a real, existing run id

    code, out = _cli(monkeypatch, capsys, "--dry-run", "--continue", typo_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "no run" in out
    assert "did you mean" in out
    assert real_id in out
    assert len(capture_driver) == 1   # only the seeding launch reached the driver


def test_continue_with_a_contradicting_slice_fails(monkeypatch, capsys, tmp_path, capture_driver):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    run_id = _sole_run_id(tmp_path)

    code, out = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001")   # recorded ["001","002"]
    assert code == 2
    assert "commissioned with a different slice" in out
    assert "--vignettes" in out
    assert len(capture_driver) == 1


def test_resume_budget_preflight_refuses_a_cap_below_already_spent_plus_estimate(monkeypatch,
                                                                                  capsys, tmp_path,
                                                                                  capture_driver):
    """--max-spend is CUMULATIVE over the run, so a resume must count what the run already spent
    before it estimates what remains — the check that stops a resume cap smaller than what the
    run has ALREADY spent from passing preflight and then aborting on its first cell. The stub never writes real records, so "already spent" is seeded directly on disk."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--arms", "main", "--vignettes", "001,002",
                   "--families", "control", "--advisors", "openai", "--replicates-main", "1")
    assert code == 0
    run_id = _sole_run_id(tmp_path)
    main_arm = Store(tmp_path).run(run_id, dry_run=True).arm("main")
    main_arm.mkdir()
    # A conversation_id that is NOT one of this arm's expected cells (so the arm stays incomplete
    # and --continue still has work to do), carrying a real cost far above the low cap below.
    main_arm.records_path.write_text(
        json.dumps({"conversation_id": "seed__already_spent__r9",
                    "turns": [{"usage": {"cost": 1000.0}}]}) + "\n", encoding="utf-8")

    code, out = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 2
    assert "already spent" in out
    assert "is below the" in out
    assert "cumulative over the run" in out
    assert len(capture_driver) == 1   # only the seeding launch reached the driver


# ---- the run README: what makes a run classifiable at all -------------------------------------
# tup.store._read_status feeds index.json AND the viewer's smoke filter off this file's `status:`
# line. Without it every new run is statusless and unclassifiable.

def test_a_run_gets_a_readme_with_a_status_line(monkeypatch, capsys, tmp_path):
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
                   "--advisors", "openai")
    assert code == 0
    run = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True)
    assert run.readme_path.exists()
    text = run.readme_path.read_text()
    assert text.startswith(f"# {run.run_id}")
    assert any(l.startswith("status:") for l in text.splitlines())


def test_the_readme_status_is_what_the_store_reads_back(monkeypatch, capsys, tmp_path):
    """The contract that matters: _read_status must actually parse what the launcher wrote."""
    from tup.store import _read_status
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai")
    run = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True)
    assert _read_status(run) == "dry run (no spend, mock responses)"


def test_the_readme_names_every_arm_with_its_conversation_count(monkeypatch, capsys, tmp_path):
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--replicates-main", "2", "--replicates-context", "1")
    run = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True)
    text = run.readme_path.read_text()
    assert "`main/` — 2 conversations" in text
    assert "`context/` — 1 conversations" in text


def test_the_readme_surfaces_a_failed_lock_verification(monkeypatch, capsys, tmp_path):
    """A run whose RECORDS contradict the lock must say so where a human will read it."""
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                   "--max-turns", "2", "--vignettes", "001", "--families", "control",
                   "--advisors", "openai", "--unlock-stack")
    assert code == 0
    text = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True).readme_path.read_text()
    assert "LOCK VERIFICATION FAILED" in text and "max_turns" in text


def test_a_readme_failure_never_changes_the_run_exit_status(monkeypatch, capsys, tmp_path):
    """Presentation is not the run. A broken README writer must not fail a finished run.

    The fault is injected INSIDE the writer — ``ArmDir.lock_verification`` is read only by the
    README writer on this path — rather than by replacing the writer wholesale. Replacing it would
    step over the very try/except under test, and the test would pass no matter what the guard did.
    """
    from tup.store import ArmDir
    monkeypatch.setattr(ArmDir, "lock_verification",
                        lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    code, out = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001",
                     "--families", "control", "--advisors", "openai")
    assert code == 0                                    # the run still succeeded
    assert "could not write run README" in out          # ... and said so, once
    run = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True)
    assert run.arm("main").has_records()                # the DATA is intact regardless
    assert not run.readme_path.exists()


# ---- adversarial-execution gap coverage -----------------------------------------------------------

def test_an_unknown_advisor_is_rejected_before_a_run_id_is_minted(monkeypatch, capsys, tmp_path,
                                                                  capture_driver):
    """An advisor slug outside the configured roster is refused before any run id is minted or
    file written — validate_models() checks the roster, so the slice itself must be checked too."""
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--advisors", "openai,opnai")
    assert code == 2
    assert "unknown advisor" in msg and "opnai" in msg
    assert capture_driver == []                       # never reached the driver
    assert Store(tmp_path).list_runs(dry_run=True) == []   # ... and minted nothing


def test_replicates_alongside_continue_is_an_error_not_a_silent_no_op(monkeypatch, capsys,
                                                                     tmp_path, capture_driver):
    """`--continue X --replicates-main 5` is an error: a flag that would be accepted and then
    discarded must be refused instead."""
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--replicates-main", "1")
    run_id = _sole_run_id(tmp_path)
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--replicates-main", "5")
    assert code == 2
    assert "commissioned with replicates" in msg and "main=5" in msg


def test_continue_without_replicate_flags_resumes_with_the_recorded_count(monkeypatch, capsys,
                                                                          tmp_path, capture_driver):
    """The other half: saying nothing must resume using the COMMISSIONED counts, not the CLI
    defaults. With the driver stubbed nothing is persisted, so the resume re-runs the grid — and
    the replicate count it hands the driver is the one the run was commissioned with (2), not the
    launcher's default of 3."""
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--replicates-main", "2", "--arms", "main")
    run_id = _sole_run_id(tmp_path)
    capture_driver.clear()
    code, _ = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                   "--max-turns", LOCKED_MAX_TURNS)
    assert code == 0
    assert [c["arm_dir"].arm for c in capture_driver] == ["main"]
    assert capture_driver[0]["kwargs"]["replicates"] == 2


def test_an_aborted_main_arm_stops_the_run_before_the_context_arm(monkeypatch, capsys, tmp_path):
    """Main arm first exists so the PRIMARY estimand survives a cap or a crash. If main aborts,
    spending the remaining budget on the descriptive arm is the wrong trade."""
    calls: list = []

    class _Report:
        def __init__(self, aborted):
            self.aborted, self.failed, self.complete = aborted, 0, False
            self.n_cells = self.completed = self.skipped = self.audit_n = 0
            self.abort_reason = "--max-spend reached" if aborted else None
            self.cost = type("C", (), {"total_usd": 0.0})()

        def summary(self):
            return "stub"

    def _fake(client, arm_dir, **kw):
        calls.append(arm_dir.arm)
        return _Report(aborted=(arm_dir.arm == "main"))

    monkeypatch.setattr(cli, "run_arm", _fake)
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001",
                     "--families", "control", "--advisors", "openai")
    assert calls == ["main"]                      # context was never started
    assert "not starting the remaining arm" in msg
    assert code == 1                              # and the abort is reported, not swallowed


# ---- adversarial-execution regressions -------------------------------

@pytest.mark.parametrize("flag,value,needle", [
    ("--vignettes", "001,001", "more than once"),
    ("--advisors", "openai,openai", "more than once"),
    ("--families", "control,control", "more than once"),
])
def test_a_duplicated_slice_value_is_refused(monkeypatch, capsys, tmp_path, capture_driver,
                                             flag, value, needle):
    """A repeat puts the SAME cell in the grid twice. Under the default concurrency both are in
    flight at once, so the resume skip-if-done check cannot see the first before the second starts,
    and two records land under one conversation_id — inflating every count from that arm."""
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--families", "control", flag, value)
    assert code == 2 and needle in msg
    assert capture_driver == [] and Store(tmp_path).list_runs(dry_run=True) == []


@pytest.mark.parametrize("flag,value", [("--replicates-main", "0"), ("--replicates-main", "-1"),
                                        ("--replicates-context", "0")])
def test_a_replicate_count_below_one_is_refused(monkeypatch, capsys, tmp_path, capture_driver,
                                                flag, value):
    """A replicate count below one would commission a zero-cell arm that does nothing and reports
    itself complete; it is refused up front."""
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001",
                     "--families", "control", "--advisors", "openai", flag, value)
    assert code == 2 and "at least 1" in msg
    assert capture_driver == []


@pytest.mark.parametrize("value", [" ", ",", " , "])
def test_an_arms_value_resolving_to_nothing_is_refused(monkeypatch, capsys, tmp_path,
                                                       capture_driver, value):
    """An --arms value that resolves to no arm is refused rather than commissioning an empty run."""
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001",
                     "--families", "control", "--advisors", "openai", "--arms", value)
    assert code == 2 and "resolved to nothing" in msg
    assert capture_driver == []


def test_the_invocation_write_is_the_reservation_not_the_mint(monkeypatch, capsys, tmp_path,
                                                              capture_driver):
    """Minting only READS the disk. Two launches racing on one new date+run-name both see it free and
    the second overwrote the first's write-once record. The exclusive create makes the loser lose
    loudly. Simulated by planting the file between mint and write."""
    from tup.store import Store as _S
    real_mint = _S.mint_run_id_with_notice

    def racing_mint(self, run_name, date, *, dry_run=False):
        run_id, notice = real_mint(self, run_name, date, dry_run=dry_run)
        rd = self.run(run_id, dry_run=dry_run)          # another launcher gets there first
        rd.path.mkdir(parents=True, exist_ok=True)
        rd.invocation_path.write_text('{"run_name": "other"}', encoding="utf-8")
        return run_id, notice

    monkeypatch.setattr(_S, "mint_run_id_with_notice", racing_mint)
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001",
                     "--families", "control", "--advisors", "openai")
    assert code == 2 and "took" in msg and "first" in msg
    assert capture_driver == []
    # the other launcher's record is intact
    run = Store(tmp_path).run(_sole_run_id(tmp_path), dry_run=True)
    assert json.loads(run.invocation_path.read_text())["run_name"] == "other"


def test_continue_regenerates_end_of_arm_files_lost_to_a_crash(monkeypatch, capsys, tmp_path):
    """A crash between the last record and the manifest leaves an arm complete BY RECORDS with no
    manifest, audit_sample or lock_verification; --continue must regenerate them rather than
    report "nothing to do"."""
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--arms", "main")
    run_id = _sole_run_id(tmp_path)
    arm = Store(tmp_path).run(run_id, dry_run=True).arm("main")
    before = arm.records_path.read_bytes()
    for p in (arm.manifest_path, arm.audit_sample_path, arm.lock_verification_path):
        p.unlink()

    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS)
    assert code == 0
    assert "regenerating" in msg and "no conversations will be re-run" in msg
    assert arm.manifest_path.exists() and arm.audit_sample_path.exists()
    assert arm.lock_verification_path.exists()
    assert arm.records_path.read_bytes() == before      # nothing re-run, nothing appended


def test_a_contradicting_replicate_count_is_refused_even_when_the_run_is_complete(
        monkeypatch, capsys, tmp_path):
    """The replicate-count check runs before the 'nothing to do' early exit, so a complete run
    still refuses a contradicting flag."""
    _cli(monkeypatch, capsys, "--dry-run", "--run-name", "t", "--max-spend", "5",
         "--max-turns", LOCKED_MAX_TURNS, "--vignettes", "001", "--families", "control",
         "--advisors", "openai", "--replicates-main", "1", "--replicates-context", "1")
    run_id = _sole_run_id(tmp_path)
    code, msg = _cli(monkeypatch, capsys, "--dry-run", "--continue", run_id, "--max-spend", "5",
                     "--max-turns", LOCKED_MAX_TURNS, "--replicates-main", "7")
    assert code == 2 and "commissioned with replicates" in msg
