"""Transcript model: judge rendering (numbering + boundaries), serialization, cost helpers."""
from __future__ import annotations

from tup.orchestration.transcript import Conversation, Turn, render_for_judge


def _conv() -> Conversation:
    turns = [
        Turn(speaker="patient", text="symptoms... what should i do?", runner_authored=True),
        Turn(speaker="advisor", text="How long has this gone on?", advisor_response_number=1),
        Turn(speaker="patient", text="a few hours, i can't afford the ER"),
        Turn(speaker="advisor", text="Go to the ER now.", advisor_response_number=2,
             usage={"cost": 0.002}),
    ]
    return Conversation(
        conversation_id="001__cost_medical_debt__openai__r0",
        vignette_id="001", condition_id=4, condition_name="cost_medical_debt",
        advisor_provider="openai", advisor_model="openai/gpt-5.6-terra",
        replicate=0, seed=20260626, turns=turns, metadata={"max_turns": 8},
    )


def test_render_for_judge_numbers_all_advisor_responses_including_question_only():
    r = render_for_judge(_conv().turns)
    assert "Advisor (response 1): How long has this gone on?" in r   # question-only turn IS numbered
    assert "Advisor (response 2): Go to the ER now." in r
    assert "Patient: a few hours, i can't afford the ER" in r


def test_render_ends_on_question_only_advisor_turn():
    turns = [
        Turn(speaker="patient", text="p", runner_authored=True),
        Turn(speaker="advisor", text="Any chest pain?", advisor_response_number=1),
    ]
    r = render_for_judge(turns)
    assert r.endswith("Advisor (response 1): Any chest pain?")


def test_render_empty_advisor_turn_shows_label_only():
    turns = [
        Turn(speaker="patient", text="p", runner_authored=True),
        Turn(speaker="advisor", text="", advisor_response_number=1),
    ]
    assert "Advisor (response 1): " in render_for_judge(turns)


def test_counts_and_cost():
    c = _conv()
    assert c.num_advisor_responses() == 2
    assert [t.advisor_response_number for t in c.advisor_turns()] == [1, 2]
    assert c.total_cost() == 0.002


def test_missing_cost_turns():
    turns = [
        Turn(speaker="patient", text="p", runner_authored=True),
        Turn(speaker="advisor", text="a1", advisor_response_number=1, usage={"cost": 0.001}),
        Turn(speaker="advisor", text="a2", advisor_response_number=2, usage={"cost": None}),       # API hit, no cost
        Turn(speaker="advisor", text="a3", advisor_response_number=3, usage={"cost": None}, cached=True),  # cached -> excluded
        Turn(speaker="advisor", text="a4", advisor_response_number=4, usage=None),                 # usage None -> excluded
    ]
    c = Conversation("id", "001", 0, "control", "openai", "m", 0, 1, turns, {})
    assert c.missing_cost_turns() == 1   # only a2
    assert c.total_cost() == 0.001       # lower bound when missing_cost_turns > 0


def test_to_dict_is_serializable():
    import json

    d = _conv().to_dict()
    assert d["conversation_id"] == "001__cost_medical_debt__openai__r0"
    assert d["condition_name"] == "cost_medical_debt"
    assert len(d["turns"]) == 4
    assert d["turns"][0]["runner_authored"] is True
    assert d["turns"][1]["advisor_response_number"] == 1
    json.dumps(d)  # must not raise
