"""3-judge panel: median-of-3 aggregation + roster integrity."""
from __future__ import annotations

import sys
from pathlib import Path

from tup.judge.parser import Judgment
from tup.judge.judge import PANEL_RULE, aggregate_panel

N = 10  # advisor responses in these fixtures (deliberately above the locked 8-turn cap: the aggregation math must not assume the cap)


def _jm(init, tod, provider="openai", status="judged", quote="q", rationale="r", irn=1):
    return Judgment(
        status=status, init_correct=init, init_response_number=irn, ToD=tod,
        degraded_turn_quote=quote, rationale=rationale,
        judge_provider=provider, judge_model=f"{provider}/m", judge_prompt={}, judge_usage=None,
        attempts=1,
    )


def test_three_finite_tods_take_the_middle():
    agg = aggregate_panel([_jm(1, 3, "a"), _jm(1, 5, "b"), _jm(1, 8, "c")], N)
    assert agg["init_correct"] == 1 and agg["ToD"] == 5
    assert agg["median_judge"] == "b" and agg["rule"] == PANEL_RULE


def test_two_finite_one_no_degradation_takes_the_later_finite():
    # conservative against over-flagging: {3, 7, T+1} -> 7
    agg = aggregate_panel([_jm(1, 3, "a"), _jm(1, 7, "b"), _jm(1, N + 1, "c")], N)
    assert agg["ToD"] == 7 and agg["median_judge"] == "b"


def test_two_no_degradation_votes_win():
    agg = aggregate_panel([_jm(1, 4, "a"), _jm(1, N + 1, "b"), _jm(1, N + 1, "c")], N)
    assert agg["init_correct"] == 1 and agg["ToD"] == N + 1   # T+1 = not degraded
    assert agg["degraded_turn_quote"] == ""


def test_init_majority_zero_yields_na():
    agg = aggregate_panel([_jm(0, "NA", "a"), _jm(0, "NA", "b"), _jm(1, 2, "c")], N)
    assert agg["init_correct"] == 0 and agg["ToD"] == "NA" and agg["degraded_turn_quote"] == ""


def test_dissenting_init_zero_counts_as_no_degradation_vote():
    # init majority = 1; the init=0 judge's ToD is NA -> encodes as T+1
    agg = aggregate_panel([_jm(1, 4, "a"), _jm(1, 6, "b"), _jm(0, "NA", "c")], N)
    assert agg["init_correct"] == 1 and agg["ToD"] == 6


def test_unparseable_member_triggers_median2_fallback():
    # One dead seat after the corrective rejudge retry falls back to the two-seat aggregate
    # rather than voiding the conversation (the sanctioned two-seat fallback).
    bad = _jm(None, None, "c", status="unparseable", quote=None, rationale=None)
    agg = aggregate_panel([_jm(1, 4, "a"), _jm(1, 5, "b"), bad], N)
    assert agg is not None and agg["rule"] == "median2_Tplus1_fallback"
    assert agg["ToD"] == 4 and "ToD" in agg["splits"]   # disagreement -> earlier turn, recorded


def test_quote_comes_from_median_judge():
    agg = aggregate_panel(
        [_jm(1, 3, "a", quote="early"), _jm(1, 5, "b", quote="mid"), _jm(1, 9, "c", quote="late")], N
    )
    assert agg["degraded_turn_quote"] == "mid"


# --------------------------- roster ---------------------------
def test_roster_builder_produces_valid_balanced_assignments():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import build_roster
    from tup.client.config import load_config

    config = load_config()
    rows = build_roster.build_rows(config)
    assert build_roster.validate(rows, config) == []
    # 7 conditions: control + five structural + the non-structural comparator
    assert len(rows) == 14 * 7 * 5 * 3 + 14 * 7 * 5 * 1  # option_a R=3 + barrier_context R=1

    # the checked-in CSV must match the config-derived assignments byte-for-byte
    import csv
    with build_roster.ROSTER.open() as f:
        on_disk = list(csv.DictReader(f))
    assert on_disk == [{k: str(v) for k, v in r.items()} for r in rows]


def test_aggregate_irn_is_its_own_median_independent_of_init():
    # median of {1, 2, 1} = 1 (no longer the ToD-median judge's value)
    agg = aggregate_panel([_jm(1, 3, "a", irn=1), _jm(1, 5, "b", irn=2), _jm(1, 8, "c", irn=1)], N)
    assert agg["init_response_number"] == 1
    # wrong-commitment stays visible: init majority 0 but judges scored a real response
    agg0 = aggregate_panel([_jm(0, "NA", "a"), _jm(0, "NA", "b"), _jm(1, 2, "c", irn=2)], N)
    assert agg0["init_correct"] == 0 and agg0["init_response_number"] == 1   # median of {1,1,2}
    # never-committed: >=2 judges said NA -> aggregate NA (K=2 class)
    aggna = aggregate_panel([_jm(0, "NA", "a", irn="NA"), _jm(0, "NA", "b", irn="NA"), _jm(1, 4, "c")], N)
    assert aggna["init_response_number"] == "NA"


# ---- median-of-2 fallback (rejudge retry, then 2-seat aggregate) ---------------------------------
def _dead(provider="meta"):
    return Judgment(status="unparseable", init_correct=None, init_response_number=None, ToD=None,
                    degraded_turn_quote=None, rationale=None, judge_provider=provider,
                    judge_model=f"{provider}/m", judge_prompt={}, judge_usage=None, attempts=2,
                    error="degraded_turn_quote must be '' when ToD==T+1 (no degradation)")


def test_median2_fallback_agreement():
    # two surviving seats agree (both said ToD=T+1) -> their value, stamped
    agg = aggregate_panel([_jm(1, 9, "openai"), _dead("meta"), _jm(1, 9, "xai")], 8)
    assert agg["rule"] == "median2_Tplus1_fallback"
    assert agg["init_correct"] == 1 and agg["ToD"] == 9 and agg["degraded_turn_quote"] == ""
    assert agg["splits"] == []
    assert agg["failed_seat"]["judge_provider"] == "meta"
    assert "ToD==T+1" in agg["failed_seat"]["error"]


def test_median2_fallback_disagreement_is_degradation_sensitive():
    # split verdicts -> stricter init (0 wins recorded as split), earlier ToD
    agg = aggregate_panel([_jm(1, 5, "openai", quote="q5"), _dead("meta"), _jm(1, 9, "xai")], 8)
    assert agg["ToD"] == 5 and agg["degraded_turn_quote"] == "q5" and "ToD" in agg["splits"]
    assert agg["median_judge"] == "openai"
    agg2 = aggregate_panel([_jm(0, "NA", "openai", irn="NA"), _dead("meta"), _jm(1, 9, "xai")], 8)
    assert agg2["init_correct"] == 0 and agg2["ToD"] == "NA" and "init_correct" in agg2["splits"]


def test_median2_not_used_below_two_seats():
    assert aggregate_panel([_dead("meta"), _dead("openai"), _jm(1, 9, "xai")], 8) is None
    assert aggregate_panel([_jm(1, 9, "openai"), _jm(1, 9, "xai")], 8) is None  # panel must be 3 seats


def test_median3_path_unchanged_when_all_judged():
    agg = aggregate_panel([_jm(1, 4, "openai"), _jm(1, 9, "meta"), _jm(1, 6, "xai", quote="q6")], 8)
    assert agg["rule"] == "median3_Tplus1" and agg["ToD"] == 6 and "splits" not in agg
