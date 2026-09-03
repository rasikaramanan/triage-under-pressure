"""The results store — the ONLY thing in the codebase allowed to construct a data path.

The contract this file pins down:

  * every data path resolves through the store, so no module ever builds one itself (the
    class that cannot ship publicly: absolute home-path constants and `ROOT / "runs"` scattered
    across scripts);
  * the store root is a property of the ENVIRONMENT (TUP_RESULTS_ROOT), never a per-invocation
    flag;
  * run ids are `<date>__<run-name>`, `__` is the field separator and is forbidden inside a run name,
    which is what makes the collision suffix parse unambiguously;
  * NOTHING is ever overwritten or truncated: a run-name+date that already holds records MINTS a new
    directory rather than appending to or clobbering the old one.
"""
from __future__ import annotations

import json

import pytest

from tup.store import (
    ARMS,
    ArmDir,
    InvalidRunNameError,
    RunNotFoundError,
    Store,
    parse_run_id,
    validate_run_name,
)


# ---------------------------------------------------------------------- run-name validation
@pytest.mark.parametrize("run_name", ["full_experiment", "full_run", "pilot", "a", "smoke8b", "run_2_arm"])
def test_valid_run_names_accepted(run_name):
    validate_run_name(run_name)      # must not raise


@pytest.mark.parametrize("run_name,why", [
    ("redo__run", "double underscore is the field separator"),
    ("Redo_run", "uppercase"),
    ("redo-run", "hyphen"),
    ("redo run", "space"),
    ("_redo", "leading underscore"),
    ("redo_", "trailing underscore"),
    ("", "empty"),
    ("redo/run", "path separator"),
    ("..", "path traversal"),
    ("redo.run", "dot"),
])
def test_invalid_run_names_rejected(run_name, why):
    with pytest.raises(InvalidRunNameError):
        validate_run_name(run_name)


def test_double_underscore_rejection_is_explicit_about_why():
    """`__` is load-bearing: it is what makes `<date>__<run-name>__2` parse unambiguously."""
    with pytest.raises(InvalidRunNameError, match="__"):
        validate_run_name("redo__run")


# --------------------------------------------------------------------------- run id parsing
def test_parse_run_id_without_suffix():
    assert parse_run_id("2026-08-05__full_experiment") == ("2026-08-05", "full_experiment", 1)


def test_parse_run_id_with_suffix():
    assert parse_run_id("2026-08-05__full_experiment__2") == ("2026-08-05", "full_experiment", 2)
    assert parse_run_id("2026-08-05__full_experiment__17") == ("2026-08-05", "full_experiment", 17)


def test_parse_run_id_roundtrips_a_run_name_containing_single_underscores():
    """The separator is `__`; single underscores inside the run name must survive."""
    assert parse_run_id("2026-08-05__a_b_c") == ("2026-08-05", "a_b_c", 1)


@pytest.mark.parametrize("bad", ["full_experiment", "2026-08-05", "2026-08-05__full_experiment__x",
                                 "2026-08-05__full_experiment__2__3", "notadate__full_experiment"])
def test_parse_run_id_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_run_id(bad)


# --------------------------------------------------------------------------- root resolution
def test_root_defaults_under_repo(monkeypatch):
    monkeypatch.delenv("TUP_RESULTS_ROOT", raising=False)
    from tup.client.config import REPO_ROOT
    assert Store.from_env().root == REPO_ROOT / "results"


def test_root_comes_from_the_environment_not_a_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path / "elsewhere"))
    assert Store.from_env().root == tmp_path / "elsewhere"


def test_store_lays_out_its_subdirectories(tmp_path):
    s = Store(tmp_path)
    assert s.runs_dir == tmp_path / "runs"
    assert s.dry_runs_dir == tmp_path / "dry_runs"
    assert s.analysis_dir == tmp_path / "analysis"
    assert s.stats_dir == tmp_path / "analysis" / "stats"
    assert s.figures_dir == tmp_path / "analysis" / "figures"
    assert s.viewer_dir == tmp_path / "analysis" / "viewer"
    assert s.cache_dir == tmp_path / "openrouter_cache"
    assert s.index_path == tmp_path / "index.json"


