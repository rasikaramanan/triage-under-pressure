"""The write-once invocation record, arm resolution, and the preflight spend estimate.

These pin down the two things the invocation record exists for (the released run predates it — its README says so):

  * reconstruct what a run was COMMISSIONED with (its manifests record only the last
    invocation — a resumed run's final backfill, not the original launch); and
  * tell a deliberate slice apart from a crash, which is impossible from records alone and is why
    ``--continue`` reads the recorded grid instead of re-deriving one.
"""
from __future__ import annotations

import json

import pytest

from tup.harness import estimate as est
from tup.harness.invocation import (
    ARM_CONTEXT,
    arm_state,
    build_grid,
    build_invocation,
    conflicting_slice,
    expected_cell_ids,
    resolve_arms_to_continue,
)
from tup.store import Store


def _inv(**over):
    base = dict(
        run_id="2026-08-05__t", started_at="2026-08-05T00:00:00Z", run_name="t", dry_run=True,
        vignettes=["001", "002"], families=["control", "work"], advisors=["openai"],
        replicates={"main": 2, "context": 1}, arms=["main", "context"], seed=42, concurrency=4,
        max_spend=10.0, estimate_usd=1.0, lock_record={"mismatches": []},
        slice_filters={"vignettes": None, "families": None, "advisors": None})
    base.update(over)
    return build_invocation(**base)


# --------------------------------------------------------------------------- grid
def test_grid_is_the_full_cross_product_in_driver_order():
    g = build_grid(["001"], ["control", "work"], ["openai", "meta"], 2)
    assert len(g) == 1 * 2 * 2 * 2
    assert g[0] == "001__control__openai__r0"
    # family innermost: the two families for one (vignette, advisor, replicate) are adjacent
    assert g[:2] == ["001__control__openai__r0", "001__work__openai__r0"]


def test_arms_get_their_own_replicate_count():
    inv = _inv()
    assert inv["grid"]["cells"]["main"] == 2 * 2 * 1 * 2      # replicates-main = 2
    assert inv["grid"]["cells"]["context"] == 2 * 2 * 1 * 1   # replicates-context = 1


def test_arm_context_mapping_is_derived_from_the_arm_name():
    assert ARM_CONTEXT == {"main": "none", "context": "barrier"}
    assert _inv()["grid"]["arm_context"] == {"main": "none", "context": "barrier"}


def test_expected_cell_ids_come_from_the_record_not_from_todays_roster():
    inv = _inv()
    ids = expected_cell_ids(inv, "main")
    assert "001__control__openai__r0" in ids and len(ids) == 8
    # Mutating the recorded grid must change the answer — proving it is READ, not recomputed.
    inv["grid"]["cell_ids"]["main"] = ["only__one__cell__r0"]
    assert expected_cell_ids(inv, "main") == {"only__one__cell__r0"}


def test_expected_cell_ids_raises_for_an_arm_the_run_never_had():
    with pytest.raises(KeyError):
        expected_cell_ids(_inv(arms=["main"]), "context")


def test_invocation_records_the_slice_as_requested():
    inv = _inv(slice_filters={"vignettes": ["001"], "families": None, "advisors": None})
    assert inv["slice"]["vignettes"] == ["001"]


def test_invocation_records_budget_and_seed():
    inv = _inv()
    assert inv["budget"] == {"max_spend_usd": 10.0, "estimate_usd": 1.0}
    assert inv["config"]["seed"] == 42


# --------------------------------------------------------------------------- arm state
def _seed(store, run_id, arm, ids):
    a = store.run(run_id, dry_run=True).arm(arm)
    a.mkdir()
    with a.records_path.open("a", encoding="utf-8") as f:
        for i in ids:
            f.write(json.dumps({"conversation_id": i}) + "\n")


def test_arm_state_derives_completion_from_records_with_no_manifest(tmp_path):
    """A hard crash leaves records.jsonl and NO manifest — completion must still be knowable."""
    s = Store(tmp_path)
    inv = _inv()
    _seed(s, "2026-08-05__t", "main", list(expected_cell_ids(inv, "main")))
    run = s.run("2026-08-05__t", dry_run=True)
    assert run.arm("main").manifest() is None          # no manifest at all
    st = arm_state(run, inv, "main")
    assert st["complete"] is True and st["missing"] == set()


def test_arm_state_reports_exactly_the_missing_cells(tmp_path):
    s = Store(tmp_path)
    inv = _inv()
    ids = sorted(expected_cell_ids(inv, "main"))
    _seed(s, "2026-08-05__t", "main", ids[:-2])
    st = arm_state(s.run("2026-08-05__t", dry_run=True), inv, "main")
    assert st["complete"] is False and st["missing"] == set(ids[-2:])


