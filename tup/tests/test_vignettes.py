"""Vignette loader: real corpus + filter branches (cohort / locked / MH) on a synthetic corpus."""
from __future__ import annotations

import yaml

from tup.data import vignettes
from tup.data.vignettes import load_vignette, load_vignettes


def test_default_load_returns_full_locked_study_set():
    # Default = the locked set: all 14 locked vignettes across cohorts.
    vs = load_vignettes()
    assert {v.id for v in vs} == {f"{i:03d}" for i in range(1, 15)}
    for v in vs:
        assert v.text.strip()
        assert v.review_status == "locked"
        assert not v.psychiatric and not v.self_harm   # the set contains no mental-health vignette
        assert v.condition                             # populated from provenance frontmatter
    assert {v.id for v in load_vignettes(cohort="pilot")} == {"001", "002", "003", "004", "005", "006"}
    # everything in the real corpus is locked, so lifting the lock filter changes nothing
    assert {v.id for v in load_vignettes(require_locked=False)} == {f"{i:03d}" for i in range(1, 15)}


def test_vignette_text_has_no_frontmatter_or_appended_question():
    v = load_vignette("001")
    assert v.slug == "asthma"
    assert not v.text.startswith("---")
    assert "?" not in v.text   # VIGNETTE_SPEC rule 6: no triage question in the file


def _write(d, name, fm):
    (d / f"{name}.md").write_text("I feel unwell.")
    prov = d / "provenance"
    prov.mkdir(exist_ok=True)
    (prov / f"{name}.md").write_text("---\n" + yaml.safe_dump(fm) + "---\nprovenance body\n")


def test_filter_branches(tmp_path, monkeypatch):
    monkeypatch.setattr(vignettes, "VIGNETTES_DIR", tmp_path)
    base = {"condition": "X", "source_key": "s", "cohort": "pilot",
            "review_status": "locked", "psychiatric": False, "self_harm": False}
    _write(tmp_path, "001_ok", {**base})
    _write(tmp_path, "002_draft", {**base, "review_status": "draft"})
    _write(tmp_path, "003_psych", {**base, "psychiatric": True})
    _write(tmp_path, "004_sh", {**base, "self_harm": True})
    _write(tmp_path, "005_full", {**base, "cohort": "full"})
    ids = lambda vs: sorted(v.id for v in vs)

    assert ids(load_vignettes()) == ["001", "005"]                           # DEFAULT = all cohorts, locked, non-mental-health
    assert ids(load_vignettes(cohort="pilot")) == ["001"]                    # explicit pilot cohort
    assert ids(load_vignettes(require_locked=False)) == ["001", "002", "005"]  # +draft
    assert ids(load_vignettes(exclude_mh=False)) == ["001", "003", "004", "005"]  # +psychiatric +self_harm
    assert ids(load_vignettes(cohort=None)) == ["001", "005"]                # explicit None matches default


def test_missing_provenance_yields_empty_metadata_and_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(vignettes, "VIGNETTES_DIR", tmp_path)
    (tmp_path / "009_orphan.md").write_text("symptoms only, no provenance")
    assert load_vignettes() == []                          # no provenance -> review_status '' -> dropped
    v = load_vignette("009")                                # direct load still works, metadata empty
    assert v.condition == "" and v.review_status == ""


def test_expansion_vignettes_load_with_background():
    """The 007-014 expansion cohort loads with its opener + background answer bank."""
    from tup.data.vignettes import load_vignettes

    vs = {v.id: v for v in load_vignettes(cohort="expansion", require_locked=False)}
    assert set(vs) == {f"{i:03d}" for i in range(7, 15)}
    for v in vs.values():
        assert v.review_status == "locked"   # the set is closed and locked
        assert v.text and len(v.text) <= 700
        for banned in ("ER", "911", "emergency"):   # expansion cohort only: 001's source text
            assert banned not in v.text                  # itself says "no recent ER visits"
    assert vs["013"].patient_background             # deposited negatives present
    assert any("sexually active" in line for line in vs["012"].patient_background)


def test_pilot_vignette_backgrounds_match_their_dossiers():
    from tup.data.vignettes import load_vignettes

    # 006's background carries the bystander line (it is not in the opener); the other
    # base backgrounds are empty.
    by_id = {v.id: v for v in load_vignettes(cohort="pilot", require_locked=False)}
    assert any("Someone is at home" in line for line in by_id["006"].patient_background)
    assert by_id["004"].patient_background == () and by_id["005"].patient_background == ()


# ------------------------------------------------------------------- index.csv consistency
def test_index_csv_mirrors_the_dossier_frontmatter():
    """vignettes/index.csv is the human-browsable master index; every cell it shows must agree
    with the dossier frontmatter it mirrors (the data of record), both ways: no extra rows, no
    missing rows, no drifted values."""
    import csv
    from tup.client.config import REPO_ROOT
    from tup.data.frontmatter import split_frontmatter

    rows = {r["vignette_id"]: r
            for r in csv.DictReader((REPO_ROOT / "vignettes" / "index.csv").open(encoding="utf-8"))}
    dossiers = {}
    for f in sorted((REPO_ROOT / "vignettes" / "provenance").glob("[0-9]*.md")):
        meta, _ = split_frontmatter(f.read_text(encoding="utf-8"))
        dossiers[str(meta["vignette_id"])] = meta

    assert rows.keys() == dossiers.keys(), (
        f"index rows {sorted(rows)} != dossiers {sorted(dossiers)}")
    for vid, row in rows.items():
        meta = dossiers[vid]
        for col, key in (("source_key", "source_key"), ("condition", "condition"),
                         ("cohort", "cohort"), ("review_status", "review_status"),
                         ("gold_driver_preserved", "gold_driver_preserved")):
            assert str(row[col]) == str(meta[key]), (vid, col, row[col], meta[key])
