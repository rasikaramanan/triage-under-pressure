"""Prompt loading + rendering: slot filling (all families), conditional resistance, opener, Option A/B."""
from __future__ import annotations

import pytest

from tup.data import prompts
from tup.data.prompts import (
    build_opener,
    get_family,
    load_advisor_info,
    load_advisor_system,
    load_families,
    render_allowed,
    render_patient_system,
)
from tup.data.vignettes import Vignette

V = Vignette(
    id="001", slug="asthma", condition="Acute asthma exacerbation",
    text="I'm 36 and my breathing is a lot worse than usual.",
    source_key="chatgpthealth2026triage", psychiatric=False, self_harm=False, review_status="locked",
)

FAMILY_NAMES = [  # all seven conditions
    "control", "caregiving", "transport_ambulance_cost", "work", "cost_medical_debt",
    "no_insurance", "hospital_fear"]


@pytest.mark.parametrize("fam_name", FAMILY_NAMES)
def test_render_fills_every_slot_for_all_families(fam_name):
    fams = load_families()
    f = get_family(fams, fam_name)
    asset = render_patient_system(V, f, fams)
    assert "<<" not in asset.text and ">>" not in asset.text   # no slot left unfilled
    assert V.text in asset.text                                # vignette verbatim
    assert f["scenario"] in asset.text
    assert f["core_barrier"] in asset.text
    assert f["not_allowed"] in asset.text
    for rung in f["allowed"]:
        assert rung in asset.text
    assert asset.version is not None and len(asset.sha256) == 64


def test_family_label_not_injected():
    fams = load_families()
    asset = render_patient_system(V, get_family(fams, "transport_ambulance_cost"), fams)
    assert "transport_ambulance_cost" not in asset.text   # taxonomy must not leak to the patient


def test_control_omits_resistance_block_barrier_includes_it():
    fams = load_families()
    first_line = fams["resistance_section"].strip().splitlines()[0]
    ctrl = render_patient_system(V, get_family(fams, "control"), fams)
    work = render_patient_system(V, get_family(fams, "work"), fams)
    assert first_line not in ctrl.text   # control (resists: false) -> empty RESISTANCE_SECTION
    assert first_line in work.text       # barrier (resists: true) -> shared block injected


def test_resists_flag_invariant():
    by = {f["name"]: f for f in load_families()["families"]}
    assert by["control"]["resists"] is False
    for n in FAMILY_NAMES[1:]:
        assert by[n]["resists"] is True   # the single cross-condition confound control


def test_families_structure():
    fams = load_families()
    assert "resistance_section" in fams
    # id 6 (hospital_fear) — the NON-STRUCTURAL comparator: same
    # resistance directive as families 1-5, obstacle is dread rather than money/transport/
    # dependents/job, so structural-vs-fear isolates the obstacle holding pushback constant.
    assert [f["id"] for f in fams["families"]] == [0, 1, 2, 3, 4, 5, 6]
    for f in fams["families"]:
        assert len(f["allowed"]) == 6     # six rungs per family (families.yaml's own stated invariant)
        assert f["scenario"].strip()      # every family (incl. control) carries a scenario
        for banned in ("ER", "911", "emergency"):
            assert banned not in f["scenario"]  # scenario never names a venue or urgency


def test_get_family_by_id_and_miss():
    fams = load_families()
    assert get_family(fams, 4)["name"] == "cost_medical_debt"   # int-id lookup
    with pytest.raises(KeyError):
        get_family(fams, "nope")
    with pytest.raises(KeyError):
        get_family(fams, 99)


def test_render_allowed_bullets_and_empty():
    assert render_allowed(["a", "b"]) == "- a\n   - b"   # continuation indented to the slot column
    assert render_allowed([]) == ""


def test_advisor_is_option_a_no_system():
    assert load_advisor_system() is None       # empty body => no system message
    info = load_advisor_info()
    assert info["has_system"] is False
    assert info["version"] is not None         # the declared version still lands in run metadata


def test_advisor_option_b_records_version(tmp_path, monkeypatch):
    f = tmp_path / "advisor.md"
    f.write_text("---\nagent: advisor\nversion: 2\noption: B\n---\nYou are a medical assistant.\n")
    monkeypatch.setattr(prompts, "ADVISOR_SYSTEM", f)
    monkeypatch.setattr(prompts, "REPO_ROOT", tmp_path)  # so _rel(f) resolves
    asset = load_advisor_system()
    assert asset is not None
    assert asset.version == 2
    assert asset.text.strip() == "You are a medical assistant."
    assert len(asset.sha256) == 64 and asset.sha256 == prompts._sha(asset.text)
    info = load_advisor_info()
    assert info["version"] == 2 and info["option"] == "B" and info["has_system"] is True


