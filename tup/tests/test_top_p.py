"""Effective-top_p provenance + live-verification gate (PROJECT_SPEC.md section 14 reproducibility). No network.

The live OpenRouter fetch is exercised by monkeypatching ``urllib.request.urlopen`` (like the client
tests mock the SDK); ``verify_top_p`` is otherwise driven with injected ``live_facts`` so the drift
logic is tested deterministically and offline.
"""
from __future__ import annotations

import dataclasses
import json

from tup.client import top_p as T
from tup.client.top_p import (
    EFFECTIVE_TOP_P,
    effective_top_p_record,
    fetch_live_facts,
    verify_top_p,
)


def _guard_cfg(sample_config):
    """The conftest config plus the guard slug — EFFECTIVE_TOP_P carries a guard-only entry
    (google/gemini-3.5-flash-lite), so full-consistency checks need a config that declares it."""
    return dataclasses.replace(sample_config, guard_model="google/gemini-3.5-flash-lite")


def _matching_facts() -> dict:
    """Live facts that exactly agree with the recorded provenance (the no-drift baseline)."""
    return {
        slug: {
            "present": True,
            "models_accepts_top_p": rec["accepts_top_p"],
            "endpoint_top_p": {rec["accepts_top_p"]},
            "providers": set(rec["provider"]),
        }
        for slug, rec in EFFECTIVE_TOP_P.items()
    }


# ----------------------------- the recorded record -----------------------------
def test_record_covers_config_and_is_all_1_0(sample_config):
    rec = effective_top_p_record()
    models = rec["models"]
    # every configured slug has provenance, and every effective value is 1.0 (the established finding)
    for slug in set(sample_config.providers.values()):
        assert slug in models, f"{slug} missing from EFFECTIVE_TOP_P"
        assert models[slug]["top_p"] == 1.0
    assert rec["openrouter_default_top_p"] == 1.0
    assert rec["last_verified"] == T.LAST_VERIFIED


def test_record_is_deep_copied():
    rec = effective_top_p_record()
    rec["models"]["x-ai/grok-4.3"]["top_p"] = 0.123     # mutate the returned copy
    assert EFFECTIVE_TOP_P["x-ai/grok-4.3"]["top_p"] == 1.0  # module table is untouched


def test_reasoning_models_unconfigurable_not_injected():
    # Whole GPT-5.x line + Sonnet 5 reject sampling params (verified 2026-07-31)
    for slug in ("openai/gpt-5.6-terra", "anthropic/claude-sonnet-5"):
        rec = EFFECTIVE_TOP_P[slug]
        assert rec["accepts_top_p"] is False
        assert "UNCONFIGURABLE" in rec["basis"]


def test_gemini_pin_and_divergence_are_recorded():
    rec = EFFECTIVE_TOP_P["google/gemini-3.6-flash"]
    assert rec["accepts_top_p"] is True and rec["top_p"] == 1.0
    assert rec["pinned_provider"] == "Google AI Studio"          # routing pin fixes the effective value
    assert "0.95" in rec["native_default_note"]                  # the Vertex-route divergence is captured


def test_pinned_entry_tolerates_split_endpoints_but_not_lost_pin(sample_config):
    cfg = _guard_cfg(sample_config)
    facts = _matching_facts()
    facts["google/gemini-3.6-flash"]["endpoint_top_p"] = {True, False}   # the real live state
    ok, drift = verify_top_p(live=True, live_facts=facts, config=cfg)
    assert ok and drift == []                                    # pin replaces the unanimity check
    facts["google/gemini-3.6-flash"]["providers"] = {"Google"}   # AI Studio vanishes
    ok, drift = verify_top_p(live=True, live_facts=facts, config=cfg)
    assert not ok and any("pinned provider" in d for d in drift)


# ----------------------------- verify_top_p: consistent -----------------------------
def test_verify_offline_consistent_with_config(sample_config):
    ok, drift = verify_top_p(live=False, config=_guard_cfg(sample_config))
    assert ok and drift == []


def test_verify_offline_flags_guardless_config_as_stale_entry(sample_config):
    # a config with NO guard_model must surface the guard-only provenance row as stale-extra
    ok, drift = verify_top_p(live=False, config=sample_config)
    assert not ok and any("gemini-3.5-flash-lite" in d for d in drift)


def test_verify_live_no_drift_when_facts_match(sample_config):
    ok, drift = verify_top_p(live=True, live_facts=_matching_facts(), config=_guard_cfg(sample_config))
    assert ok and drift == []