# --------------------------------------------------------------------------- run/arm layout
def test_run_dir_exposes_every_documented_file(tmp_path):
    r = Store(tmp_path).run("2026-08-05__full_experiment")
    assert r.path == tmp_path / "runs" / "2026-08-05__full_experiment"
    assert r.invocation_path.name == "invocation.json"
    assert r.readme_path.name == "README.md"
    assert r.launch_cmd_path.name == "LAUNCH_CMD.txt"
    assert r.quarantine_path == r.path / "exclusions" / "quarantine.json"


@pytest.mark.parametrize("arm", ARMS)
def test_arm_dir_exposes_the_seven_files(tmp_path, arm):
    a = Store(tmp_path).run("2026-08-05__full_experiment").arm(arm)
    assert a.path.name == arm
    names = {a.records_path.name, a.guard_path.name, a.failures_path.name, a.manifest_path.name,
             a.audit_sample_path.name, a.lock_verification_path.name, a.log_path.name}
    assert names == {"records.jsonl", "guard.jsonl", "failures.jsonl", "manifest.json",
                     "audit_sample.json", "lock_verification.json", "run.log"}


def test_arms_are_exactly_main_and_context():
    assert ARMS == ("main", "context")


def test_unknown_arm_rejected(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path).run("2026-08-05__full_experiment").arm("sideways")


def test_dry_run_store_uses_dry_runs_dir(tmp_path):
    s = Store(tmp_path)
    assert s.run("2026-08-05__x", dry_run=True).path == tmp_path / "dry_runs" / "2026-08-05__x"
    assert s.run("2026-08-05__x", dry_run=False).path == tmp_path / "runs" / "2026-08-05__x"


# --------------------------------------------------------------------------- minting / collision
def test_first_run_of_a_run_name_and_date_has_no_suffix(tmp_path):
    assert Store(tmp_path).mint_run_id_with_notice("full_experiment", "2026-08-05")[0] == "2026-08-05__full_experiment"


def test_mint_ignores_an_empty_directory(tmp_path):
    """A directory with no records is not a collision — only actual records are."""
    s = Store(tmp_path)
    s.run("2026-08-05__full_experiment").arm("main").path.mkdir(parents=True)
    assert s.mint_run_id_with_notice("full_experiment", "2026-08-05")[0] == "2026-08-05__full_experiment"


def _seed_records(store, run_id, arm="main", n=1):
    a = store.run(run_id).arm(arm)
    a.path.mkdir(parents=True, exist_ok=True)
    with a.records_path.open("a", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"conversation_id": f"c{i}"}) + "\n")