def test_a_permanently_failed_cell_still_counts_as_terminal(tmp_path):
    """Matches the driver: complete = expected <= (done | failed)."""
    s = Store(tmp_path)
    inv = _inv()
    ids = sorted(expected_cell_ids(inv, "main"))
    _seed(s, "2026-08-05__t", "main", ids[:-1])
    a = s.run("2026-08-05__t", dry_run=True).arm("main")
    a.failures_path.write_text(json.dumps({"conversation_id": ids[-1]}) + "\n", encoding="utf-8")
    assert arm_state(s.run("2026-08-05__t", dry_run=True), inv, "main")["complete"] is True


# --------------------------------------------------------------------------- --continue resolution
def test_continue_resumes_every_incomplete_arm(tmp_path):
    s = Store(tmp_path)
    inv = _inv()
    _seed(s, "2026-08-05__t", "main", list(expected_cell_ids(inv, "main")))   # main complete
    todo, _ = resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), inv)
    assert todo == ["context"]


def test_continue_with_both_arms_incomplete_runs_main_first(tmp_path):
    s = Store(tmp_path)
    todo, _ = resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), _inv())
    assert todo == ["main", "context"]


def test_arms_flag_narrows_but_never_widens(tmp_path):
    s = Store(tmp_path)
    inv = _inv()
    todo, _ = resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), inv, ["context"])
    assert todo == ["context"]


def test_arms_flag_cannot_name_an_arm_the_run_never_had(tmp_path):
    s = Store(tmp_path)
    with pytest.raises(ValueError, match="never included"):
        resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), _inv(arms=["main"]),
                                 ["context"])


def test_arms_flag_rejects_an_unknown_arm(tmp_path):
    s = Store(tmp_path)
    with pytest.raises(ValueError):
        resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), _inv(), ["sideways"])


def test_nothing_to_continue_when_every_arm_is_complete(tmp_path):
    s = Store(tmp_path)
    inv = _inv()
    for arm in ("main", "context"):
        _seed(s, "2026-08-05__t", arm, list(expected_cell_ids(inv, arm)))
    todo, _ = resolve_arms_to_continue(s.run("2026-08-05__t", dry_run=True), inv)
    assert todo == []


# --------------------------------------------------------------------------- slice conflicts
def test_a_matching_slice_is_not_a_conflict():
    inv = _inv(slice_filters={"vignettes": ["001"], "families": None, "advisors": None})
    assert conflicting_slice(inv, {"vignettes": ["001"]}) == []


def test_a_different_slice_on_continue_is_an_error_not_an_override():
    inv = _inv(slice_filters={"vignettes": ["001"], "families": None, "advisors": None})
    out = conflicting_slice(inv, {"vignettes": ["002"]})
    assert len(out) == 1 and "vignettes" in out[0]


def test_adding_a_slice_to_an_unsliced_run_is_a_conflict():
    inv = _inv()
    assert conflicting_slice(inv, {"advisors": ["openai"]})


def test_passing_no_slice_flags_is_never_a_conflict():
    inv = _inv(slice_filters={"vignettes": ["001"], "families": None, "advisors": None})
    assert conflicting_slice(inv, {"vignettes": None, "families": None, "advisors": None}) == []


# --------------------------------------------------------------------------- spend estimate
def test_estimate_scales_with_the_grid():
    assert est.estimate_usd(0) == 0
    assert est.estimate_usd(1000) == pytest.approx(1000 * est.USD_PER_CONVERSATION, rel=1e-6)


def test_estimate_errs_high_relative_to_the_measured_rate():
    """The measured rate is itself a lower bound, so the estimate must exceed it."""
    assert est.USD_PER_CONVERSATION > est.MEASURED_USD_PER_CONVERSATION
    assert est.UNDERCOUNT_ALLOWANCE > 1.0


def test_estimate_of_the_completed_experiment_exceeds_what_it_actually_cost():
    """1,960 conversations cost $153.23 in turns+judging (all-in $171.67 with the separately
    recorded guard spend) — the estimate must sit above the turns+judging cost, not below."""
    assert est.estimate_usd(1960) > 153.23


def test_cap_below_estimate_is_refused():
    assert est.exceeds_cap(est.estimate_usd(1000), 1.0) is True
    assert est.exceeds_cap(est.estimate_usd(10), 1000.0) is False


def test_preflight_line_names_estimate_cap_and_headroom():
    line = est.format_preflight(10.0, 100.0, n_conversations=100)[0]
    assert "estimate" in line and "cap" in line and "headroom" in line


def test_a_wildly_oversized_cap_warns_loudly():
    """An order-of-magnitude typo must be visible: $1,600 typed as $16,000."""
    out = "\n".join(est.format_preflight(10.0, 10_000.0, n_conversations=100))
    assert "!!" in out and "stop now" in out


def test_a_sane_cap_does_not_warn():
    out = "\n".join(est.format_preflight(100.0, 160.0, n_conversations=1000))
    assert "!!" not in out
