"""Effective top_p provenance for the routed models (PROJECT_SPEC.md section 14 reproducibility).

WHY THIS EXISTS — the crux
--------------------------
TUP intentionally OMITS top_p (a deliberate design decision, recorded per-model below and in every run manifest: leave it at the provider default, do NOT pin
it). The reproducibility question is therefore: with top_p absent from the request, what value
actually applies — and where does it come from?

OpenRouter's API Parameters docs answer it directly: *"OpenRouter will default to the values listed
below if certain parameters are absent from your request"*, listing **top_p default = 1.0**. So for
every model whose served endpoints ACCEPT top_p, OpenRouter INJECTS top_p=1.0 before forwarding to the
upstream — the upstream provider's *native* default (e.g. Gemini's ~0.95) does NOT apply through
OpenRouter. The one exception: a model that does NOT accept top_p at all — OpenRouter then drops the
param and the upstream's own fixed default applies.
  Source: https://openrouter.ai/docs/api/reference/parameters

This overturns the naive assumption that "omitted ⇒ the upstream's native default" — through OpenRouter
the omitted-default is OpenRouter's 1.0, not the provider's.

Live-verified via the OpenRouter API (dates per entry in the table below; re-runnable:
``scripts/check_top_p.py``). Two mechanisms produce the effective value: endpoints that ACCEPT
top_p get OpenRouter's injected 1.0; models that accept NEITHER top_p NOR temperature (the
OpenAI reasoning line, Anthropic's adaptive-thinking model) run at their provider's fixed
default — effective 1.0, but UNCONFIGURABLE. Split-endpoint models are pinned to an accepting
route (config/models.yaml provider_pins).

Net: every routed model runs at effective top_p = **1.0** — but for TWO distinct, separately-recorded
reasons. The **Gemini divergence** is the reproducibility-relevant fact this table exists to capture:
Gemini's native default topP is ~0.95 and would apply if it were called directly (or if OpenRouter ever
stopped injecting); via OpenRouter it is 1.0.

CAVEAT (read-back): OpenRouter does not reliably echo the APPLIED top_p, so this cannot be confirmed
behaviorally from a response. The provenance below rests on OpenRouter + provider DOCS; ``verify_top_p``
re-checks the OBSERVABLE facts the determination depends on — each model still listed, top_p still
accepted/declined the same way on every endpoint, same upstream providers — and FAILS on any drift.
"""
from __future__ import annotations

import copy
from typing import Optional

from tup.client.config import load_config

# We never send top_p (locked decision). OpenRouter's documented default for an omitted top_p:
OPENROUTER_DEFAULT_TOP_P = 1.0
OPENROUTER_PARAMS_DOC = "https://openrouter.ai/docs/api/reference/parameters"

# Default ISO date the provenance below was verified against live provider / OpenRouter docs + the
# live API; rows re-verified later carry their own later date.
LAST_VERIFIED = "2026-07-31"

