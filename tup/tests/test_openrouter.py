"""OpenRouter client wrapper: resolution, usage capture, caching, seed, retries, validation."""
from __future__ import annotations

import httpx
import pytest
import tenacity
from openai import APIConnectionError

from tup.client.cache import ResponseCache
from tup.client.openrouter import OpenRouterClient, TransientUpstreamError
from tup.client.provider import ConstraintError

from .conftest import _PTD, _UNSET, FakeSDK, _Resp, _Usage

MSGS = [{"role": "user", "content": "hi"}]


def _client(sample_config, sdk, cache=None):
    return OpenRouterClient(config=sample_config, sdk_client=sdk, cache=cache)


def test_complete_captures_content_cost_and_reasoning(sample_config):
    sdk = FakeSDK(
        responses=[_Resp(content="go to the ER", usage=_Usage(120, 40, 0.00031, reasoning_tokens=64))]
    )
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.content == "go to the ER"
    assert out.model == "x-ai/grok-4.3"          # requested slug
    assert out.usage.completion_tokens == 40
    assert out.usage.cost == 0.00031
    assert out.usage.reasoning_tokens == 64       # reasoning-token metadata
    assert out.cached is False


def test_captures_routing_metadata(sample_config):
    sdk = FakeSDK(
        responses=[_Resp(usage=_Usage(1, 1, 0.0), id="gen_abc", model="served/y", provider="Fireworks")]
    )
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.generation_id == "gen_abc"         # routing metadata
    assert out.served_model == "served/y"
    assert out.provider == "Fireworks"


def test_role_sampling_is_passed_through(sample_config):
    sdk = FakeSDK()
    _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert sdk.last_kwargs["temperature"] == 0.0  # judge temp
    assert sdk.last_kwargs["max_tokens"] == 4096


def test_seed_defaults_to_config_and_is_overridable(sample_config):
    sdk = FakeSDK()
    client = _client(sample_config, sdk)
    client.complete("judge", MSGS, provider="xai")
    assert sdk.last_kwargs["seed"] == sample_config.seed  # default = config base seed
    client.complete("judge", MSGS, provider="xai", seed=999)
    assert sdk.last_kwargs["seed"] == 999                 # explicit per-replicate override


def test_distinct_seeds_dont_collapse(sample_config, tmp_path):
    """Seed-in-key: distinct seeds => distinct calls + cache entries; same seed re-runs from cache."""
    sdk = FakeSDK(responses=[_Resp(content="r", usage=_Usage(5, 1, 0.0))])
    client = _client(sample_config, sdk, cache=ResponseCache(cache_dir=tmp_path))
    a = client.complete("advisor", MSGS, provider="openai", seed=1)
    b = client.complete("advisor", MSGS, provider="openai", seed=2)
    assert a.cached is False and b.cached is False
    assert sdk.create_calls == 2                   # two seeds => two real calls, no collision
    again = client.complete("advisor", MSGS, provider="openai", seed=1)
    assert again.cached is True                     # same seed => cache hit
    assert sdk.create_calls == 2


def test_advisor_requires_provider(sample_config):
    client = _client(sample_config, FakeSDK())
    with pytest.raises(ValueError, match="explicit provider"):
        client.complete("advisor", MSGS)
    out = client.complete("advisor", MSGS, provider="openai")
    assert out.model == "openai/gpt-5.6-terra"


def test_truncation_flag(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="x", finish_reason="length", usage=None)])
    out = _client(sample_config, sdk).complete("advisor", MSGS, provider="openai")
    assert out.truncated is True


def test_cache_short_circuits_second_call(sample_config, tmp_path):
    sdk = FakeSDK(responses=[_Resp(content="cached me", usage=_Usage(5, 1, 0.0))])
    client = _client(sample_config, sdk, cache=ResponseCache(cache_dir=tmp_path))
    first = client.complete("judge", MSGS, provider="xai")
    second = client.complete("judge", MSGS, provider="xai")
    assert first.cached is False and second.cached is True
    assert second.content == "cached me"
    assert sdk.create_calls == 1                    # same default seed => SDK hit once


