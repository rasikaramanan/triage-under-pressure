"""OpenRouter client wrapper — the one place the network is touched.

A thin layer over the OpenAI SDK (base_url override) that:
  - resolves the model + sampling for a role,
  - retries transient failures with exponential backoff (incl. OpenRouter's 200-with-error-body,
    which the SDK surfaces as a normal response with empty ``choices``),
  - retries an empty completion once (reasoning models can spend the whole token budget on hidden
    reasoning), and never caches an empty result,
  - captures usage (tokens + reasoning tokens + OpenRouter cost), finish_reason, and routing
    metadata (generation id, served model, upstream provider),
  - optionally caches responses by (model, messages, sampling, seed),
  - accounts spend at the wire: every response's ``usage.cost`` is summed into ``spent_usd``
    (thread-safe), so a spend cap can be enforced by a caller that never sees the persisted
    records — a retry's first attempt and a seat whose record later keeps only its last
    attempt are both counted here and nowhere else.

The runner, the judge and the patient guard call ``complete()``; they never touch the SDK directly.
"""
from __future__ import annotations

import threading
from typing import Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tup.client.anthropic_cache import prepare_messages
from tup.client.cache import ResponseCache
from tup.client.config import load_api_key, load_base_url, load_config
from tup.client.provider import ProviderRegistry
from tup.client.types import ClientResponse, Config, Usage


class TransientUpstreamError(Exception):
    """OpenRouter returned HTTP 200 but the body carries an error / no choices.

    The SDK does not raise for this (the HTTP status was 200), so without an explicit raise it would
    surface as an IndexError on ``choices[0]`` and never be retried. We raise this inside ``_call`` so
    tenacity retries it like any other transient upstream failure (rate limit, 5xx, no endpoint).
    """


# Errors worth retrying: rate limits, timeouts, dropped connections, upstream 5xx, and the
# 200-with-error-body case. (Auth / 400 / model-not-found are NOT here — they should fail immediately.)
_TRANSIENT = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    TransientUpstreamError,
)


def _reasoning_tokens(usage, extra: dict) -> Optional[int]:
    """Pull completion_tokens_details.reasoning_tokens (object- or dict-shaped, or via model_extra).

    The output layer logs this for reasoning models to confirm the configured max_tokens cap
    isn't spent on hidden reasoning, truncating visible output (the advisor cap is 8192 for
    exactly that headroom — config/models.yaml).
    """
    ctd = getattr(usage, "completion_tokens_details", None)
    if ctd is None:
        ctd = extra.get("completion_tokens_details")
    if ctd is None:
        return None
    if isinstance(ctd, dict):
        return ctd.get("reasoning_tokens")
    return getattr(ctd, "reasoning_tokens", None)


def _cached_tokens(usage, extra: dict) -> Optional[int]:
    """Pull prompt_tokens_details.cached_tokens (object- or dict-shaped, or via model_extra).

    This is the provider's prompt-cache read count — the ONLY ground truth for whether automatic prompt caching (the non-Anthropic providers, where they offer it) is actually firing on the growing-transcript calls. Recorded
    per turn so cache hit rates are measurable from run records instead of inferred from cost ratios.
    """
    ptd = getattr(usage, "prompt_tokens_details", None)
    if ptd is None:
        ptd = extra.get("prompt_tokens_details")
    if ptd is None:
        return None
    if isinstance(ptd, dict):
        return ptd.get("cached_tokens")
    return getattr(ptd, "cached_tokens", None)


def _extract_usage(resp) -> Optional[Usage]:
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    extra = getattr(u, "model_extra", None) or {}
    return Usage(
        prompt_tokens=u.prompt_tokens,
        completion_tokens=u.completion_tokens,
        cost=extra.get("cost"),
        reasoning_tokens=_reasoning_tokens(u, extra),
        cached_tokens=_cached_tokens(u, extra),
        cache_discount=extra.get("cache_discount"),
    )


def _extract_provider(resp) -> Optional[str]:
    """OpenRouter reports the upstream provider it routed to (a non-OpenAI `provider` field)."""
    prov = getattr(resp, "provider", None)
    if prov:
        return prov
    extra = getattr(resp, "model_extra", None) or {}
    return extra.get("provider")


def _content_of(resp) -> str:
    return resp.choices[0].message.content or ""


