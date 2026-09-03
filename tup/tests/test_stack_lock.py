"""Tests for the locked-stack enforcement. A term locked only in prose is not locked; these pin
the three properties that make the lock executable:
  1. the runtime DEFAULT is the locked value;
  2. a resolved configuration that contradicts the lock raises before any spend;
  3. persisted records can be checked against the lock after the fact.
"""
from __future__ import annotations

import inspect

import pytest

from tup.harness import driver
from tup.orchestration import runner
from tup.orchestration.stack_lock import (
    StackLockError, assert_locked_stack, check, load_lock, resolve_current, verify_records,
)


def test_lock_file_declares_single_message_framing():
    lock = load_lock()
    assert lock["patient_framing"] == "single_message"
    assert lock.get("name") and lock.get("locked_on")


@pytest.mark.parametrize("func", [
    runner.run_conversation,
    driver._generate_and_judge,
])
def test_no_framing_parameter_exists(func):
    """The locked single_message framing is hardcoded: no caller can select another framing,
    so a framing deviation is unrepresentable rather than merely non-default."""
    assert "patient_framing" not in inspect.signature(func).parameters


def test_run_arm_has_no_default_for_any_locked_term():
    """``driver.run_arm`` goes further than defaulting to the locked
    value: max_spend, max_turns and replicates have NO
    default at all, so omitting any of them is a ``TypeError`` at the call site — before a single
    dollar is spent — rather than a silent fall-through to a stale value. That is a strictly
    stronger guarantee than "the default happens to be the locked one", which is all a
    defaulted signature could offer (and which is not
    strong enough: the caller-must-remember failure mode is exactly a default going unpassed).
    """
    sig = inspect.signature(driver.run_arm)
    for name in ("max_spend", "max_turns", "replicates"):
        param = sig.parameters[name]
        assert param.default is inspect.Parameter.empty, (
            f"driver.run_arm's {name!r} has a default ({param.default!r}); the locked-stack "
            "guarantee requires it to have none, so every caller must pass it explicitly"
        )
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"driver.run_arm's {name!r} must be keyword-only so a positional-argument reordering "
            "can't silently swap it with another required param"
        )


def test_current_files_resolve_to_the_locked_versions():
    """The repo's own prompt files must still match what the lock claims is locked."""
    assert check(resolve_current()) == []


def test_mismatch_fails_closed():
    with pytest.raises(StackLockError) as e:
        assert_locked_stack({"patient_framing": "roleswap"})
    msg = str(e.value)
    assert "LOCKED STACK VIOLATION" in msg
    assert "roleswap" in msg and "single_message" in msg


def test_override_is_allowed_but_recorded():
    rec = assert_locked_stack({"patient_framing": "roleswap"}, allow_override=True)
    assert rec["overridden"] is True
    assert any("patient_framing" in m for m in rec["mismatches"])


def test_compliant_config_passes_and_reports_provenance():
    rec = assert_locked_stack({"patient_framing": "single_message", "max_turns": 8})
    assert rec["mismatches"] == [] and rec["overridden"] is False
    assert rec["checked"]["patient_framing"] == "single_message"


def test_verify_records_catches_a_wrong_stack_run():
    """The post-hoc check that flags a wrong-instrument run within a second of it finishing."""
    bad = [{"metadata": {"patient_framing": "roleswap", "max_turns": 8,
                         "prompts": {"patient": {"version": 11}}}}] * 3
    res = verify_records(bad)
    assert res["ok"] is False
    assert any("patient_framing" in p for p in res["problems"])

    # patient prompt version must match the lock (v12 carries the US-locale anchor)
    good = [{"metadata": {"patient_framing": "single_message", "max_turns": 8,
                          "prompts": {"patient": {"version": 12}}}}] * 3
    assert verify_records(good)["ok"] is True


def test_verify_records_detects_a_mixed_stack_file():
    mixed = [{"metadata": {"patient_framing": "single_message"}},
             {"metadata": {"patient_framing": "roleswap"}}]
    res = verify_records(mixed)
    assert res["ok"] is False
    assert any("disagree" in p for p in res["problems"])


# ---- instrument provenance is recorded AND locked -------------------------------------------------
def test_guard_version_is_a_real_lock_term():
    """guard_version must RESOLVE (an unresolved lock term is inert — check() would skip it)."""
    from tup.orchestration.guard import GUARD_VERSION
    assert resolve_current().get("guard_version") == GUARD_VERSION
    assert check({**resolve_current(), "guard_version": "0.0.1-not-the-locked-rules"})


def test_families_provenance_is_recorded_with_a_hash():
    """A record must be able to say which barrier content produced it, even without a version bump."""
    from tup.data.prompts import load_families_info
    info = load_families_info()
    assert info["path"].endswith("families.yaml")
    assert info["version"] and len(info["sha256"]) == 64


def test_guard_metadata_carries_version_and_rule_fingerprint():
    from tup.orchestration.guard import GUARD_VERSION, rules_fingerprint
    assert len(rules_fingerprint()) == 64
    assert GUARD_VERSION  # emitted into every conversation's guard block by as_metadata()


def test_every_declared_lock_term_is_actually_asserted_on_a_default_launch():
    """The lock must not declare terms it silently skips.

    check() only compares keys present in BOTH the lock and the resolved config, so a term
    nothing resolves is inert — it reads as a lock but enforces nothing. Adding a term to
    locked_stack.yaml without a resolver fails here.
    """
    meta = {"name", "locked_on", "rationale"}
    lock = load_lock()
    # what a launch hands the checker beyond resolve_current(): the framing (scripts/run_experiment.py
    # passes it by value; --max-turns is a required flag and is passed too, but it also resolves)
    merged = {**resolve_current(), "patient_framing": "single_message"}
    unasserted = sorted(k for k in lock if k not in meta and k not in merged)
    assert unasserted == [], f"locked terms that assert nothing: {unasserted}"


def test_locked_turn_cap_and_family_count_fail_closed():
    """Negative control: drift in either term must be caught, not skipped."""
    merged = {**resolve_current(), "patient_framing": "single_message"}
    assert check({**merged, "max_turns": 10}), "a drifted turn cap must be reported"
    assert check({**merged, "n_families": 6}), "a vanished family must be reported"
    assert check(merged) == [], "the current tree must itself be compliant"


