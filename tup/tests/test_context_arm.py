"""Barrier-as-context arm: profile rendering + advisor system-message injection."""
from __future__ import annotations

import pytest

from tup.data.prompts import CONTEXT_ARMS, load_families, get_family, render_advisor_context

FAMILY_NAMES = ["control", "caregiving", "transport_ambulance_cost", "work",
                "cost_medical_debt", "no_insurance", "hospital_fear"]


def test_none_arm_renders_nothing():
    fams = load_families()
    for name in FAMILY_NAMES:
        assert render_advisor_context(get_family(fams, name), "none") is None


@pytest.mark.parametrize("fam_name", FAMILY_NAMES)
def test_barrier_arm_renders_third_person_profile(fam_name):
    fams = load_families()
    asset = render_advisor_context(get_family(fams, fam_name), "barrier")
    assert asset is not None and asset.text.strip()
    assert "Saved context about this user" in asset.text          # memory framing present
    body = asset.text.lower()
    import re
    for banned in ("er", "emergency", "911"):
        # word-boundary match so "emergency," / trailing "er." are caught too
        assert not re.search(rf"\b{banned}\b", body)  # no venue/urgency words
    # The PROFILE portion (after the template) is third-person about the user — never "you"/"your"
    # (the template itself may address the advisor as "you"; that's its job).
    profile = asset.text.split("\n\n", 1)[1].lower()
    words = profile.replace(",", " ").replace(".", " ").split()
    assert "you" not in words and "your" not in words
    assert len(asset.sha256) == 64 and asset.version is not None


def test_control_profile_is_neutral():
    fams = load_families()
    ctrl = render_advisor_context(get_family(fams, "control"), "barrier").text.lower()
    for token in ("insurance", "caregiver", "shift", "bus", "bill", "debt"):
        assert token not in ctrl                                   # control profile carries no barrier


def test_unknown_arm_rejected():
    fams = load_families()
    with pytest.raises(ValueError, match="context_arm"):
        render_advisor_context(get_family(fams, "control"), "profile_no_barrier")
    assert CONTEXT_ARMS == ("none", "barrier")


def test_runner_injects_context_as_system_message(monkeypatch):
    """In the barrier arm the advisor's messages start with the profile system message; in the
    none arm they don't (locked Option A)."""
    from tup.orchestration import runner as rn
    from tup.data.vignettes import load_vignettes

    fams = load_families()
    fam = get_family(fams, "work")
    v = load_vignettes()[0]
    captured = {}

    from tup.client.types import Sampling

    class FakeClient:
        class config:  # noqa: N801 — minimal stand-in
            seed = 1
            sampling = {"advisor": Sampling(0.7, 8192), "patient": Sampling(0.9, 4096)}
        registry = None

        def resolve_model(self, role, provider=None):
            return "prov/model"

        def complete(self, role, messages, provider=None, seed=None, cache_salt=None, session_id=None):
            if role == "advisor" and "advisor_msgs" not in captured:
                captured["advisor_msgs"] = messages

            class R:
                content = "ok"
                model = "prov/model"
                finish_reason = "stop"
                usage = None
                generation_id = None
                served_model = None
                provider = None
                truncated = False
                cached = False
            return R()

    conv = rn.run_conversation(FakeClient(), v, fam, "openai", families=fams,
                               max_turns=1, context_arm="barrier")
    msgs = captured["advisor_msgs"]
    assert msgs[0]["role"] == "system" and "Saved context about this user" in msgs[0]["content"]
    assert conv.metadata["context_arm"] == "barrier"
    assert conv.metadata["advisor_context"]["sha256"]

    captured.clear()
    conv2 = rn.run_conversation(FakeClient(), v, fam, "openai", families=fams,
                                max_turns=1, context_arm="none")
    assert captured["advisor_msgs"][0]["role"] == "user"          # Option A: no system message
    assert conv2.metadata["context_arm"] == "none"
    assert conv2.metadata["advisor_context"] is None


def test_every_advisor_profile_still_mirrors_its_patient_scenario():
    """The context arm's profiles are a hand-written third-person mirror of families.yaml scenarios.

    Two files, one silently stale: an edit to a scenario that never revisits its mirror leaves the
    context-arm advisor being told the very facts the edit removed.

    Nothing can diff prose semantically, so each profile records the hash of the scenario it mirrors.
    Editing a scenario without revisiting its profile now fails here instead of shipping silently.
    """
    import hashlib
    import yaml
    from tup.data.prompts import ADVISOR_CONTEXT, load_families

    doc = yaml.safe_load(ADVISOR_CONTEXT.read_text())
    scenarios = {f["name"]: f["scenario"] for f in load_families()["families"]}
    recorded = doc.get("mirrors_scenario_sha256") or {}

    assert set(doc["profiles"]) == set(scenarios), "every family needs a profile (the context arm KeyErrors otherwise)"
    assert set(recorded) == set(scenarios), "every profile must record the scenario it mirrors"

    stale = [n for n, h in recorded.items()
             if hashlib.sha256(scenarios[n].strip().encode("utf-8")).hexdigest() != h]
    assert stale == [], (
        f"scenario changed without revisiting its advisor profile: {stale}. Update the profile text "
        f"in prompts/advisor/context_profiles.yaml, then refresh its entry in mirrors_scenario_sha256."
    )
