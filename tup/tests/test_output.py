"""Output layer: persistence, by-family metrics, judge-inclusive cost, truncation, viewer.

All synthetic — no API. Records are built straight from ``Conversation``/``Turn`` + a Judgment dict so
the tests pin the persisted-record contract the aggregator/cost/viewer consume.
"""
from __future__ import annotations

import json

import pytest

from tup.orchestration.transcript import Conversation, Turn
from tup.output import cost, metrics, persist


def _turn(speaker, text, n=None, cost_usd=0.001, rt=0, truncated=False, cached=False,
          model="openai/gpt-5.6-terra", usage=True):
    u = None
    if usage:
        u = {"prompt_tokens": 40, "completion_tokens": 20, "cost": cost_usd, "reasoning_tokens": rt}
    return Turn(speaker, text, advisor_response_number=n, usage=u, truncated=truncated,
                cached=cached, model=model)


def _judgment(status="judged", init=1, tod=2, quote="wait", judge_cost=0.002, rt=300):
    if status == "judged":
        return {
            "status": "judged", "init_correct": init, "ToD": tod,
            "degraded_turn_quote": quote, "rationale": "r",
            "judge_provider": "xai", "judge_model": "x-ai/grok-4.3",
            "judge_prompt": {"path": "prompts/judge/system.md", "version": 8, "sha256": "a" * 64},
            "judge_usage": {"prompt_tokens": 100, "completion_tokens": 30, "cost": judge_cost,
                            "reasoning_tokens": rt},
            "attempts": 1, "raw": "{}", "error": None, "quote_verbatim": True,
        }
    if status == "skipped_incomplete":
        return {
            "status": "skipped_incomplete", "init_correct": None, "ToD": None,
            "degraded_turn_quote": None, "rationale": None, "judge_provider": None,
            "judge_model": None, "judge_prompt": {"version": 8, "sha256": "a" * 64},
            "judge_usage": None, "attempts": 0, "raw": None, "error": "empty@1",
            "quote_verbatim": None,
        }
    # unparseable (or panel_incomplete, via status=): a paid call was made (cost present), no clean parse
    return {
        "status": status, "init_correct": None, "ToD": None, "degraded_turn_quote": None,
        "rationale": None, "judge_provider": "xai", "judge_model": "x-ai/grok-4.3",
        "judge_prompt": {"version": 8, "sha256": "a" * 64},
        "judge_usage": {"prompt_tokens": 100, "completion_tokens": 5, "cost": judge_cost,
                        "reasoning_tokens": rt},
        "attempts": 2, "raw": "junk", "error": "no json", "quote_verbatim": None,
    }


def _conv(cid="c1", provider="openai", condition_id=4, *, n=2, complete=True,
          judgment=None, turn_cost=0.001, rt=0, truncated=False) -> Conversation:
    """Build a Conversation with ``n`` advisor responses (+ interleaved patient turns)."""
    turns = [_turn("patient", "symptoms... what should i do?", usage=False)]
    turns[0].runner_authored = True
    for i in range(1, n + 1):
        turns.append(_turn("advisor", f"go to the ER ({i})", n=i, cost_usd=turn_cost, rt=rt,
                           truncated=truncated))
        if i < n:
            turns.append(_turn("patient", f"i can't afford it ({i})", cost_usd=0.0001,
                               model="google/gemini-3.5-flash-lite"))
    c = Conversation(cid, "001", condition_id, "cost_medical_debt", provider, f"{provider}/m", 0,
                     12345, turns,
                     {"complete": complete, "aborted_reason": None if complete else "empty@1",
                      "vignette_condition": "Asthma"})
    c.judgment = judgment if judgment is not None else _judgment()
    return c


def _rec(*a, **k) -> dict:
    return _conv(*a, **k).to_dict()


# ----------------------------- persist -----------------------------
def test_save_load_roundtrip_preserves_judgment(tmp_path):
    convs = [_conv("c1"), _conv("c2", "anthropic", judgment=_judgment(init=0, tod="NA", quote=""))]
    p = persist.save_records(convs, tmp_path / "out.jsonl")
    back = persist.load_records(p)
    assert len(back) == 2
    assert back[0]["conversation_id"] == "c1"
    assert back[0]["judgment"]["status"] == "judged" and back[0]["judgment"]["ToD"] == 2
    assert back[1]["judgment"]["init_correct"] == 0 and back[1]["judgment"]["ToD"] == "NA"
    # full transcript + judge prompt sha survive the round-trip (PROJECT_SPEC.md section 14)
    assert back[0]["judgment"]["judge_prompt"]["sha256"] == "a" * 64
    assert [t["speaker"] for t in back[0]["turns"]][:2] == ["patient", "advisor"]