def test_constraints_enforced_at_init(sample_config):
    import dataclasses

    # Rule: the patient may share an advisor's provider; the constraint that still fails loud
    # at init is a panel that leave-one-provider-out cannot seat (too few other providers).
    bad = dataclasses.replace(
        sample_config,
        providers={k: v for k, v in list(sample_config.providers.items())[:3]},
        advisors=list(sample_config.providers)[:3],
    )
    with pytest.raises(ConstraintError):
        OpenRouterClient(config=bad, sdk_client=FakeSDK())


def test_retry_then_succeed(sample_config, monkeypatch):
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)  # no real backoff waits
    exc = APIConnectionError(request=httpx.Request("POST", "https://openrouter.ai/api/v1"))
    sdk = FakeSDK(responses=[_Resp(content="recovered", usage=_Usage(3, 1, 0.0))], fail_times=2, exc=exc)
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.content == "recovered"
    assert sdk.create_calls == 3                    # 2 failures + 1 success


def test_validate_models(sample_config):
    all_slugs = list(sample_config.providers.values())
    ok = _client(sample_config, FakeSDK(model_ids=all_slugs))
    assert sorted(ok.validate_models()) == sorted(set(all_slugs))

    missing = _client(sample_config, FakeSDK(model_ids=all_slugs[:-1]))  # drop one
    with pytest.raises(ValueError, match="not on the live OpenRouter list"):
        missing.validate_models()


def test_usage_include_flag_sent_every_request(sample_config):
    """Requirement: real charged cost must be requested from OpenRouter, not reconstructed."""
    sdk = FakeSDK()
    client = _client(sample_config, sdk)
    for role, kw in (("judge", {"provider": "xai"}), ("patient", {}), ("advisor", {"provider": "meta"})):
        client.complete(role, MSGS, **kw)
        assert sdk.last_kwargs["extra_body"] == {"usage": {"include": True}}
        assert sdk.last_kwargs.get("stream") in (None, False)  # non-streaming => usage present


# ---- OpenRouter 200-with-error-body (empty choices) -------------------
def test_empty_choices_is_retried_then_raises(sample_config, monkeypatch):
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)
    sdk = FakeSDK(responses=[_Resp(error={"message": "no endpoints", "code": 502})])  # choices=[]
    with pytest.raises(TransientUpstreamError):
        _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert sdk.create_calls == 4   # retried stop_after_attempt(4) instead of IndexError


def test_empty_choices_then_success(sample_config, monkeypatch):
    monkeypatch.setattr(tenacity.nap, "sleep", lambda _s: None)
    sdk = FakeSDK(responses=[_Resp(error={"message": "x"}), _Resp(content="recovered", usage=_Usage(1, 1, 0.0))])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.content == "recovered"
    assert sdk.create_calls == 2


# ---- empty completion handling ---------------------------------------
def test_empty_content_retried_then_recovers(sample_config):
    sdk = FakeSDK(responses=[_Resp(content=""), _Resp(content="now i have content", usage=_Usage(1, 1, 0.0))])
    out = _client(sample_config, sdk).complete("advisor", MSGS, provider="openai")
    assert out.content == "now i have content"
    assert sdk.create_calls == 2   # one retry on the empty first completion


def test_persistent_empty_content_is_not_cached(sample_config, tmp_path):
    sdk = FakeSDK(responses=[_Resp(content="", finish_reason="length", usage=None)])
    client = _client(sample_config, sdk, cache=ResponseCache(cache_dir=tmp_path))
    out = client.complete("advisor", MSGS, provider="openai")
    assert out.content == "" and out.truncated is True
    before = sdk.create_calls
    out2 = client.complete("advisor", MSGS, provider="openai")
    assert out2.cached is False              # empty was NOT cached -> re-run retries
    assert sdk.create_calls > before


