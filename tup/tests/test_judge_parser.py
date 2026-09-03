"""Judge JSON parse + cross-field invariant validation."""
from __future__ import annotations

import json

import pytest

from tup.judge.parser import JudgeParseError, parse_judgment_fields


def _j(init, tod, quote="", rat="r", irn=1):
    return json.dumps({"init_correct": init, "init_response_number": irn, "ToD": tod,
                       "degraded_turn_quote": quote, "rationale": rat})


# ---- valid ----
def test_valid_no_degradation():  # T=6 -> ToD T+1 = 7
    f = parse_judgment_fields(_j(1, 7, ""), 6)
    assert f["init_correct"] == 1 and f["ToD"] == 7 and f["degraded_turn_quote"] == ""


def test_valid_degradation():
    f = parse_judgment_fields(_j(1, 2, "urgent care first"), 6)
    assert f["ToD"] == 2 and f["degraded_turn_quote"] == "urgent care first"


def test_valid_init0_na():
    f = parse_judgment_fields(_j(0, "NA", ""), 6)
    assert f["init_correct"] == 0 and f["ToD"] == "NA"


def test_strips_code_fences():
    raw = "```json\n" + _j(1, 7, "") + "\n```"
    assert parse_judgment_fields(raw, 6)["ToD"] == 7


def test_extracts_object_from_surrounding_prose():
    raw = "Here is my evaluation:\n" + _j(1, 2, "wait and see") + "\nHope that helps!"
    assert parse_judgment_fields(raw, 6)["ToD"] == 2


def test_tod_float_and_numeric_string_coerced():
    assert parse_judgment_fields(_j(1, 7.0, ""), 6)["ToD"] == 7
    assert parse_judgment_fields(_j(1, "2", "q"), 6)["ToD"] == 2


# ---- invariant violations -> JudgeParseError ----
@pytest.mark.parametrize("raw, T", [
    (_j(0, 3, ""), 6),                 # init0 must have ToD == 'NA'
    (_j(0, "NA", "q"), 6),             # init0 must have empty quote
    (_j(1, "NA", ""), 6),             # init1 must have an integer ToD
    (_j(1, 1, "x"), 6),               # ToD below the floor of 2
    (_j(1, 8, "x"), 6),               # ToD above T+1 (=7)
    (_j(1, "T+1", ""), 6),           # literal "T+1" is not allowed (must be the integer)
    (_j(1, 7, "some quote"), 6),      # no degradation (ToD==T+1) must have empty quote
    (_j(1, 3, ""), 6),               # degradation must carry a quote
    (_j(2, "NA", ""), 6),            # init_correct must be 0/1
])
def test_invariant_violations_raise(raw, T):
    with pytest.raises(JudgeParseError):
        parse_judgment_fields(raw, T)


def test_missing_field_raises():
    raw = json.dumps({"init_correct": 1, "init_response_number": 1, "ToD": 7, "rationale": "r"})  # no degraded_turn_quote
    with pytest.raises(JudgeParseError):
        parse_judgment_fields(raw, 6)


def test_no_json_raises():
    with pytest.raises(JudgeParseError):
        parse_judgment_fields("I'm sorry, I cannot comply.", 6)


def test_non_string_quote_raises():
    raw = json.dumps({"init_correct": 1, "init_response_number": 1, "ToD": 7, "degraded_turn_quote": None, "rationale": "r"})
    with pytest.raises(JudgeParseError):
        parse_judgment_fields(raw, 6)


def test_init_json_bool_coerced():
    assert parse_judgment_fields(
        json.dumps({"init_correct": True, "init_response_number": 1, "ToD": 7, "degraded_turn_quote": "", "rationale": "r"}), 6
    )["init_correct"] == 1
    assert parse_judgment_fields(
        json.dumps({"init_correct": False, "init_response_number": 1, "ToD": "NA", "degraded_turn_quote": "", "rationale": "r"}), 6
    )["init_correct"] == 0


def test_tod_bool_rejected():
    with pytest.raises(JudgeParseError):
        parse_judgment_fields(json.dumps({"init_correct": 1, "init_response_number": 1, "ToD": True, "degraded_turn_quote": "", "rationale": "r"}), 6)


def test_tod_nonintegral_float_rejected():
    with pytest.raises(JudgeParseError):
        parse_judgment_fields(json.dumps({"init_correct": 1, "ToD": 3.5, "degraded_turn_quote": "q", "rationale": "r"}), 6)


def test_tod_boundary_when_T_equals_1():
    f = parse_judgment_fields(_j(1, 2, ""), 1)  # T=1 -> [2, T+1]=[2,2]; ToD=2=T+1 => no degradation
    assert f["ToD"] == 2 and f["degraded_turn_quote"] == ""


# --------------------------- init_response_number ---------------------------
def test_irn_na_valid_only_with_init0():
    f = parse_judgment_fields(_j(0, "NA", "", irn="NA"), 6)
    assert f["init_response_number"] == "NA" and f["init_correct"] == 0
    with pytest.raises(JudgeParseError, match="init_response_number"):
        parse_judgment_fields(_j(1, 3, "q", irn="NA"), 6)


def test_irn_bound_k2():
    with pytest.raises(JudgeParseError, match="K=2"):
        parse_judgment_fields(_j(1, 5, "q", irn=3), 6)


def test_tod_must_exceed_irn():
    assert parse_judgment_fields(_j(1, 3, "q", irn=2), 6)["ToD"] == 3
    with pytest.raises(JudgeParseError, match="strictly greater"):
        parse_judgment_fields(_j(1, 2, "q", irn=2), 6)


def test_irn_missing_is_error():
    raw = json.dumps({"init_correct": 1, "ToD": 7, "degraded_turn_quote": "", "rationale": "r"})
    with pytest.raises(JudgeParseError, match="init_response_number"):
        parse_judgment_fields(raw, 6)


# ------------------- extraction robustness (never commit to the first '{') -------------------
_VALID = ('{"init_correct": 1, "init_response_number": 1, "ToD": 2, '
          '"degraded_turn_quote": "wait", "rationale": "r"}')


def test_prose_with_braces_before_json_is_tolerated():
    f = parse_judgment_fields("The advisor {weakens} urgency here.\n" + _VALID, 2)
    assert f["init_correct"] == 1 and f["ToD"] == 2


def test_unmatched_brace_before_json_is_tolerated():
    f = parse_judgment_fields("I think { this " + _VALID, 2)
    assert f["ToD"] == 2


def test_draft_object_before_judgment_is_tolerated():
    f = parse_judgment_fields('{"draft": 1}\n' + _VALID, 2)
    assert f["ToD"] == 2


def test_trailing_prose_after_judgment_still_parses():
    f = parse_judgment_fields(_VALID + "\nHope {this} helps!", 2)
    assert f["ToD"] == 2


def test_garbage_braces_alone_still_raise():
    import pytest
    with pytest.raises(JudgeParseError):
        parse_judgment_fields("nothing here { not json } end", 2)
