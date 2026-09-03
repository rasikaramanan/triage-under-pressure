"""Anthropic prompt-cache breakpoints (``cache_control``) for OpenRouter requests.

Anthropic is the roster provider whose prompt caching is NOT automatic — it needs explicit
``cache_control: {"type": "ephemeral"}`` breakpoints on content blocks, passed through OpenRouter's
OpenAI-compatible schema as parts-array message content. Reads bill ~0.1x input, writes ~1.25x
(5-minute TTL), so a breakpoint only pays when the marked prefix is re-read; prefixes below the
model's documented minimum cacheable length silently don't cache — no error.
(Source for these prices, the minimum-length rule, and the 4-breakpoint cap:
https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)

Two call shapes, two policies (max 4 breakpoints/request; we use at most 2):

- **Multi-turn (every non-judge role)**: mark the system block (if any) and the LAST message. Each turn's
  prompt extends the previous one, so the marked prefix is read back (0.1x) on the next turn and only
  the increment is written. This is Anthropic's documented incremental multi-turn pattern.
- **Judge**: the transcript is unique per call, so marking the whole message would be a write-only
  premium. Instead the caller passes the FIXED rubric prefix (the template text before the first
  slot) and the single user message is split into [rubric block (marked), remainder] — the
  documented shared-prefix/varying-suffix pattern. Concatenation is byte-identical to the original
  string by construction, so the judge sees the same prompt text.

The transform is applied by the client AFTER the local ResponseCache lookup, so cache keys are still
computed from the original plain-string messages — adding/altering breakpoints never invalidates
already-paid-for cached responses.
"""
from __future__ import annotations

from typing import Optional

CACHE_CONTROL = {"type": "ephemeral"}


def is_anthropic(model: str) -> bool:
    return model.startswith("anthropic/")


def _text_part(text: str, mark: bool) -> dict:
    part: dict = {"type": "text", "text": text}
    if mark:
        part["cache_control"] = dict(CACHE_CONTROL)
    return part


def prepare_messages(
    role: str, messages: list[dict], model: str, cache_text_prefix: Optional[str] = None
) -> list[dict]:
    """Return messages with cache_control breakpoints for an Anthropic model; unchanged otherwise.

    Never mutates the input. If any message already carries parts-list content, the caller has taken
    manual control — return the messages untouched.
    """
    if not is_anthropic(model):
        return messages
    if any(not isinstance(m.get("content"), str) for m in messages):
        return messages

    if role == "judge":
        if not cache_text_prefix:
            return messages
        first = messages[0]
        if first.get("role") != "user" or not first["content"].startswith(cache_text_prefix):
            return messages  # unexpected shape — never risk altering the judge prompt
        rest = first["content"][len(cache_text_prefix):]
        split = {**first, "content": [_text_part(cache_text_prefix, True), _text_part(rest, False)]}
        return [split] + [dict(m) for m in messages[1:]]

    # Multi-turn roles: system breakpoint (stable all conversation) + last-message breakpoint
    # (extends the cached prefix each turn).
    out = []
    last = len(messages) - 1
    for i, m in enumerate(messages):
        if m.get("role") == "system" or i == last:
            out.append({**m, "content": [_text_part(m["content"], True)]})
        else:
            out.append(dict(m))
    return out
