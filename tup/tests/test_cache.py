"""Response cache: hits, misses, key sensitivity (incl. seed), metadata roundtrip, cache-dir resolution."""
from __future__ import annotations

from pathlib import Path

from tup.client.cache import ResponseCache
from tup.store import Store
from tup.client.types import ClientResponse, Usage

MSGS = [{"role": "user", "content": "hi"}]
SEED = 7


def _resp(content="hello", reasoning_tokens=None, generation_id="gen_1", served_model="served/x", provider="Prov"):
    return ClientResponse(
        content=content,
        model="x-ai/grok-4.3",
        role="judge",
        finish_reason="stop",
        usage=Usage(10, 2, 0.0001, reasoning_tokens),
        generation_id=generation_id,
        served_model=served_model,
        provider=provider,
    )


def test_set_then_get(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED, _resp())
    hit = cache.get("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED)
    assert hit is not None
    assert hit.content == "hello"
    assert hit.cached is True
    assert hit.usage.cost == 0.0001


def test_miss_returns_none(tmp_path):
    assert ResponseCache(cache_dir=tmp_path).get("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED) is None


def test_cached_tokens_and_discount_roundtrip(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    r = ClientResponse(content="hello", model="x-ai/grok-4.3", role="judge", finish_reason="stop",
                       usage=Usage(1000, 2, 0.0001, cached_tokens=768, cache_discount=-0.0002))
    cache.set("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED, r)
    hit = cache.get("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED)
    assert hit.usage.cached_tokens == 768
    assert hit.usage.cache_discount == -0.0002


def test_pre_cached_tokens_entry_still_loads(tmp_path):
    """Entries lacking the optional cached_tokens/cache_discount fields must still deserialize
    (the whole point of the response cache is that old paid-for calls stay usable)."""
    import json
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED, _resp())
    entry = next(tmp_path.glob("*.json"))
    d = json.loads(entry.read_text())
    for k in ("cached_tokens", "cache_discount"):
        d["usage"].pop(k)                      # simulate an on-disk entry without the optional fields
    entry.write_text(json.dumps(d))
    hit = cache.get("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED)
    assert hit is not None and hit.usage.cached_tokens is None and hit.usage.cache_discount is None


def test_sampling_change_is_a_miss(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED, _resp())
    assert cache.get("x-ai/grok-4.3", MSGS, 0.7, 4096, SEED) is None  # temperature differs
    assert cache.get("x-ai/grok-4.3", MSGS, 0.0, 512, SEED) is None  # max_tokens differs


def test_seed_change_is_a_miss(tmp_path):
    """Seed-in-key at the cache layer: a different seed is a different entry (no replicate collapse)."""
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("x-ai/grok-4.3", MSGS, 0.7, 4096, 1, _resp(content="replicate-1"))
    assert cache.get("x-ai/grok-4.3", MSGS, 0.7, 4096, 2) is None  # seed 2 != seed 1 -> miss
    assert cache.get("x-ai/grok-4.3", MSGS, 0.7, 4096, 1).content == "replicate-1"  # same seed hits


def test_none_usage_roundtrips(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    r = ClientResponse(content="x", model="m", role="advisor", finish_reason="length", usage=None)
    cache.set("m", MSGS, 0.7, 4096, SEED, r)
    hit = cache.get("m", MSGS, 0.7, 4096, SEED)
    assert hit.usage is None
    assert hit.truncated is True


def test_reasoning_and_routing_roundtrip(tmp_path):
    """reasoning_tokens + routing metadata survive the cache."""
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set(
        "x-ai/grok-4.3", MSGS, 0.0, 4096, SEED,
        _resp(reasoning_tokens=128, generation_id="gen_abc", served_model="x-ai/grok-4.3", provider="xAI"),
    )
    hit = cache.get("x-ai/grok-4.3", MSGS, 0.0, 4096, SEED)
    assert hit.usage.reasoning_tokens == 128
    assert hit.generation_id == "gen_abc"
    assert hit.served_model == "x-ai/grok-4.3"
    assert hit.provider == "xAI"


# --------------------------- cache-dir resolution ----------------------
def test_the_store_owns_the_default_cache_dir(tmp_path, monkeypatch):
    """The store is the SINGLE authority on where cache data lives, resolved at call time —
    the cache never derives a path itself (a second path authority is the drift the store
    exists to prevent)."""
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    assert ResponseCache().cache_dir == Store(tmp_path).cache_dir
    assert ResponseCache().cache_dir.is_relative_to(tmp_path)


def test_an_explicit_cache_dir_still_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path / "store"))
    forced = tmp_path / "forced"
    assert ResponseCache(cache_dir=forced).cache_dir == forced
    assert ResponseCache(cache_dir=str(forced)).cache_dir == forced


def test_the_default_cache_dir_is_resolved_per_call_not_at_import(tmp_path, monkeypatch):
    """The cache directory follows TUP_RESULTS_ROOT at call time: two different roots in one
    process must give two different caches."""
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path / "a"))
    a = ResponseCache().cache_dir
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path / "b"))
    assert ResponseCache().cache_dir != a


def test_separate_cache_dirs_are_isolated(tmp_path):
    # the core safety property: an entry written under one dir is invisible under another (no contamination)
    shared = ResponseCache(cache_dir=tmp_path / "one")
    indep = ResponseCache(cache_dir=tmp_path / "two")
    shared.set("x-ai/grok-4.3", MSGS, 0.7, 4096, SEED, _resp(content="from-shared"))
    assert indep.get("x-ai/grok-4.3", MSGS, 0.7, 4096, SEED) is None          # independent run can't see it
    assert shared.get("x-ai/grok-4.3", MSGS, 0.7, 4096, SEED).content == "from-shared"


# --------------------------- extra-discriminator keying (routing-pin + condition-salt discriminators) ---------------------------
def test_extra_discriminates_key(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("m", MSGS, 0.0, 4096, SEED, _resp("pinned"), extra={"provider_pin": ["DeepInfra"]})
    assert cache.get("m", MSGS, 0.0, 4096, SEED) is None                                   # base key distinct
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra={"provider_pin": ["Novita"]}) is None  # other pin misses
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra={"provider_pin": ["DeepInfra"]}).content == "pinned"


def test_empty_extra_is_the_legacy_key(tmp_path):
    # extra=None and extra={} must both address the base key so unpinned entries stay valid
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("m", MSGS, 0.0, 4096, SEED, _resp("legacy"))
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra=None).content == "legacy"
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra={}).content == "legacy"


def test_salt_discriminates_key(tmp_path):
    cache = ResponseCache(cache_dir=tmp_path)
    cache.set("m", MSGS, 0.0, 4096, SEED, _resp("work"), extra={"cache_salt": "work"})
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra={"cache_salt": "no_insurance"}) is None
    assert cache.get("m", MSGS, 0.0, 4096, SEED, extra={"cache_salt": "work"}).content == "work"