# ---- usage-extraction fallbacks (dict- and attr-shaped provider payloads) --------
def test_reasoning_tokens_dict_shaped(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(10, 5, 0.001, ctd={"reasoning_tokens": 96}))])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.usage.reasoning_tokens == 96


def test_reasoning_tokens_via_model_extra(sample_config):
    u = _Usage(10, 5, 0.001, ctd=None, model_extra={"cost": 0.001, "completion_tokens_details": {"reasoning_tokens": 77}})
    out = _client(sample_config, FakeSDK(responses=[_Resp(usage=u)])).complete("judge", MSGS, provider="xai")
    assert out.usage.reasoning_tokens == 77


def test_provider_via_model_extra_fallback(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0), provider=_UNSET, model_extra={"provider": "Fireworks"})])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.provider == "Fireworks"


def test_absent_routing_metadata_is_none(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0), id=_UNSET, model=_UNSET, provider=_UNSET)])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.generation_id is None and out.served_model is None and out.provider is None


def test_provider_pin_is_part_of_the_cache_key(sample_config, tmp_path):
    """Provider pins are part of the cache key: editing provider_pins must invalidate
    entries cached under the old routing."""
    import dataclasses
    cache = ResponseCache(cache_dir=tmp_path)
    sdk = FakeSDK(responses=[_Resp(content="one", usage=_Usage(1, 1, 0.0))])
    pinned = dataclasses.replace(sample_config, provider_pins={"x-ai/grok-4.3": ["DeepInfra"]})
    c1 = OpenRouterClient(config=pinned, sdk_client=sdk, cache=cache)
    c1.complete("judge", MSGS, provider="xai", seed=1)
    assert c1.complete("judge", MSGS, provider="xai", seed=1).cached is True and sdk.create_calls == 1  # same pin hits
    repinned = dataclasses.replace(sample_config, provider_pins={"x-ai/grok-4.3": ["Novita"]})
    OpenRouterClient(config=repinned, sdk_client=sdk, cache=cache).complete("judge", MSGS, provider="xai", seed=1)
    assert sdk.create_calls == 2                        # changed pin -> miss -> fresh call
    OpenRouterClient(config=sample_config, sdk_client=sdk, cache=cache).complete("judge", MSGS, provider="xai", seed=1)
    assert sdk.create_calls == 3                        # unpinned -> legacy key -> also distinct

# ---- prompt-cache observability (cached_tokens / cache_discount) ------------
def test_cached_tokens_object_shaped(sample_config):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1000, 5, 0.001, ptd=_PTD(cached_tokens=896)))])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.usage.cached_tokens == 896


def test_cached_tokens_and_discount_via_model_extra(sample_config):
    u = _Usage(1000, 5, 0.001, model_extra={"cost": 0.001,
                                            "prompt_tokens_details": {"cached_tokens": 512},
                                            "cache_discount": -0.0004})
    out = _client(sample_config, FakeSDK(responses=[_Resp(usage=u)])).complete("judge", MSGS, provider="xai")
    assert out.usage.cached_tokens == 512
    assert out.usage.cache_discount == -0.0004


def test_cached_tokens_absent_is_none(sample_config):
    # provider reports no prompt_tokens_details at all -> None (not 0): "not reported" != "no hits"
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(10, 5, 0.001))])
    out = _client(sample_config, sdk).complete("judge", MSGS, provider="xai")
    assert out.usage.cached_tokens is None and out.usage.cache_discount is None


