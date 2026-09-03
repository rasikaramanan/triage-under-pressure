"""config.load_config / load_api_key / load_base_url — parsing, validation, env handling."""
from __future__ import annotations

import textwrap

import pytest

from tup.client import config as cfg
from tup.client.config import load_api_key, load_base_url, load_config


def test_load_real_config():
    c = load_config()
    assert c.providers["xai"] == "x-ai/grok-4.3"
    assert c.providers["openai"] == "openai/gpt-5.6-terra"        # the locked advisor slate
    assert c.providers["anthropic"] == "anthropic/claude-sonnet-5"
    assert c.providers["meta"] == "meta-llama/llama-4-maverick"
    assert c.providers["google"] == "google/gemini-3.6-flash"
    assert c.advisors == ["openai", "anthropic", "meta", "google", "xai"]  # full run: all five
    assert c.patient == "meta" and c.judge_panel == 3
    # the simulator must not be one of the five advisor models
    assert c.patient_model == "meta-llama/llama-3.3-70b-instruct"
    assert c.provider_pins == {
        "google/gemini-3.6-flash": ["Google AI Studio"],
        "google/gemini-3.5-flash-lite": ["Google AI Studio"],   # guard classifier pin
        "meta-llama/llama-4-maverick": ["DeepInfra", "Novita"],  # cost pin: pinned providers keep routing and prices fixed
        # pinned for price stability: unpinned routing may drift to costlier providers
        "meta-llama/llama-3.3-70b-instruct": ["DeepInfra", "Novita"],
    }
    assert c.guard_model == "google/gemini-3.5-flash-lite"      # the guard classifier slug
    assert c.judge_panel == 3                       # full run: 3-judge panel mode
    assert c.sampling["advisor"].temperature == 0.7
    assert c.sampling["judge"].temperature == 0.2  # panel temp (sycoevalem2026 anchor)
    assert c.sampling["patient"].temperature == 0.9
    assert c.sampling["judge"].max_tokens == 4096
    assert isinstance(c.seed, int)


def test_malformed_config_raises(tmp_path):
    p = tmp_path / "m.yaml"
    p.write_text("providers:\n  openai: a\nroles:\n  advisors: [openai]\n  patient: openai\n  judge: openai\n")
    with pytest.raises(ValueError, match="Malformed"):  # no `sampling` / `seed`
        load_config(p)


def test_referential_integrity_raises(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(textwrap.dedent("""
      providers: {openai: a, google: b}
      roles: {advisors: [openai, xai], patient: google, judge_panel: 3}
      sampling:
        advisor: {temperature: 0.7, max_tokens: 10}
        patient: {temperature: 0.9, max_tokens: 10}
        judge: {temperature: 0.0, max_tokens: 10}
      seed: 1
    """))
    with pytest.raises(ValueError, match="absent from"):  # advisor 'xai' not in providers
        load_config(p)


def test_api_key_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / "none.env")  # missing file -> no key leak
    monkeypatch.delenv("OPENROUTER_TUP_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_TUP_API_KEY"):
        load_api_key()


def test_api_key_fallback_to_plain_name(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / "none.env")
    monkeypatch.delenv("OPENROUTER_TUP_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fallback")
    assert load_api_key() == "sk-fallback"


def test_base_url_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_PATH", tmp_path / "none.env")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    assert load_base_url() == cfg.DEFAULT_BASE_URL