class OpenRouterClient:
    def __init__(
        self,
        config: Optional[Config] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        cache: Optional[ResponseCache] = None,
        sdk_client: Optional[OpenAI] = None,  # injectable for tests
    ):
        self.config = config or load_config()
        self.registry = ProviderRegistry(self.config)
        self.registry.validate_constraints()  # fail loud at startup
        self._sdk = sdk_client or OpenAI(
            base_url=base_url or load_base_url(),
            api_key=api_key or load_api_key(),
        )
        self.cache = cache
        # Spend accounting at the one place the network is touched. ``complete`` may call
        # ``_call`` twice (empty-completion retry) and tenacity may re-enter it; each attempt that
        # returns a response is charged exactly once here. A response without ``usage.cost`` is
        # counted in ``calls_missing_cost`` so the total is known to be a lower bound.
        self._spend_lock = threading.Lock()
        self.spent_usd: float = 0.0
        self.calls_missing_cost: int = 0

    def _account(self, resp) -> None:
        u = _extract_usage(resp)
        with self._spend_lock:
            if u is not None and u.cost is not None:
                self.spent_usd += float(u.cost)
            else:
                self.calls_missing_cost += 1

    # ---- model / sampling resolution --------------------------------------
    def resolve_model(self, role: str, provider: Optional[str] = None) -> str:
        if role == "patient":
            # Per-role override: the patient may use a different slug than its provider's
            # advisor/judge slug (the shipped config: llama-3.3-70b patient vs llama-4-maverick
            # advisor, both meta — keeping the simulator off the advisor slate).
            if self.config.patient_model:
                return self.config.patient_model
            return self.registry.slug_for(self.config.patient)
        if role == "guard":
            # Patient role-compliance guard classifier (apparatus — leave-one-out does not apply).
            if not self.config.guard_model:
                raise ValueError("guard role requires roles.guard_model in config/models.yaml")
            return self.config.guard_model
        if role == "judge":
            # The panel path always passes the seat's provider explicitly.
            if provider is None:
                raise ValueError("judge role requires an explicit provider (a panel seat)")
            if provider not in self.config.providers:
                raise ValueError(f"{provider!r} is not a configured provider")
            return self.registry.slug_for(provider)
        if role == "advisor":
            if provider is None:
                raise ValueError("advisor role requires an explicit provider (multiple advisors)")
            if provider not in self.config.advisors:
                raise ValueError(f"{provider!r} is not a configured advisor")
            return self.registry.slug_for(provider)
        raise ValueError(f"unknown role: {role!r}")

    # ---- main entrypoint --------------------------------------------------
    def complete(
        self,
        role: str,
        messages: list[dict],
        provider: Optional[str] = None,
        seed: Optional[int] = None,
        cache_salt: Optional[str] = None,      # -> folded into the cache key
        session_id: Optional[str] = None,      # -> routing hint ONLY, never the cache key
        cache_text_prefix: Optional[str] = None,
    ) -> ClientResponse:
        """Call the model for ``role`` (sampling from config); cache-aware.

        ``seed`` defaults to the config base seed. The runner passes a DISTINCT derived seed per
        conversation (tup/orchestration/runner.py:conversation_seed); the effective seed is
        threaded into BOTH the API request and the cache key, so replicates stay distinct *and*
        re-runs reproduce.

        ``session_id`` is an OpenRouter provider-routing hint (sticky routing): calls sharing a
        session_id land on the same upstream provider, keeping its prompt cache warm across the
        growing-transcript calls. Routing-only — deliberately NOT part of the response-cache key, so
        adding/changing it never invalidates existing cached responses.

        Anthropic models additionally get explicit ``cache_control`` breakpoints (Anthropic caching
        is opt-in, unlike OpenAI/Google/xAI): multi-turn roles are marked system + last message;
        the judge passes ``cache_text_prefix`` (its fixed rubric) so only the shared prefix of its
        single message is marked. Applied AFTER the response-cache lookup, so — like session_id — it
        never changes a cache key. See tup/client/anthropic_cache.py.

        An empty completion is retried once (uncached) and is never written to the cache, so a stuck
        empty result does not get frozen — re-runs retry it. The caller (runner) decides what to do if
        it is still empty.
        """
        if role not in self.config.sampling:
            raise ValueError(f"no sampling config for role {role!r}")
        model = self.resolve_model(role, provider)
        s = self.config.sampling[role]
        effective_seed = seed if seed is not None else self.config.seed

        # Cache-key discriminators beyond the request payload:
        # - the provider-routing pin, so editing `provider_pins` invalidates entries served under the
        #   OLD routing (a pinned model must never replay a response from a since-excluded upstream,
        #   nor a gemini response sampled on a non-AI-Studio endpoint where temp/top_p don't apply);
        # - the caller's `cache_salt` (the runner salts post-response-1 advisor calls by condition).
        # Unpinned+unsalted calls omit the field entirely, keeping cache entries from earlier code versions valid.
        pins = self.config.provider_pins or {}
        cache_extra: Optional[dict] = {}
        if model in pins:
            cache_extra["provider_pin"] = list(pins[model])
        if cache_salt is not None:
            cache_extra["cache_salt"] = cache_salt
        cache_extra = cache_extra or None

        if self.cache is not None:
            hit = self.cache.get(
                model, messages, s.temperature, s.max_tokens, effective_seed, extra=cache_extra
            )
            if hit is not None:
                return hit

        # Anthropic cache_control transform happens here — after the cache lookup above (keys stay
        # based on the plain messages) and once for both the call and its empty-completion retry.
        wire_messages = prepare_messages(role, messages, model, cache_text_prefix)

        resp = self._call(model, wire_messages, s.temperature, s.max_tokens, effective_seed, session_id)
        if not _content_of(resp).strip():
            resp = self._call(model, wire_messages, s.temperature, s.max_tokens, effective_seed, session_id)  # one retry

        choice = resp.choices[0]
        content = choice.message.content or ""
        out = ClientResponse(
            content=content,
            model=model,
            role=role,
            finish_reason=choice.finish_reason,
            usage=_extract_usage(resp),
            generation_id=getattr(resp, "id", None),
            served_model=getattr(resp, "model", None),
            provider=_extract_provider(resp),
        )
        if self.cache is not None and content.strip():  # never cache an empty completion
            self.cache.set(
                model, messages, s.temperature, s.max_tokens, effective_seed, out, extra=cache_extra
            )
        return out

    def _extra_body(self, model: str, session_id: Optional[str] = None) -> dict:
        """OpenRouter extra_body: always request real cost; add a provider-routing pin when
        config.provider_pins names this slug (e.g. gemini-3.6-flash -> Google AI Studio, the only
        endpoints where its temperature/top_p apply — see config/models.yaml); add the sticky-routing
        session_id when the caller supplies one (prompt-cache continuity)."""
        body: dict = {"usage": {"include": True}}
        pins = self.config.provider_pins or {}
        if model in pins:
            body["provider"] = {"order": list(pins[model]), "allow_fallbacks": False}
        if session_id is not None:
            body["session_id"] = session_id
        return body

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        reraise=True,
    )
    def _call(
        self, model: str, messages: list[dict], temperature: float, max_tokens: int, seed: int,
        session_id: Optional[str] = None,
    ):
        resp = self._sdk.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            # Best-effort determinism (some providers honor it, some ignore it); the seed-keyed cache
            # is what guarantees distinct replicates + reproducible re-runs regardless.
            seed=seed,
            # Cost-accounting requirement: get OpenRouter's REAL charged cost back in `usage.cost`; never
            # reconstruct cost from token counts. Non-streaming => usage is always present.
            extra_body=self._extra_body(model, session_id),
        )
        # OpenRouter can return HTTP 200 with an error body and no choices (rate limit, 5xx, content
        # filter, no-endpoint). Raise so tenacity retries instead of letting choices[0] IndexError.
        if not getattr(resp, "choices", None):
            err = getattr(resp, "error", None) or (getattr(resp, "model_extra", None) or {}).get("error")
            raise TransientUpstreamError(f"OpenRouter returned no choices (model={model}): {err}")
        self._account(resp)
        return resp

    # ---- startup slug validation ------------------------------------------
    def validate_models(self) -> list[str]:
        """Assert every configured slug exists on the live OpenRouter model list.

        Returns the configured slugs on success; raises ValueError naming any that are
        missing/deprecated — a typo'd or retired slug fails here, before any spend. Scope:
        the provider slate (advisor/judge-seat slugs); the patient/guard overrides are covered
        by the top_p verification gate (tup/client/top_p.py), which fetches them explicitly.
        """
        configured = sorted(set(self.config.providers.values()))
        live = {m.id for m in self._sdk.models.list().data}
        missing = [s for s in configured if s not in live]
        if missing:
            raise ValueError(f"configured slug(s) not on the live OpenRouter list: {missing}")
        return configured