# ---- sticky-routing session_id ----------------------------------------------
def test_session_id_composes_with_provider_pin(sample_config):
    """Both routing fields ride extra_body under separate keys — a pinned model (gemini,
    llama-4-maverick) must keep its pin when a session_id is also sent, and vice versa."""
    import dataclasses
    cfg = dataclasses.replace(
        sample_config, provider_pins={"meta-llama/llama-4-maverick": ["DeepInfra", "Novita"]}
    )
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.0))])
    _client(cfg, sdk).complete("advisor", MSGS, provider="meta", session_id="001__work__meta__r0")
    eb = sdk.last_kwargs["extra_body"]
    assert eb["provider"] == {"order": ["DeepInfra", "Novita"], "allow_fallbacks": False}
    assert eb["session_id"] == "001__work__meta__r0"
    assert eb["usage"] == {"include": True}


def test_session_id_forwarded_to_extra_body(sample_config):
    sdk = FakeSDK()
    client = _client(sample_config, sdk)
    client.complete("judge", MSGS, provider="xai", session_id="001__work__openai__r0")
    assert sdk.last_kwargs["extra_body"]["session_id"] == "001__work__openai__r0"
    client.complete("judge", MSGS, provider="xai")   # no session_id -> key absent (not None), per OpenRouter contract
    assert "session_id" not in sdk.last_kwargs["extra_body"]


def test_session_id_is_never_part_of_the_cache_key(sample_config, tmp_path):
    """CRITICAL INVARIANT: session_id never enters the cache key — it is a per-CONVERSATION
    routing hint. If it ever entered the key, every conversation would get its own
    entries, invalidating the entire cache on any run. Same calls under different session_ids
    must HIT; cache_salt (which legitimately keys) must MISS."""
    cache = ResponseCache(cache_dir=tmp_path)
    sdk = FakeSDK(responses=[_Resp(content="one", usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=cache)
    client.complete("judge", MSGS, provider="xai", seed=7, session_id="conv__A")
    assert sdk.create_calls == 1
    out = client.complete("judge", MSGS, provider="xai", seed=7, session_id="conv__B")   # different session
    assert out.cached is True and sdk.create_calls == 1                  # ...still a cache HIT
    out = client.complete("judge", MSGS, provider="xai", seed=7)                         # no session at all
    assert out.cached is True and sdk.create_calls == 1
    client.complete("judge", MSGS, provider="xai", seed=7, cache_salt="work")            # salt DOES key
    assert sdk.create_calls == 2


# ---- spend accounting at the wire --------------------------------------------------------------
def test_spend_is_summed_per_response_including_the_empty_retry(sample_config):
    sdk = FakeSDK(responses=[
        _Resp(content="", usage=_Usage(1, 1, 0.25)),        # empty completion -> retried once
        _Resp(content="ok", usage=_Usage(1, 1, 0.5)),
        _Resp(content="ok", usage=_Usage(1, 1, None)),      # no cost metadata
    ])
    c = _client(sample_config, sdk)
    c.complete("judge", MSGS, provider="xai")
    assert c.spent_usd == pytest.approx(0.75)                # both paid attempts counted
    assert c.calls_missing_cost == 0
    c.complete("judge", MSGS, provider="xai")
    assert c.spent_usd == pytest.approx(0.75)
    assert c.calls_missing_cost == 1                         # the total is now a lower bound


def test_spend_is_not_charged_for_cache_hits(sample_config, tmp_path):
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.3))])
    c = _client(sample_config, sdk, cache=ResponseCache(tmp_path / "cache"))
    c.complete("judge", MSGS, provider="xai")
    c.complete("judge", MSGS, provider="xai")                # served from the cache
    assert sdk.create_calls == 1 and c.spent_usd == pytest.approx(0.3)


def test_spend_accumulator_is_thread_safe(sample_config):
    from concurrent.futures import ThreadPoolExecutor
    sdk = FakeSDK(responses=[_Resp(content="ok", usage=_Usage(1, 1, 0.01))])
    c = _client(sample_config, sdk)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: c.complete("judge", MSGS, provider="xai"), range(200)))
    assert c.spent_usd == pytest.approx(2.0)
