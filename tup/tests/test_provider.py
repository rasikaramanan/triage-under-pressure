"""Provider registry + the leave-one-provider-out rule for the 3-judge panel."""
from __future__ import annotations

import dataclasses

import pytest

from tup.client.provider import ConstraintError, ProviderRegistry


def test_valid_config_passes(sample_config):
    ProviderRegistry(sample_config).validate_constraints()  # should not raise


def test_patient_may_share_advisor_provider(sample_config):
    # Exclusion is judge-vs-advisor ONLY — a patient sharing an
    # advisor's provider is VALID (config/models.yaml: meta advises and supplies the patient model).
    ok = dataclasses.replace(sample_config, patient="openai")  # openai is an advisor
    ProviderRegistry(ok).validate_constraints()  # should not raise


def test_slug_for_provider(sample_config):
    reg = ProviderRegistry(sample_config)
    assert reg.slug_for("xai") == "x-ai/grok-4.3"


def test_unknown_provider_raises(sample_config):
    reg = ProviderRegistry(sample_config)
    with pytest.raises(KeyError):
        reg.slug_for("nope")


# --------------------------- 3-judge panel (full run) ---------------------------
def _panel_config(sample_config):
    return dataclasses.replace(sample_config, advisors=list(sample_config.providers))


def test_panel_config_validates_with_all_providers_advising(sample_config):
    ProviderRegistry(_panel_config(sample_config)).validate_constraints()


def test_panel_for_excludes_advisor_and_rotates(sample_config):
    reg = ProviderRegistry(_panel_config(sample_config))
    seen_panels = set()
    for rotation in range(8):
        panel = reg.panel_for("openai", rotation)
        assert len(panel) == 3 and len(set(panel)) == 3
        assert "openai" not in panel                      # leave-one-provider-out
        assert panel == sorted(panel)                     # deterministic order
        seen_panels.add(tuple(panel))
    assert len(seen_panels) == 4                          # each eligible provider sits out in turn


def test_panel_for_unsatisfiable_raises(sample_config):
    small = dataclasses.replace(
        sample_config,
        providers={k: v for k, v in list(sample_config.providers.items())[:3]},
        advisors=list(sample_config.providers)[:3],
        judge_panel=3,
    )
    with pytest.raises(ConstraintError):
        ProviderRegistry(small).validate_constraints()
    with pytest.raises(ConstraintError):
        ProviderRegistry(small).panel_for(list(small.providers)[0], 0)