def test_append_record_accumulates_and_to_record_accepts_dict(tmp_path):
    p = tmp_path / "stream.jsonl"
    persist.append_record(_conv("c1"), p)
    persist.append_record(_rec("c2"), p)          # a dict record passes through unchanged
    back = persist.load_records(p)
    assert [r["conversation_id"] for r in back] == ["c1", "c2"]


def test_load_skips_blank_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    persist.save_records([_conv("c1")], p)
    with p.open("a") as f:
        f.write("\n   \n")
    assert len(persist.load_records(p)) == 1


# ----------------------------- cost --------------------------------
def test_turns_and_missing_cost_mirror_conversation_methods():
    c = _conv("c1", n=2)
    # inject one API turn with NO cost (not cached) -> a missing-cost turn
    c.turns.append(_turn("advisor", "addendum", n=3, cost_usd=None))
    r = c.to_dict()
    assert cost.turns_cost(r) == c.total_cost()
    assert cost.missing_cost_turns(r) == c.missing_cost_turns() == 1


def test_accumulate_includes_judge_cost():
    recs = [_rec("c1", turn_cost=0.001, n=2, judgment=_judgment(judge_cost=0.005))]
    rep = cost.accumulate(recs)
    # 2 advisor turns @0.001 + 1 patient @0.0001 = 0.0021 ; judge 0.005
    assert abs(rep.turns_usd - 0.0021) < 1e-9
    assert abs(rep.judge_usd - 0.005) < 1e-9
    assert abs(rep.total_usd - 0.0071) < 1e-9
    assert rep.n_conversations == 1 and not rep.is_lower_bound


def test_skipped_judge_has_no_cost_and_is_not_missing():
    r = _rec("c1", complete=False, judgment=_judgment(status="skipped_incomplete"))
    c_usd, missing = cost.judge_cost(r)
    assert c_usd == 0.0 and missing is False     # never sent => not a gap
    assert not cost.accumulate([r]).is_lower_bound


def test_unparseable_judge_cost_is_counted_but_flagged_lower_bound():
    # the unparseable fixture has attempts=2: the last attempt's cost is counted, but the earlier
    # billed attempt is not in judge_usage -> the total is a lower bound, so it must be flagged.
    r = _rec("c1", judgment=_judgment(status="unparseable", judge_cost=0.004))
    c_usd, incomplete = cost.judge_cost(r)
    assert c_usd == 0.004 and incomplete is True
    rep = cost.accumulate([r])
    assert rep.judge_usd == 0.004 and rep.judge_calls_missing_cost == 1 and rep.is_lower_bound


def test_single_attempt_judge_cost_not_flagged():
    r = _rec("c1", judgment=_judgment(judge_cost=0.004))     # attempts=1 (clean first parse)
    c_usd, incomplete = cost.judge_cost(r)
    assert c_usd == 0.004 and incomplete is False
    assert not cost.accumulate([r]).is_lower_bound


def test_complete_but_unjudged_flags_lower_bound():
    c = _conv("c1", judgment=None)            # complete conversation, judge never ran
    c.judgment = None
    r = c.to_dict()
    c_usd, incomplete = cost.judge_cost(r)
    assert c_usd == 0.0 and incomplete is True   # expected-but-missing judge call
    assert cost.accumulate([r]).is_lower_bound


def test_incomplete_unjudged_is_not_a_cost_gap():
    c = _conv("c1", complete=False, judgment=None)   # incomplete -> judge legitimately never sent
    c.judgment = None
    rep = cost.accumulate([c.to_dict()])
    assert rep.judge_calls_missing_cost == 0 and not rep.is_lower_bound


def test_lower_bound_flag_on_missing_turn_cost():
    c = _conv("c1")
    c.turns.append(_turn("advisor", "x", n=3, cost_usd=None))   # API turn, no cost
    rep = cost.accumulate([c.to_dict()])
    assert rep.missing_cost_turns == 1 and rep.is_lower_bound


def test_lower_bound_flag_when_judged_but_judge_cost_missing():
    j = _judgment()
    j["judge_usage"]["cost"] = None              # judged but cost absent
    rep = cost.accumulate([_rec("c1", judgment=j)])
    assert rep.judge_calls_missing_cost == 1 and rep.is_lower_bound