# Per-model effective top_p provenance. Keyed by the exact OpenRouter slug (matches config/models.yaml).
#   top_p         — the effective value that applies given we omit the parameter
#   basis         — WHY that value applies (the determination, in prose)
#   provider      — the upstream provider(s) OpenRouter was observed to route to (set; routing varies)
#   source_url    — the authoritative source for the effective value
#   last_verified — ISO date this row was verified
#   accepts_top_p — whether the model's endpoints accept top_p (decides injected-1.0 vs upstream-default;
#                   this is the field verify_top_p() gates on, since it determines the effective value)
EFFECTIVE_TOP_P: dict[str, dict] = {
    "openai/gpt-5.6-terra": {
        "top_p": 1.0,
        "basis": (
            "OpenAI GPT-5.x REASONING line — accepts NEITHER top_p NOR temperature on any endpoint "
            "(verified live 2026-07-31: all endpoints decline both). OpenRouter omits the params and "
            "OpenAI applies its fixed defaults; OpenAI states reasoning models 'only support the "
            "default (1) value'. Effective top_p 1.0, UNCONFIGURABLE; the configured advisor "
            "temperature 0.7 does NOT apply to this model (runs at model default) — documented "
            "sampling-coverage exception."
        ),
        "provider": ["Amazon Bedrock", "Azure", "OpenAI"],
        "source_url": "https://platform.openai.com/docs/api-reference/chat/create",
        "last_verified": LAST_VERIFIED,
        "accepts_top_p": False,
    },
    "anthropic/claude-sonnet-5": {
        "top_p": 1.0,
        "basis": (
            "Adaptive-thinking model — accepts NEITHER top_p NOR temperature on any endpoint "
            "(verified live 2026-07-31). OpenRouter omits the params; Anthropic's default sampling "
            "applies (nucleus off = effective 1.0). UNCONFIGURABLE; the advisor temperature 0.7 and "
            "panel-judge temperature 0.2 do NOT apply to this model — documented sampling-coverage "
            "exception."
        ),
        "provider": ["Amazon Bedrock", "Anthropic", "Azure", "Google"],
        "source_url": "https://docs.anthropic.com/en/api/messages",
        "last_verified": LAST_VERIFIED,
        "accepts_top_p": False,
    },
    "meta-llama/llama-3.3-70b-instruct": {
        "top_p": 1.0,
        "basis": (
            "Patient simulator (locked: the "
            "simulator must not be one of the five advisor models). Accepts top_p on every served "
            "endpoint -> OpenRouter injects its documented default top_p=1.0 for the omitted "
            "parameter before forwarding upstream. "
            "The provider list is the OBSERVED routing set (12 endpoints, re-verified live "
            "2026-08-05, top_p accepted unanimously); the run pins routing to DeepInfra/Novita for "
            "price stability, which is recorded separately in config/models.yaml provider_pins."
        ),
        "provider": ["AkashML", "Cloudflare", "CoreWeave", "Crusoe", "DeepInfra", "Google", "Groq",
                     "Nebius", "Novita", "Parasail", "SambaNova", "Together"],
        "source_url": OPENROUTER_PARAMS_DOC,
        "last_verified": "2026-08-05",
        "accepts_top_p": True,
    },
    "meta-llama/llama-4-maverick": {
        "top_p": 1.0,
        "basis": (
            "Accepts top_p on every served endpoint → OpenRouter injects its documented default "
            "top_p=1.0 for the omitted parameter before forwarding upstream."
        ),
        "provider": ["DeepInfra", "DigitalOcean", "Google", "Novita", "Parasail"],
        "source_url": OPENROUTER_PARAMS_DOC,
        "last_verified": LAST_VERIFIED,
        "accepts_top_p": True,
    },
    "google/gemini-3.6-flash": {
        "top_p": 1.0,
        "basis": (
            "SPLIT endpoints (verified live 2026-07-31): Google AI Studio endpoints accept "
            "top_p/temperature; Google Vertex endpoints do not. TUP PINS routing to Google AI Studio "
            "(config/models.yaml provider_pins + allow_fallbacks:false), so on the pinned route "
            "OpenRouter injects its documented default top_p=1.0 for the omitted parameter and the "
            "configured temperatures apply. The unanimity check is replaced by the pin check for "
            "this entry."
        ),
        "provider": ["Google", "Google AI Studio"],
        "pinned_provider": "Google AI Studio",
        "source_url": OPENROUTER_PARAMS_DOC,
        "last_verified": LAST_VERIFIED,
        "accepts_top_p": True,
        "native_default_note": (
            "Gemini native topP ~0.95 would apply on an unpinned Vertex route (which rejects the "
            "param) — the AI-Studio pin is what keeps the effective value at the injected 1.0."
        ),
    },
    "google/gemini-3.5-flash-lite": {
        "top_p": 1.0,
        "basis": (
            "GUARD-ONLY slug (patient role-compliance classifier). SPLIT endpoints "
            "(verified live 2026-08-03, same shape as gemini-3.6-flash): Google AI Studio endpoints "
            "accept top_p/temperature; Google Vertex endpoints do not. TUP PINS routing to Google AI "
            "Studio (config/models.yaml provider_pins + allow_fallbacks:false), so on the pinned "
            "route OpenRouter injects its documented default top_p=1.0 for the omitted parameter and "
            "the guard temperature 0.0 applies. Non-reasoning model — required because MANDATORY "
            "hidden reasoning empties guard verdicts at the small guard token cap."
        ),
        "provider": ["Google", "Google AI Studio"],
        "pinned_provider": "Google AI Studio",
        "source_url": OPENROUTER_PARAMS_DOC,
        "last_verified": "2026-08-03",
        "accepts_top_p": True,
    },
    "x-ai/grok-4.3": {
        "top_p": 1.0,
        "basis": (
            "Accepts top_p on every served endpoint → OpenRouter injects its documented default "
            "top_p=1.0 for the omitted parameter before forwarding upstream."
        ),
        "provider": ["xAI"],
        "source_url": OPENROUTER_PARAMS_DOC,
        "last_verified": LAST_VERIFIED,
        "accepts_top_p": True,
    },
}


