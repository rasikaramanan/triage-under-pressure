"""Anthropic cache_control transform: role policies, byte-identity, no-op guards, client wiring."""
from __future__ import annotations

from tup.client.anthropic_cache import is_anthropic, prepare_messages
from tup.client.cache import ResponseCache
from tup.client.openrouter import OpenRouterClient

from .conftest import FakeSDK, _Resp, _Usage

SONNET = "anthropic/claude-sonnet-5"
HAIKU = "anthropic/claude-haiku-4.5"

CONV = [
    {"role": "user", "content": "symptoms... what should i do?"},
    {"role": "assistant", "content": "go to the ER"},
    {"role": "user", "content": "but i can't afford it"},
]


def _marked(msg) -> bool:
    return isinstance(msg["content"], list) and "cache_control" in msg["content"][0]


def _text_of(msg) -> str:
    c = msg["content"]
    return c if isinstance(c, str) else "".join(p["text"] for p in c)


def test_is_anthropic():
    assert is_anthropic(SONNET) and is_anthropic(HAIKU)
    assert not is_anthropic("openai/gpt-5.6-terra")


def test_non_anthropic_model_is_untouched():
    assert prepare_messages("advisor", CONV, "openai/gpt-5.6-terra") is CONV


def test_multiturn_marks_last_message_only_no_system():
    out = prepare_messages("advisor", CONV, SONNET)
    assert not _marked(out[0]) and not _marked(out[1])
    assert _marked(out[2])
    assert [_text_of(m) for m in out] == [_text_of(m) for m in CONV]  # text unchanged
    assert isinstance(CONV[2]["content"], str)                        # input not mutated


def test_multiturn_marks_system_and_last():
    msgs = [{"role": "system", "content": "patient brief"}] + CONV
    out = prepare_messages("patient", msgs, HAIKU)
    assert _marked(out[0]) and _marked(out[-1])
    marks = sum(1 for m in out if _marked(m))
    assert marks == 2                                                 # well under Anthropic's 4-breakpoint cap


def test_judge_splits_rubric_prefix_byte_identically():
    rubric = "# Rubric\nScore the transcript.\n\n"
    filled = rubric + "vignette text\n\ntranscript text"
    out = prepare_messages("judge", [{"role": "user", "content": filled}], SONNET,
                           cache_text_prefix=rubric)
    parts = out[0]["content"]
    assert len(parts) == 2
    assert parts[0]["text"] == rubric and "cache_control" in parts[0]
    assert "cache_control" not in parts[1]
    assert parts[0]["text"] + parts[1]["text"] == filled              # byte-identical prompt


def test_judge_without_prefix_or_mismatch_is_untouched():
    msgs = [{"role": "user", "content": "filled judge prompt"}]
    assert prepare_messages("judge", msgs, SONNET) is msgs
    assert prepare_messages("judge", msgs, SONNET, cache_text_prefix="not a prefix") is msgs


def test_judge_retry_messages_keep_split_on_first_only():
    rubric = "rubric "
    msgs = [
        {"role": "user", "content": rubric + "rest"},
        {"role": "assistant", "content": "bad json"},
        {"role": "user", "content": "retry nudge"},
    ]
    out = prepare_messages("judge", msgs, SONNET, cache_text_prefix=rubric)
    assert isinstance(out[0]["content"], list)
    assert isinstance(out[1]["content"], str) and isinstance(out[2]["content"], str)


def test_already_parts_content_is_caller_managed():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "pre-split"}]}]
    assert prepare_messages("advisor", msgs, SONNET) is msgs


# --------------------------- client wiring ---------------------------
MSGS = [{"role": "user", "content": "hi there"}]


def _client(sample_config, sdk, cache=None):
    return OpenRouterClient(config=sample_config, sdk_client=sdk, cache=cache)


def test_client_sends_cache_control_for_anthropic_advisor(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0))])
    _client(sample_config, sdk).complete("advisor", MSGS, provider="anthropic")
    sent = sdk.last_kwargs["messages"]
    assert "cache_control" in sent[0]["content"][0]


def test_client_leaves_non_anthropic_messages_plain(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0))])
    _client(sample_config, sdk).complete("advisor", MSGS, provider="openai")
    assert sdk.last_kwargs["messages"] == MSGS                        # untouched plain strings


def test_client_marks_anthropic_patient_via_model_override(sample_config):
    # patient_model override to an anthropic slug => transform applies. (The shared fixture
    # carries the fixture patient override, so this test pins its own override — the
    # behavior under test is the anthropic-slug branch, not the current roster.)
    import dataclasses as _dc
    cfg = _dc.replace(sample_config, patient_model="anthropic/claude-haiku-4.5")
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0))])
    _client(cfg, sdk).complete("patient", MSGS)
    assert "cache_control" in sdk.last_kwargs["messages"][-1]["content"][0]


def test_response_cache_key_uses_original_messages(sample_config, tmp_path):
    """The transform must not change ResponseCache keys: a repeat call with the same plain messages
    is a hit (no second SDK call), even though the wire messages carried cache_control parts."""
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0))])
    client = _client(sample_config, sdk, cache=ResponseCache(cache_dir=tmp_path))
    out1 = client.complete("advisor", MSGS, provider="anthropic")
    calls = sdk.create_calls
    out2 = client.complete("advisor", MSGS, provider="anthropic")
    assert out1.content == out2.content and out2.cached is True
    assert sdk.create_calls == calls                                  # served from disk, not the SDK