def test_build_opener_is_verbatim_plus_fixed_question():
    op = build_opener(V)
    assert op.startswith(V.text)
    assert op.endswith("what should i do?")
    assert "ER" not in op and "911" not in op and "emergency" not in op.lower()


def test_render_judge_fills_vignette_text_and_transcript():
    from tup.data.prompts import load_judge_prompt, render_judge

    asset = load_judge_prompt()
    assert asset.version is not None and len(asset.sha256) == 64
    transcript = "Patient: hi\n\nAdvisor (response 1): go to the ER now"
    filled = render_judge(asset.text, V, transcript)
    assert V.text in filled                                    # vignette TEXT (not gold) injected
    assert transcript in filled
    assert "<<VIGNETTE>>" not in filled and "<<CONVERSATION_TRANSCRIPT>>" not in filled
    assert "<<" not in filled


def test_patient_background_renders_only_when_present_and_strips_annotations():
    from tup.data.prompts import render_patient_background
    from tup.data.vignettes import load_vignette

    fams = load_families()
    fam = get_family(fams, "control")

    v13 = load_vignette("013")
    asset = render_patient_system(v13, fam, fams)
    assert "If the assistant asks about you" in asset.text
    assert "no chest pain at all" in asset.text
    assert "You smoke." not in asset.text   # redundant with the opener's "I smoke."
    # "row-68" = the 013 deposit-row locator string — provenance-only, never patient-visible
    for leak in ("(Source:", "(Deposited", "ENTAILED", "TUP-ADDED", "⚠", "row-68"):
        assert leak not in asset.text, leak

    v14 = load_vignette("014")
    a14 = render_patient_system(v14, fam, fams)
    assert "32 weeks" in a14.text and "TUP-ADDED" not in a14.text

    v04 = load_vignette("004")
    a04 = render_patient_system(v04, fam, fams)
    assert "## If the assistant asks about you" not in a04.text   # empty background -> no section
    assert "<<" not in a04.text

    assert render_patient_background(()) == ""


def test_nonstructural_comparator_is_fenced_from_the_structural_families():
    """The fear family must carry the resistance directive but NO structural obstacle.

    If it drifts into money/transport/dependents/work content the structural-vs-fear contrast
    collapses, since that contrast exists precisely to hold pushback constant while varying whether
    the obstacle is structural.
    """
    fams = load_families()
    fear = next(f for f in fams["families"] if f["name"] == "hospital_fear")
    assert fear["resists"] is True, "must carry the same resistance directive as families 1-5"
    fence = fear["not_allowed"].lower()
    for absent in ("money", "transport", "depend", "work"):
        assert absent in fence, f"the fence must explicitly disclaim {absent!r}"
    blob = (fear["scenario"] + " " + fear["core_barrier"]).lower()
    for structural in ("insurance", "afford", "bill", "shift", "boss", "caregiver"):
        assert structural not in blob, f"non-structural comparator leaked structural content: {structural!r}"


def test_analysis_classes_every_family_and_pools_only_structural_ones():
    """'Everything that isn't control' is not a safe definition of 'barrier': the seventh family resists without a structural obstacle."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "analysis"))
    import analyze_experiment as R

    names = {f["name"] for f in load_families()["families"]}
    assert set(R.FAMILY_CLASS) == names, "every family must be classed explicitly"
    assert "hospital_fear" not in R.STRUCTURAL and R.FAMILY_CLASS["hospital_fear"] == "nonstructural"
    assert set(R.STRUCTURAL) == names - {"control", "hospital_fear"}


@pytest.mark.parametrize("path", [prompts.PATIENT_SYSTEM, prompts.JUDGE_SYSTEM, prompts.ADVISOR_SYSTEM])
def test_frontmatter_slots_match_the_body_placeholders(path):
    """Each prompt's `slots:` front-matter lists exactly the `<<NAME>>` placeholders its body carries."""
    import re
    from tup.data.frontmatter import split_frontmatter
    fm, body = split_frontmatter(path.read_text())
    assert set(fm.get("slots") or []) == set(re.findall(r"<<([A-Z_]+)>>", body))

