"""Load + validate ``config/models.yaml`` and OpenRouter credentials."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from tup.client.types import Config, Sampling

REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_YAML = REPO_ROOT / "config" / "models.yaml"
ENV_PATH = REPO_ROOT / ".env"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_VAR = "OPENROUTER_TUP_API_KEY"
FALLBACK_API_KEY_VAR = "OPENROUTER_API_KEY"   # the generic name; honored so a standard setup works


def load_config(path: Path = MODELS_YAML) -> Config:
    """Parse models.yaml into a Config, validating structure + provider references."""
    raw = yaml.safe_load(Path(path).read_text())
    try:
        providers = dict(raw["providers"])
        roles = raw["roles"]
        advisors = list(roles["advisors"])
        patient = roles["patient"]
        judge_panel = int(roles["judge_panel"])   # panel size (the run of record: 3)
        patient_model = roles.get("patient_model")   # optional per-role slug override
        guard_model = roles.get("guard_model")       # optional guard classifier slug (None => guard off)
        provider_pins = raw.get("provider_pins") or None
        sampling = {
            role: Sampling(temperature=float(s["temperature"]), max_tokens=int(s["max_tokens"]))
            for role, s in raw["sampling"].items()
        }
        seed = int(raw["seed"])
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed {path}: missing/invalid key {e}") from e

    referenced = set(advisors) | {patient}
    missing = referenced - set(providers)
    if missing:
        raise ValueError(f"roles reference provider(s) absent from `providers`: {sorted(missing)}")

    return Config(
        providers=providers,
        advisors=advisors,
        patient=patient,
        sampling=sampling,
        seed=seed,
        judge_panel=judge_panel,
        patient_model=patient_model,
        provider_pins=provider_pins,
        guard_model=guard_model,
    )


def load_api_key() -> str:
    """Return the OpenRouter key from .env.

    Prefers OPENROUTER_TUP_API_KEY (the canonical, project-scoped name), falling back to the
    generic OPENROUTER_API_KEY so a standard OpenRouter setup works unchanged.
    """
    load_dotenv(ENV_PATH)
    key = os.getenv(API_KEY_VAR) or os.getenv(FALLBACK_API_KEY_VAR)
    if not key:
        raise ValueError(f"{API_KEY_VAR} (or {FALLBACK_API_KEY_VAR}) not set (looked in {ENV_PATH})")
    return key


def load_base_url() -> str:
    load_dotenv(ENV_PATH)
    return os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL)