def effective_top_p_record() -> dict:
    """The provenance record to embed in run metadata under ``reproducibility.effective_top_p`` (PROJECT_SPEC.md section 14).

    Returns a deep copy so callers embedding it in a manifest cannot mutate the module table.
    """
    return {
        "policy": "top_p omitted from all requests (provider/OpenRouter default applies)",
        "openrouter_default_top_p": OPENROUTER_DEFAULT_TOP_P,
        "openrouter_params_doc": OPENROUTER_PARAMS_DOC,
        "last_verified": LAST_VERIFIED,
        "models": copy.deepcopy(EFFECTIVE_TOP_P),
    }


# ----------------------------- live verification -----------------------------
def fetch_live_facts(slugs, *, api_key: Optional[str] = None, base_url: Optional[str] = None) -> dict:
    """Fetch the OBSERVABLE top_p facts for ``slugs`` from the live OpenRouter API (stdlib only).

    For each slug returns ``{present, models_accepts_top_p, endpoint_top_p (set of bools), providers
    (set)}`` — drawn from ``GET /models`` (model-level ``supported_parameters``) and
    ``GET /models/{slug}/endpoints`` (per-endpoint ``supported_parameters`` + ``provider_name``).
    Network/stdlib only so it has no heavy deps; mock it (or pass ``live_facts``) in tests.
    """
    import json
    import urllib.request

    from tup.client.config import load_api_key, load_base_url

    key = api_key or load_api_key()
    base = (base_url or load_base_url()).rstrip("/")

    def _get(url: str) -> dict:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (trusted OpenRouter URL)
            return json.loads(r.read().decode())

    all_models = {m.get("id"): m for m in _get(f"{base}/models").get("data", [])}
    facts: dict[str, dict] = {}
    for slug in slugs:
        m = all_models.get(slug)
        if m is None:
            facts[slug] = {"present": False}
            continue
        endpoints = _get(f"{base}/models/{slug}/endpoints").get("data", {}).get("endpoints", [])
        facts[slug] = {
            "present": True,
            "models_accepts_top_p": "top_p" in (m.get("supported_parameters") or []),
            "endpoint_top_p": {("top_p" in (e.get("supported_parameters") or [])) for e in endpoints},
            "providers": {e.get("provider_name") for e in endpoints if e.get("provider_name")},
        }
    return facts