# ----------------------------- verify_top_p: drift -----------------------------
def test_drift_when_model_missing(sample_config):
    facts = _matching_facts()
    facts["x-ai/grok-4.3"] = {"present": False}
    ok, drift = verify_top_p(live=True, live_facts=facts, config=sample_config)
    assert not ok and any("NOT FOUND" in d for d in drift)


def test_drift_when_top_p_acceptance_flips(sample_config):
    # a model suddenly stops accepting top_p -> its effective value changes (injected 1.0 -> upstream default)
    facts = _matching_facts()
    facts["meta-llama/llama-4-maverick"]["models_accepts_top_p"] = False
    facts["meta-llama/llama-4-maverick"]["endpoint_top_p"] = {False}
    ok, drift = verify_top_p(live=True, live_facts=facts, config=sample_config)
    assert not ok and any("acceptance changed" in d and "maverick" in d for d in drift)


def test_drift_when_endpoints_disagree(sample_config):
    facts = _matching_facts()
    facts["meta-llama/llama-4-maverick"]["endpoint_top_p"] = {True, False}   # split routing (no pin => drift)
    ok, drift = verify_top_p(live=True, live_facts=facts, config=sample_config)
    assert not ok and any("disagree on top_p" in d for d in drift)


def test_drift_when_providers_change(sample_config):
    facts = _matching_facts()
    facts["x-ai/grok-4.3"]["providers"] = {"xAI", "SomeNewHost"}
    ok, drift = verify_top_p(live=True, live_facts=facts, config=sample_config)
    assert not ok and any("routing changed" in d and "SomeNewHost" in d for d in drift)


def test_drift_when_config_has_model_without_provenance(sample_config):
    cfg = dataclasses.replace(
        sample_config,
        providers={**sample_config.providers, "openai": "openai/some-unlisted-model"},
    )
    ok, drift = verify_top_p(live=False, config=cfg)
    assert not ok and any("no top_p provenance" in d for d in drift)


# ----------------------------- fetch_live_facts parsing (mocked urllib) -----------------------------
class _FakeHTTP:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_live_facts_parses_models_and_endpoints(monkeypatch):
    models_payload = {"data": [
        {"id": "x-ai/grok-4.3", "supported_parameters": ["temperature", "top_p"]},
        {"id": "openai/gpt-5.6-terra", "supported_parameters": ["max_tokens", "reasoning"]},
    ]}
    endpoints = {
        "x-ai/grok-4.3": {"data": {"endpoints": [
            {"provider_name": "xAI", "supported_parameters": ["top_p"]},
        ]}},
        "openai/gpt-5.6-terra": {"data": {"endpoints": [
            {"provider_name": "OpenAI", "supported_parameters": ["max_tokens"]},
            {"provider_name": "Azure", "supported_parameters": ["max_tokens"]},
        ]}},
    }

    def fake_urlopen(req, timeout=30):
        url = req.full_url
        if url.endswith("/models"):
            return _FakeHTTP(models_payload)
        slug = url.split("/models/", 1)[1].rsplit("/endpoints", 1)[0]
        return _FakeHTTP(endpoints[slug])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    facts = fetch_live_facts(["x-ai/grok-4.3", "openai/gpt-5.6-terra"],
                             api_key="k", base_url="https://openrouter.ai/api/v1")

    assert facts["x-ai/grok-4.3"]["present"] and facts["x-ai/grok-4.3"]["models_accepts_top_p"] is True
    assert facts["x-ai/grok-4.3"]["endpoint_top_p"] == {True}
    assert facts["x-ai/grok-4.3"]["providers"] == {"xAI"}
    assert facts["openai/gpt-5.6-terra"]["models_accepts_top_p"] is False
    assert facts["openai/gpt-5.6-terra"]["endpoint_top_p"] == {False}
    assert facts["openai/gpt-5.6-terra"]["providers"] == {"OpenAI", "Azure"}


def test_fetch_live_facts_marks_absent_model(monkeypatch):
    def fake_urlopen(req, timeout=30):
        assert req.full_url.endswith("/models")     # absent model -> endpoints never fetched
        return _FakeHTTP({"data": [{"id": "x-ai/grok-4.3", "supported_parameters": ["top_p"]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    facts = fetch_live_facts(["does/not-exist"], api_key="k", base_url="https://openrouter.ai/api/v1")
    assert facts["does/not-exist"] == {"present": False}