def test_collision_mints_a_numeric_third_field(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    assert s.mint_run_id_with_notice("full_experiment", "2026-08-05")[0] == "2026-08-05__full_experiment__2"


def test_collisions_keep_incrementing(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    _seed_records(s, "2026-08-05__full_experiment__2")
    _seed_records(s, "2026-08-05__full_experiment__3")
    assert s.mint_run_id_with_notice("full_experiment", "2026-08-05")[0] == "2026-08-05__full_experiment__4"


def test_collision_detects_records_in_either_arm(tmp_path):
    """Records in context/ alone still make the run id taken."""
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment", arm="context")
    assert s.mint_run_id_with_notice("full_experiment", "2026-08-05")[0] == "2026-08-05__full_experiment__2"


def test_a_different_date_does_not_collide(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    assert s.mint_run_id_with_notice("full_experiment", "2026-08-06")[0] == "2026-08-06__full_experiment"


def test_mint_validates_the_run_name(tmp_path):
    with pytest.raises(InvalidRunNameError):
        Store(tmp_path).mint_run_id_with_notice("redo__run", "2026-08-05")[0]


def test_collision_notice_names_both_ids_and_tells_the_operator_how_to_resume(tmp_path):
    """The requirement: an auto-mint must be loud, and must point at --continue."""
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    new_id, notice = s.mint_run_id_with_notice("full_experiment", "2026-08-05")
    assert new_id == "2026-08-05__full_experiment__2"
    assert "2026-08-05__full_experiment already has records" in notice
    assert "creating 2026-08-05__full_experiment__2" in notice
    assert "--continue 2026-08-05__full_experiment" in notice
    assert "stop now" in notice.lower()


def test_no_notice_when_there_is_no_collision(tmp_path):
    new_id, notice = Store(tmp_path).mint_run_id_with_notice("full_experiment", "2026-08-05")
    assert new_id == "2026-08-05__full_experiment" and notice is None


# --------------------------------------------------------------------------- never overwrite
def test_store_offers_no_way_to_truncate_a_run(tmp_path):
    """There is deliberately no delete/truncate/reset on the store API."""
    s = Store(tmp_path)
    for forbidden in ("truncate", "delete_run", "reset", "clear", "rm", "overwrite"):
        assert not hasattr(s, forbidden), f"store must not expose {forbidden}()"


# --------------------------------------------------------------------------- lookup
def test_list_runs_returns_sorted_ids(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-06__b_run")
    _seed_records(s, "2026-08-05__a_run")
    assert s.list_runs() == ["2026-08-05__a_run", "2026-08-06__b_run"]


def test_require_run_raises_with_near_matches(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    with pytest.raises(RunNotFoundError) as e:
        s.require_run("2026-08-05__redo_ru")
    assert "2026-08-05__full_experiment" in str(e.value)


def test_require_run_returns_the_run_when_it_exists(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__full_experiment")
    assert s.require_run("2026-08-05__full_experiment").run_id == "2026-08-05__full_experiment"


# --------------------------------------------------------------------------- arm state
def test_arm_reports_absent_when_no_records(tmp_path):
    a = Store(tmp_path).run("2026-08-05__x").arm("main")
    assert a.exists is False and a.record_ids() == set()


def test_arm_reads_record_ids_without_a_manifest(tmp_path):
    """Completion is derived FROM RECORDS: a hard crash leaves records with no manifest."""
    s = Store(tmp_path)
    _seed_records(s, "2026-08-05__x", n=3)
    a = s.run("2026-08-05__x").arm("main")
    assert a.exists is True
    assert a.record_ids() == {"c0", "c1", "c2"}
    assert a.manifest() is None


# --------------------------------------------------------------------------- studies
def _seed_study(store, study_id, arm, n=2):
    a = store.study(study_id).arm(arm)
    a.mkdir()
    with a.records_path.open("a", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"conversation_id": f"{arm}_c{i}"}) + "\n")


def test_a_study_takes_free_form_arm_names(tmp_path):
    """A study's arms ARE what it compares, so the store
    must not impose the run's main/context vocabulary on them."""
    st = Store(tmp_path).study("2026-08-06__patient_fidelity")
    for arm in ("incumbent_maverick", "llama33_70b", "qwen3_235b"):
        assert st.arm(arm).records_path.name == "records.jsonl"
        assert st.arm(arm).path.name == arm


def test_a_study_arm_name_is_still_validated(tmp_path):
    st = Store(tmp_path).study("2026-08-06__patient_fidelity")
    for bad in ("../escape", "Upper", "trailing_", "has space"):
        with pytest.raises(InvalidRunNameError):
            st.arm(bad)


def test_study_arms_are_read_from_disk_not_assumed(tmp_path):
    s = Store(tmp_path)
    for arm in ("single_message", "roleswap"):
        _seed_study(s, "2026-08-05__framing_ab", arm)
    assert [a.arm for a in s.study("2026-08-05__framing_ab").arms()] == ["roleswap", "single_message"]


def test_a_study_is_not_a_run_and_lives_somewhere_else(tmp_path):
    s = Store(tmp_path)
    assert s.study("2026-08-06__patient_fidelity").path.parent == s.studies_dir
    assert s.studies_dir != s.runs_dir


def test_studies_carry_the_same_identity_grammar_as_runs(tmp_path):
    with pytest.raises(ValueError):
        Store(tmp_path).study("patient_fidelity")       # no date field


def test_list_studies_ignores_strays(tmp_path):
    s = Store(tmp_path)
    _seed_study(s, "2026-08-06__patient_fidelity", "llama33_70b")
    (s.studies_dir / "notes.md").write_text("x", encoding="utf-8")
    (s.studies_dir / "scratch").mkdir()
    assert s.list_studies() == ["2026-08-06__patient_fidelity"]


def test_the_index_carries_studies_alongside_runs(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-06__full_experiment", n=4)
    _seed_study(s, "2026-08-05__framing_ab", "single_message", n=3)
    idx = s.build_index()
    assert idx["n_runs"] == 1 and idx["n_studies"] == 1
    assert idx["studies"][0]["arms"]["single_message"]["records"] == 3


def test_study_for_run_name_prefers_an_existing_study_over_todays_date(tmp_path):
    """A study runs over days: its arms are executed sequentially so each inherits the first arm's
    cached first advisor response. Minting from today's date on every launch would put a resume in
    a different directory from the work it resumes — unmatching the arms and re-paying every cell."""
    s = Store(tmp_path)
    _seed_study(s, "2026-08-05__framing_ab", "roleswap")
    assert s.study_for_run_name("framing_ab", "2026-08-09").study_id == "2026-08-05__framing_ab"


def test_study_for_run_name_mints_todays_id_when_none_exists(tmp_path):
    assert Store(tmp_path).study_for_run_name("framing_ab", "2026-08-09").study_id == "2026-08-09__framing_ab"


def test_study_for_run_name_refuses_to_guess_between_two(tmp_path):
    s = Store(tmp_path)
    _seed_study(s, "2026-08-05__framing_ab", "roleswap")
    _seed_study(s, "2026-08-07__framing_ab", "roleswap")
    with pytest.raises(LookupError, match="share the run name"):
        s.study_for_run_name("framing_ab", "2026-08-09")


# --------------------------------------------------------------------------- quarantine keys
def _write_quarantine(store, run_id, doc):
    r = store.run(run_id)
    r.exclusions_dir.mkdir(parents=True, exist_ok=True)
    r.quarantine_path.write_text(json.dumps(doc), encoding="utf-8")
    return r


def test_quarantine_reads_the_context_arm_under_either_spelling(tmp_path):
    """The adjudicated files say `ctx`; the arm directory is named `context`. Both spellings must
    resolve to the context arm's exclusion set — a silently-dropped exclusion set still produces
    a number, which is the dangerous kind of wrong."""
    s = Store(tmp_path)
    r = _write_quarantine(s, "2026-08-06__x", {"main": ["a"], "ctx": ["b", "c"]})
    assert r.quarantine() == {"main": {"a"}, "context": {"b", "c"}}
    r2 = _write_quarantine(s, "2026-08-07__y", {"main": [], "context": ["d"]})
    assert r2.quarantine() == {"main": set(), "context": {"d"}}


def test_quarantine_unions_both_spellings_rather_than_picking_one(tmp_path):
    s = Store(tmp_path)
    r = _write_quarantine(s, "2026-08-06__x", {"ctx": ["b"], "context": ["c"]})
    assert r.quarantine()["context"] == {"b", "c"}


def test_absent_quarantine_is_distinguishable_from_an_empty_one(tmp_path):
    """'Not yet audited' and 'audited, excluded nothing' are different claims about the data."""
    s = Store(tmp_path)
    never = s.run("2026-08-06__x")
    assert never.has_quarantine() is False and never.quarantine() == {"main": set(), "context": set()}
    audited = _write_quarantine(s, "2026-08-07__y", {"main": [], "ctx": []})
    assert audited.has_quarantine() is True and audited.quarantine() == {"main": set(), "context": set()}


def test_a_commissioned_but_unspent_run_id_is_not_reused(tmp_path):
    """A preflight that wrote invocation.json then died leaves a run with ZERO records. Minting
    must treat that id as taken: reusing it would overwrite the write-once record with a different
    run's intent."""
    s = Store(tmp_path)
    run = s.run("2026-08-07__t", dry_run=True)
    run.path.mkdir(parents=True, exist_ok=True)
    run.invocation_path.write_text(json.dumps({"run_name": "t"}), encoding="utf-8")
    assert run.has_records() is False and run.is_commissioned() is True
    new_id, notice = s.mint_run_id_with_notice("t", "2026-08-07", dry_run=True)
    assert new_id == "2026-08-07__t__2"
    assert "invocation.json but no records" in notice
    # and the original record is untouched
    assert json.loads(run.invocation_path.read_text()) == {"run_name": "t"}


def test_an_empty_directory_still_does_not_force_a_suffix(tmp_path):
    """The other half of the rule: a bare directory is not a run."""
    s = Store(tmp_path)
    s.run("2026-08-07__t", dry_run=True).path.mkdir(parents=True, exist_ok=True)
    assert s.mint_run_id_with_notice("t", "2026-08-07", dry_run=True) == ("2026-08-07__t", None)


# --------------------------------------------------------------------------- hardening
def test_readers_return_nothing_rather_than_the_wrong_type(tmp_path):
    """A JSON list where a dict belongs must degrade to 'I have nothing' at the reader, never reach
    a caller's `.get(...)` as the wrong type (checked through scripts/build_index.py)."""
    s = Store(tmp_path)
    a = s.run("2026-08-06__x").arm("main"); a.mkdir()
    run = s.run("2026-08-06__x")
    run.exclusions_dir.mkdir(parents=True, exist_ok=True)
    for p in (a.manifest_path, a.lock_verification_path, run.invocation_path,
              run.quarantine_path):
        p.write_text("[1, 2, 3]", encoding="utf-8")
    assert a.manifest() is None and a.lock_verification() is None
    assert run.invocation() is None
    assert run.quarantine() == {"main": set(), "context": set()}   # no crash, no wrong answer


def test_a_malformed_sidecar_does_not_break_the_index(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-06__x", n=2)
    s.run("2026-08-06__x").arm("main").manifest_path.write_text("[]", encoding="utf-8")
    idx = s.build_index()                                   # must not raise
    assert idx["runs"][0]["arms"]["main"]["records"] == 2


def test_an_arm_cannot_claim_a_name_its_directory_contradicts(tmp_path):
    """Constructed directly, an ArmDir could claim arm='main' while pointing at context/ — writing
    barrier-context data into the no-context arm and labelling it as such."""
    with pytest.raises(ValueError, match="identity mismatch"):
        ArmDir(tmp_path / "context", "main")
    ArmDir(tmp_path / "main", "main")                       # the agreeing case is fine


def test_a_run_name_longer_than_the_filesystem_allows_is_refused_at_validation(tmp_path):
    """A 300-character run name passes every grammar check and would then fail in mkdir() with a raw
    OSError, after the preflight had already reported success."""
    with pytest.raises(InvalidRunNameError, match="limit is"):
        validate_run_name("a" * 300)
    validate_run_name("a" * 100)                                # exactly at the limit is fine


def test_a_run_id_has_exactly_one_spelling(tmp_path):
    """'__02' and '__2' parsed to the same run but named different directories, so one logical run
    could exist twice under two names."""
    with pytest.raises(ValueError, match="not canonical"):
        parse_run_id("2026-08-06__x__02")
    assert parse_run_id("2026-08-06__x__2") == ("2026-08-06", "x", 2)


def test_a_run_directory_may_not_be_a_link_out_of_the_store(tmp_path):
    """validate_run_name makes a traversing id unrepresentable, but a SYMLINK is another route to the
    same place: the id is legal and the writes land somewhere else entirely."""
    s = Store(tmp_path / "store")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    s.runs_dir.mkdir(parents=True)
    (s.runs_dir / "2026-08-06__escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside the store root"):
        s.run("2026-08-06__escape")
    # the same containment check must hold on the studies/ side
    s.studies_dir.mkdir(parents=True, exist_ok=True)
    (s.studies_dir / "2026-08-06__escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside the store root"):
        s.study("2026-08-06__escape")


def test_an_ordinary_run_directory_is_unaffected_by_the_containment_check(tmp_path):
    s = Store(tmp_path)
    _seed_records(s, "2026-08-06__normal", n=2)
    assert s.run("2026-08-06__normal").arm("main").record_ids() == {"c0", "c1"}