def test_cached_turn_without_recorded_cost_is_not_missing():
    c = _conv("c1")
    # a cached turn carrying no recorded cost is not a missing-cost gap (cache hits aren't billed again)
    c.turns.append(_turn("advisor", "x", n=3, cost_usd=None, cached=True))
    assert cost.missing_cost_turns(c.to_dict()) == 0


# ----------------------------- metrics -----------------------------
def test_cost_mirror_holds_with_cached_and_zero_cost_turns():
    c = _conv("c1", n=2)
    c.turns.append(_turn("advisor", "cached", n=3, cost_usd=None, cached=True))  # cache hit, no cost
    c.turns.append(_turn("advisor", "free", n=4, cost_usd=0.0))                  # zero-cost turn
    r = c.to_dict()
    assert cost.turns_cost(r) == c.total_cost()
    assert cost.missing_cost_turns(r) == c.missing_cost_turns()


def test_load_records_skips_torn_line_but_strict_raises(tmp_path, capsys):
    p = tmp_path / "torn.jsonl"
    persist.save_records([_conv("c1"), _conv("c2")], p)
    with p.open("a") as f:
        f.write('{"conversation_id":"c3","par')              # torn trailing line (killed mid-write)
    recovered = persist.load_records(p)
    assert [r["conversation_id"] for r in recovered] == ["c1", "c2"]   # prior progress preserved
    err = capsys.readouterr().err
    assert "torn trailing line" in err and "CORRUPT mid-file" not in err   # a clean tail is NOT mid-corruption
    with pytest.raises(json.JSONDecodeError):
        persist.load_records(p, strict=True)


def test_load_records_recovers_around_malformed_middle_and_torn_tail(tmp_path, capsys):
    # valid | MALFORMED MIDDLE (has newline) | valid | TORN TRAILING (no newline) — both kinds of corruption
    p = tmp_path / "corrupt.jsonl"
    good1 = json.dumps(persist.to_record(_conv("c1")), ensure_ascii=False)
    good2 = json.dumps(persist.to_record(_conv("c2")), ensure_ascii=False)
    p.write_text(good1 + "\n{ not valid json }\n" + good2 + "\n" + '{"conversation_id":"c3","par',
                 encoding="utf-8")

    recovered = persist.load_records(p)                                   # tolerant default
    assert [r["conversation_id"] for r in recovered] == ["c1", "c2"]      # both well-formed records recovered

    err = capsys.readouterr().err
    assert "CORRUPT mid-file" in err and "[2]" in err                    # the middle line (line 2) flagged LOUD
    assert "torn trailing line" in err and ":4" in err                   # the torn tail (line 4) flagged separately

    with pytest.raises(json.JSONDecodeError):                            # strict raises on the FIRST bad line
        persist.load_records(p, strict=True)


def test_append_after_torn_line_preserves_new_record(tmp_path):
    """a fresh append after a torn (newline-less) tail must not merge into it."""
    from tup.output.persist import append_record, load_records
    p = tmp_path / "torn_append.jsonl"
    append_record({"conversation_id": "A"}, p)
    with p.open("a", encoding="utf-8") as f:
        f.write('{"conversation_id": "B", "par')          # killed mid-write: no trailing newline
    append_record({"conversation_id": "C"}, p)
    recs = load_records(p)
    assert [r["conversation_id"] for r in recs] == ["A", "C"]   # C intact; only the torn B is lost


def test_exclusion_reason_panel_incomplete_not_malformed():
    r = _rec("p1", judgment={"status": "panel_incomplete", "init_correct": None, "ToD": None})
    assert not metrics.is_analyzable(r)
    assert metrics.exclusion_reason(r) == "panel_incomplete"


def test_malformed_judged_record_is_excluded_not_half_counted():
    r = _rec(judgment=_judgment(init=1, tod="not-an-int"))
    assert not metrics.is_analyzable(r)
    assert metrics.exclusion_reason(r) == "malformed"


def test_judged_missing_tod_key_is_malformed_not_a_crash():
    r = _rec(judgment=_judgment(init=1, tod=3))
    del r["judgment"]["ToD"]
    assert metrics.exclusion_reason(r) == "malformed"
    assert not metrics.is_analyzable(r)


def test_status_judged_with_init_none_is_excluded():
    r = _rec(judgment=_judgment(init=None, tod=None))
    assert not metrics.is_analyzable(r)
    assert metrics.exclusion_reason(r) == "malformed"
