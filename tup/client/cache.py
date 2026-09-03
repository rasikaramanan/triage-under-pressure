"""Disk-backed response cache keyed on (model, messages, sampling, seed).

One JSON file per call keeps cached results human-inspectable and makes re-runs + dev
iteration free and idempotent. Keyed on the full request — model, messages, temperature,
max_tokens, AND seed — so any change is a miss. The seed is part of the key on purpose: every
conversation carries a distinct derived seed (tup/orchestration/runner.py:conversation_seed),
so replicates of an otherwise-identical call get distinct entries instead of collapsing onto
one and silently shrinking N.

WHAT MUST *NOT* ENTER THE KEY: the client's ``session_id`` (OpenRouter sticky-routing hint) is
per-conversation, so keying it would give every conversation its own entries and make every
resume a full cache miss. It is a routing hint only and never reaches this module; ``extra`` carries only facts that change WHAT a
response is (provider pin, condition salt). Same for the Anthropic ``cache_text_prefix`` marking,
which is applied after the lookup.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from tup.client.types import ClientResponse, Usage

def _default_cache_dir() -> Path:
    """The store's cache directory, resolved at CALL time.

    The store is the ONLY authority on where cache data goes — this module never decides a
    path, it asks.
    """
    from tup.store import Store   # local import: importing at module top would be circular via tup.client
    return Store.from_env().cache_dir


def _key(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    seed: Optional[int],
    extra: Optional[dict] = None,
) -> str:
    blob_dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    # ``extra`` carries request facts that change WHAT a response is without changing the message
    # payload — today the provider-routing pin (a pinned model must never replay a response served
    # by a since-excluded upstream) and the runner's per-condition salt.
    # It is folded in ONLY when present, so cache entries written by earlier code versions (before pins/salts existed) stay addressable.
    if extra:
        blob_dict["extra"] = extra
    blob = json.dumps(blob_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else _default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        seed: Optional[int],
        extra: Optional[dict] = None,
    ) -> Optional[ClientResponse]:
        path = self._path(_key(model, messages, temperature, max_tokens, seed, extra))
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        usage = Usage(**d["usage"]) if d.get("usage") is not None else None
        return ClientResponse(
            content=d["content"],
            model=d["model"],
            role=d["role"],
            finish_reason=d.get("finish_reason"),
            usage=usage,
            cached=True,
            generation_id=d.get("generation_id"),
            served_model=d.get("served_model"),
            provider=d.get("provider"),
        )

    def set(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        seed: Optional[int],
        response: ClientResponse,
        extra: Optional[dict] = None,
    ) -> None:
        usage = None
        if response.usage is not None:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "cost": response.usage.cost,
                "reasoning_tokens": response.usage.reasoning_tokens,
                "cached_tokens": response.usage.cached_tokens,
                "cache_discount": response.usage.cache_discount,
            }
        payload = {
            "content": response.content,
            "model": response.model,
            "role": response.role,
            "finish_reason": response.finish_reason,
            "usage": usage,
            "generation_id": response.generation_id,
            "served_model": response.served_model,
            "provider": response.provider,
        }
        # Atomic write (temp-in-dir + os.replace) so a concurrent reader never sees a torn file and a
        # crash mid-write can't leave a half-written entry. This makes the cache safe under the parallel
        # runner: distinct cells use distinct keys (distinct files), and even a same-key race resolves to
        # last-writer-wins with no corruption. The unique temp name keeps concurrent writers from colliding.
        final = self._path(_key(model, messages, temperature, max_tokens, seed, extra))
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            os.replace(tmp, final)  # atomic on the same filesystem
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