def _check_one(slug: str, recorded: dict, live: dict) -> list[str]:
    """Compare one model's recorded provenance against its live facts; return drift messages."""
    drift: list[str] = []
    if not live.get("present"):
        return [f"{slug}: NOT FOUND on the live OpenRouter model list (was recorded; routing/slug drift)"]

    accepts = recorded["accepts_top_p"]
    # (1) model-level top_p acceptance — this is what decides injected-1.0 vs upstream-default.
    if live.get("models_accepts_top_p") != accepts:
        drift.append(
            f"{slug}: top_p acceptance changed — recorded accepts_top_p={accepts}, live="
            f"{live.get('models_accepts_top_p')}. This CHANGES the effective top_p; re-derive the basis."
        )
    # (2) endpoints must UNANIMOUSLY agree with the recorded acceptance (a split = ambiguous effective
    # value) — UNLESS the entry declares a routing pin, in which case the pin (not unanimity) is what
    # fixes the effective value: require the pinned provider to still be live instead.
    ep = live.get("endpoint_top_p") or set()
    pinned = recorded.get("pinned_provider")
    if pinned:
        if pinned not in (live.get("providers") or set()):
            drift.append(
                f"{slug}: pinned provider {pinned!r} no longer among live endpoints "
                f"({sorted(live.get('providers') or [])}) — the routing pin cannot hold; re-derive."
            )
    elif ep and ep != {accepts}:
        drift.append(
            f"{slug}: served endpoints disagree on top_p support (live endpoint values={sorted(ep)}, "
            f"recorded={accepts}) — the effective top_p is no longer uniform across routing."
        )
    # (3) upstream provider set — strict: a model that routes differently must be re-verified.
    rec_provs = set(recorded.get("provider") or [])
    live_provs = set(live.get("providers") or set())
    if live_provs and live_provs != rec_provs:
        added = sorted(live_provs - rec_provs)
        removed = sorted(rec_provs - live_provs)
        drift.append(
            f"{slug}: upstream routing changed — added {added}, removed {removed}. "
            f"Re-verify each new endpoint accepts top_p the same way, then update EFFECTIVE_TOP_P['{slug}']"
            f"['provider'] + last_verified. (Effective top_p unaffected IF top_p handling is unchanged.)"
        )
    return drift


def verify_top_p(live: bool = True, *, live_facts: Optional[dict] = None, config=None) -> tuple[bool, list[str]]:
    """Verify the recorded top_p provenance is still consistent. Returns ``(ok, drift_messages)``.

    Always checks (offline): every model slug in ``config/models.yaml`` has a provenance entry here, and
    no recorded entry is stale-extra. With ``live=True`` it ALSO fetches the OpenRouter API and checks,
    per model: still listed, top_p still accepted/declined as recorded on EVERY endpoint, and the same
    upstream providers. ``live_facts`` may be supplied (e.g. by tests) to skip the network.

    Call sites: ``scripts/check_top_p.py`` (the on-demand gate) and the launcher preflight in
    ``scripts/run_experiment.py`` (alongside ``validate_models()``).
    """
    cfg = config or load_config()
    configured = set(cfg.providers.values())
    if getattr(cfg, "patient_model", None):
        configured.add(cfg.patient_model)   # per-role override slug is live-used; verify it too
    if getattr(cfg, "guard_model", None):
        configured.add(cfg.guard_model)     # guard classifier slug is live-used; verify it too
    drift: list[str] = []

    # offline: config <-> table consistency (catches a model swapped in config without a provenance row)
    missing = sorted(configured - set(EFFECTIVE_TOP_P))
    extra = sorted(set(EFFECTIVE_TOP_P) - configured)
    if missing:
        drift.append(f"config models with no top_p provenance entry: {missing} (add them to EFFECTIVE_TOP_P)")
    if extra:
        drift.append(f"provenance entries not in config/models.yaml: {extra} (stale — remove or update config)")

    if live:
        slugs = sorted(configured)
        facts = live_facts if live_facts is not None else fetch_live_facts(slugs)
        for slug in slugs:
            if slug not in EFFECTIVE_TOP_P:
                continue  # already reported as missing above
            drift.extend(_check_one(slug, EFFECTIVE_TOP_P[slug], facts.get(slug, {"present": False})))

    return (not drift), drift
