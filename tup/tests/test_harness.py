"""Run harness: dry-run grid, resume skip-if-done, per-cell isolation, cost-cap abort.

Offline only — the MockSDK ($0, deterministic) drives the FULL real pipeline (client → runner → judge
→ persist → cost), so these exercise the harness without a network or API key.

Driver entrypoint is ``run_arm(client, arm_dir, ...)``:
``arm_dir`` is a :class:`tup.store.ArmDir`, which owns the arm's output files, and the locked
parameters (``max_spend``, ``max_turns``, ``replicates``) are required keywords with no
defaults. There is no ``resume=False``
(truncation) and no ``limit`` — partial grids are expressed as narrower slices; the truncation
absence is pinned below, the flag absences in test_no_absolute_paths.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import tup.harness.driver as drv
from tup.client.config import load_config
from tup.data.prompts import load_families
from tup.data.vignettes import load_vignettes
from tup.harness.driver import cell_id, run_arm
from tup.harness.mock import dry_run_client
from tup.orchestration.runner import run_conversation
from tup.orchestration.transcript import Conversation, Turn
from tup.output.persist import load_records
from tup.store import Store


def _client(cost=0.0):
    return dry_run_client(load_config(), cost=cost)


def _vigs(n=1):
    # require_locked=False: fixtures must be stable across lock/unlock cycles of the
    # vignette set; several mocks key on ids 001/002.
    return load_vignettes(require_locked=False)[:n]


def _fams(n=2):
    return load_families()["families"][:n]


def _arm(tmp_path, arm="main", rid="2026-01-01__t"):
    """A fresh :class:`tup.store.ArmDir` under an isolated dry-run store rooted at ``tmp_path``."""
    return Store(tmp_path).run(rid, dry_run=True).arm(arm)


#: The five required-keyword args every run_arm call must supply. Tests override individual keys
#: (especially max_spend in the budget-cap tests, which is the point of those tests) but otherwise
#: share these fixture defaults for the required arguments.
_REQ = dict(max_spend=50.0, max_turns=2, replicates=2)


# --------------------------- grid identity ---------------------------
def test_cell_id_matches_runner_conversation_id():
    v = _vigs(1)[0]
    fam = _fams(1)[0]
    conv = run_conversation(_client(), v, fam, "openai", replicate=2, max_turns=2)
    assert conv.conversation_id == cell_id(v.id, fam["name"], "openai", 2)


def test_full_grid_conversation_ids_are_unique():
    cfg = load_config()
    vigs = load_vignettes(require_locked=False)
    fams = load_families()["families"]
    ids = [cell_id(v.id, f["name"], a, r)
           for v in vigs for f in fams for a in cfg.advisors for r in range(3)]
    expected = len(vigs) * len(fams) * len(cfg.advisors) * 3
    assert len(ids) == expected and len(set(ids)) == expected   # no id collisions across the grid


# --------------------------- dry-run grid ----------------------------
def test_dry_run_grid_completes_persists_and_judges(tmp_path):
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                  advisors=["openai", "meta"], **dict(_REQ, replicates=2))
    assert rep.completed == 8 and rep.skipped == 0 and rep.failed == 0 and not rep.aborted
    recs = load_records(arm.records_path)
    assert len(recs) == 8
    ids = [r["conversation_id"] for r in recs]
    assert len(set(ids)) == 8                                   # unique conversation_ids
    assert all(r["judgment"]["status"] == "judged" for r in recs)
    assert all(r["judgment"]["init_correct"] in (0, 1) for r in recs)
    assert rep.cost.total_usd == 0.0 and not rep.cost.is_lower_bound


def test_narrower_grid_then_full_grid_resumes_the_added_cells(tmp_path):
    """There is no `limit` parameter (driver docstring: "nothing here truncates"). The
    real-world shape of "run part of the grid" is a narrower slice — fewer families/advisors —
    not a truncated attempt count. Running the full grid afterwards resumes:
    the narrower cells are skipped, only the newly-added ones run."""
    arm = _arm(tmp_path)
    kw = dict(_REQ, replicates=3)
    narrow = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1),
                     advisors=["openai"], **kw)
    assert narrow.n_cells == 3 and narrow.completed == 3
    assert len(load_records(arm.records_path)) == 3

    wide = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                   advisors=["openai", "meta"], **kw)
    assert wide.n_cells == 12          # full grid: 1 vignette x 2 families x 2 advisors x 3 replicates
    assert wide.skipped == 3 and wide.completed == 9
    assert len(load_records(arm.records_path)) == 12


# --------------------------- resume ----------------------------------
def test_resume_skips_done_cells_without_duplicating(tmp_path):
    arm = _arm(tmp_path)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], replicates=2)
    first = run_arm(_client(), arm, **kw)
    assert first.completed == 4 and first.skipped == 0
    n_after_first = len(load_records(arm.records_path))

    second = run_arm(_client(), arm, **kw)                       # rerun = everything already done
    assert second.completed == 0 and second.skipped == 4
    assert len(load_records(arm.records_path)) == n_after_first  # appended nothing; file not truncated


def test_store_mints_a_new_id_instead_of_truncating_a_resume(tmp_path):
    """Truncation is deliberately unrepresentable (driver docstring: "There is no resume=False:
    nothing here truncates. A fresh start is a NEW RUN ID, which the store mints rather than
    overwrites"). Prove the capability is absent two ways: (1) a second run_arm call against the SAME arm skips
    everything and appends nothing — there is no way to force a truncate-and-rerun; (2) the way to
    get a genuinely fresh start is store.mint_run_id, which mints a new id rather than reusing one
    that already has records."""
    store = Store(tmp_path)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], replicates=1)
    rid = store.mint_run_id_with_notice("noresume_run", "2026-01-01", dry_run=True)[0]
    arm = store.run(rid, dry_run=True).arm("main")

    first = run_arm(_client(), arm, **kw)
    assert first.completed == 2 and first.skipped == 0
    ids_after_first = {r["conversation_id"] for r in load_records(arm.records_path)}
    assert len(ids_after_first) == 2

    # no resume=False exists to force a truncate-and-rerun; a second call just resumes (skips all)
    second = run_arm(_client(), arm, **kw)
    assert second.completed == 0 and second.skipped == 2
    ids_after_second = {r["conversation_id"] for r in load_records(arm.records_path)}
    assert ids_after_second == ids_after_first                   # nothing appended, nothing duplicated

    # the only way to get a fresh start is a NEW run id — the store mints one rather than reusing
    # the one that already has records
    new_rid = store.mint_run_id_with_notice("noresume_run", "2026-01-01", dry_run=True)[0]
    assert new_rid != rid
    fresh_arm = store.run(new_rid, dry_run=True).arm("main")
    assert not fresh_arm.has_records()


def test_resume_tolerates_torn_final_line(tmp_path):
    arm = _arm(tmp_path)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], replicates=1)
    run_arm(_client(), arm, **kw)
    with arm.records_path.open("a") as f:
        f.write('{"conversation_id":"001__work__openai__r0","par')   # killed mid-append
    # resume must still read the 2 complete records back and skip them (not crash on the torn line)
    rep = run_arm(_client(), arm, **kw)
    assert rep.skipped == 2 and rep.completed == 0


# --------------------------- per-cell isolation ----------------------
def test_per_cell_isolation_logs_failure_and_continues(tmp_path, monkeypatch):
    arm = _arm(tmp_path)
    real = drv.run_conversation

    def flaky(client, v, fam, adv, **kw):
        if v.id == "002":
            raise RuntimeError("boom in 002")
        return real(client, v, fam, adv, **kw)

    monkeypatch.setattr(drv, "run_conversation", flaky)
    rep = run_arm(_client(), arm, vignettes=_vigs(2), families=_fams(1), advisors=["openai"],
                 now=lambda: "T", **dict(_REQ, replicates=1))
    # vignette 001 completes, vignette 002 fails — one bad cell never aborts the other
    assert rep.completed == 1 and rep.failed == 1 and not rep.aborted
    assert [r["conversation_id"] for r in load_records(arm.records_path)] == ["001__control__openai__r0"]
    fails = load_records(arm.failures_path)
    assert len(fails) == 1
    f = fails[0]
    assert f["conversation_id"] == "002__control__openai__r0"
    assert "boom in 002" in f["error"] and f["traceback"] and f["timestamp"] == "T"


# --------------------- per-cell isolation ---------------------------
def test_judge_failure_is_persisted_not_discarded(tmp_path, monkeypatch):
    """The soft-judge design:

    Discarding a fully-generated conversation when the judge raises is a failure in the
    SECONDARY outcome destroying the PRIMARY one, at the cost of re-running the turns. The
    transcript is the irreplaceable artifact; a judgment is re-derivable from it by
    scripts/rejudge.py. So the cell COMPLETES, carrying status "judge_failed".
    """
    def boom_judge(client, conv, v, **kw):
        raise RuntimeError("RateLimitError: 429 from the judge pool")

    monkeypatch.setattr(drv, "judge_conversation_panel", boom_judge)
    monkeypatch.setattr(drv, "judge_conversation_panel", boom_judge)  # real config runs panel mode
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2), advisors=["openai"],
                 now=lambda: "T", **dict(_REQ, replicates=1))
    assert rep.completed == 2 and rep.failed == 0 and not rep.aborted
    recs = load_records(arm.records_path)
    assert len(recs) == 2
    for r in recs:
        assert r["judgment"]["status"] == "judge_failed" and "429" in r["judgment"]["error"]
        assert r["turns"], "the generated transcript must survive a judge failure"
    # and such a record must never enter the metrics
    from tup.output.metrics import is_analyzable
    assert not any(is_analyzable(r) for r in recs)


def test_raising_progress_sink_does_not_miscount_persisted_cell(tmp_path):
    # the real CLI sink raises BrokenPipeError on a closed pipe (`| head`); it must NOT fail the cell
    def broken(_ev):
        raise BrokenPipeError("stdout closed")

    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"],
                 progress=broken, **dict(_REQ, replicates=1))
    assert rep.completed == 1 and rep.failed == 0 and not rep.aborted   # progress error didn't fail it
    assert len(load_records(arm.records_path)) == 1                     # persisted exactly once
    assert not Path(rep.failures_path).exists()                        # NOT logged as a failure


def test_failure_logging_error_does_not_abort_grid(tmp_path, monkeypatch):
    # even if the failures-manifest write throws (e.g. disk full — often the same fault that failed the
    # cell), the handler is total and the grid keeps going
    real = drv.run_conversation

    def flaky(client, v, fam, adv, **kw):
        if v.id == "002":
            raise RuntimeError("boom in 002")
        return real(client, v, fam, adv, **kw)

    def boom_append(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(drv, "run_conversation", flaky)
    monkeypatch.setattr(drv, "_append_failure", boom_append)
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(2), families=_fams(1), advisors=["openai"],
                 **dict(_REQ, replicates=1))
    assert rep.completed == 1 and rep.failed == 1 and not rep.aborted   # 002 failed, no propagation
    assert [r["conversation_id"] for r in load_records(arm.records_path)] == ["001__control__openai__r0"]


# --------------------------- cost cap --------------------------------
def test_max_spend_hard_abort_includes_judge(tmp_path):
    # every mock call costs $1; one 2-turn cell = 2 advisor + 1 patient + 3 judge seats (panel mode) = $6 > $3.5 cap
    arm = _arm(tmp_path)
    rep = run_arm(_client(cost=1.0), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai", "meta"], **dict(_REQ, replicates=2, max_spend=3.5))
    assert rep.aborted and "max-spend" in rep.abort_reason
    assert rep.completed == 1                                   # one cell ran ($6), then the cap stopped it
    assert rep.cost.judge_usd > 0 and rep.cost.total_usd >= 3.5  # the cap counts the judge call too


def test_resumed_prior_spend_counts_toward_cap(tmp_path):
    arm = _arm(tmp_path)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], replicates=1)
    run_arm(_client(cost=1.0), arm, **dict(kw, max_spend=50.0))    # spend ~ $12 over 2 cells (panel mode), persisted
    # a resumed run with a cap below the already-spent total must abort immediately, doing no new cells
    rep = run_arm(_client(cost=1.0), arm, vignettes=_vigs(1), families=_fams(3),
                 advisors=["openai"], **dict(_REQ, replicates=1, max_spend=1.0))
    assert rep.aborted and rep.completed == 0


def test_missing_cost_surfaced_as_lower_bound(tmp_path):
    arm = _arm(tmp_path)
    rep = run_arm(_client(cost=None), arm, vignettes=_vigs(1), families=_fams(1),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep.completed == 1
    assert rep.cost.is_lower_bound                              # cost=None turns + judge => lower bound flagged
    assert rep.cost.missing_cost_turns > 0


def test_missing_cost_fails_closed_before_next_cell(tmp_path):
    # cost=None => `spent` is a lower bound; the cap can't be trusted, so the run halts after the first
    # cell rather than sailing past the cap (a $0.01 cap must NOT silently complete the whole grid)
    arm = _arm(tmp_path)
    rep = run_arm(_client(cost=None), arm, vignettes=_vigs(1), families=_fams(3),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep.completed == 1 and rep.aborted
    assert "cost data missing" in rep.abort_reason


def test_cap_gate_counts_judge_not_just_turns(tmp_path):
    # one 2-turn cell = 3 turn-calls ($3) + 3 judge seats ($3) = $6. With a $3.50 cap, if the GATE counted
    # turns only ($3 < 3.5) both cells would run; because judge spend IS in `spent`, the 2nd cell is stopped.
    arm = _arm(tmp_path)
    rep = run_arm(_client(cost=1.0), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1, max_spend=3.5))
    assert rep.completed == 1 and rep.aborted and rep.cost.judge_usd > 0


# --------------------- new API: prior_spend + arm-derived context ----
def test_prior_spend_makes_the_cap_whole_run_not_per_arm(tmp_path):
    """`max_spend` caps the WHOLE RUN's cumulative cost. `prior_spend` carries what
    an earlier arm of the same run already cost, so the SAME nominal cap that a fresh arm could
    easily afford aborts immediately once an earlier arm's spend is carried forward."""
    run = Store(tmp_path).run("2026-01-01__t", dry_run=True)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], replicates=1,
             max_spend=50.0)
    main_rep = run_arm(_client(cost=1.0), run.arm("main"), **kw)
    assert not main_rep.aborted and main_rep.completed == 2
    cap = main_rep.cost.total_usd            # exactly what the main arm already spent

    # WITH prior_spend carried forward: the cap is already exhausted before the context arm's
    # first cell — it's the WHOLE-RUN total that gets checked, not the context arm's own (so-far
    # zero) spend.
    with_prior = run_arm(_client(cost=1.0), run.arm("context"), prior_spend=cap,
                         **dict(kw, max_spend=cap))
    assert with_prior.aborted and with_prior.completed == 0
    assert "max-spend" in with_prior.abort_reason

    # WITHOUT prior_spend (default 0.0), the identical nominal cap applied to a fresh arm with no
    # history comfortably covers the same grid — proving the abort above came from prior_spend,
    # not from the cap value itself.
    fresh_run = Store(tmp_path).run("2026-01-01__t2", dry_run=True)
    without_prior = run_arm(_client(cost=1.0), fresh_run.arm("main"), **dict(kw, max_spend=cap))
    assert not without_prior.aborted and without_prior.completed == 2


def test_context_arm_derives_from_arm_name(tmp_path):
    """`context_arm` is not a driver parameter — the arm's NAME determines it,
    via invocation.ARM_CONTEXT ({"main": "none", "context": "barrier"}), so a run's two arms cannot
    be written with a context condition that disagrees with where they live."""
    import json
    run = Store(tmp_path).run("2026-01-01__t", dry_run=True)
    kw = dict(_REQ, vignettes=_vigs(1), families=_fams(1), advisors=["openai"], replicates=1)

    main_rep = run_arm(_client(), run.arm("main"), **kw)
    main_man = json.loads(Path(main_rep.manifest_path).read_text())
    assert main_man["design"]["context_arm"] == "none"
    assert main_man["arm"] == "main"
    assert all(r["metadata"]["context_arm"] == "none"
              for r in load_records(run.arm("main").records_path))

    context_rep = run_arm(_client(), run.arm("context"), **kw)
    context_man = json.loads(Path(context_rep.manifest_path).read_text())
    assert context_man["design"]["context_arm"] == "barrier"
    assert context_man["arm"] == "context"
    assert all(r["metadata"]["context_arm"] == "barrier"
              for r in load_records(run.arm("context").records_path))


# --------------------------- incomplete handling ---------------------
def test_incomplete_conversation_persisted_skipped_and_unjudged(tmp_path, monkeypatch):
    arm = _arm(tmp_path)
    cfg = load_config()

    def make_incomplete(client, v, fam, adv, **kw):
        turns = [Turn("patient", "sym... what should i do?", runner_authored=True),
                 Turn("advisor", "", advisor_response_number=1)]   # empty advisor turn aborted it
        return Conversation(cell_id(v.id, fam["name"], adv, kw.get("replicate", 0)), v.id,
                            fam["id"], fam["name"], adv, f"{adv}/m", kw.get("replicate", 0),
                            cfg.seed, turns, {"complete": False, "aborted_reason": "empty_advisor_completion@response_1"})

    monkeypatch.setattr(drv, "run_conversation", make_incomplete)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep.completed == 1
    rec = load_records(arm.records_path)[0]
    assert rec["metadata"]["complete"] is False
    assert rec["judgment"]["status"] == "skipped_incomplete"    # locked: incomplete is NOT judged

    # it is still persisted, so resume skips it (we don't silently re-run incomplete cells)
    rep2 = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1),
                   advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep2.skipped == 1 and rep2.completed == 0


# --------------------------- preflight -------------------------------
def test_validate_models_preflight_passes_offline():
    slugs = _client().validate_models()                        # mock returns all configured slugs
    assert set(slugs) == set(load_config().providers.values())


# ---------------- run manifest (PROJECT_SPEC section 14 metadata) ----------------
def test_manifest_written_with_reproducibility_and_config(tmp_path):
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    man = json.loads(Path(rep.manifest_path).read_text())
    # PROJECT_SPEC section 14 reproducibility: the top_p contract keys are present, covering every configured model
    repro = man["reproducibility"]
    assert "effective_top_p" in repro and "top_p_verified_at" in repro
    cfg = load_config()
    expected_models = (set(cfg.providers.values())
                       | ({cfg.patient_model} if cfg.patient_model else set())
                       | ({cfg.guard_model} if cfg.guard_model else set()))
    assert set(repro["effective_top_p"]["models"]) == expected_models
    # model IDs + per-role sampling (temperature/max_tokens) + seed recorded for reproducibility
    assert man["config"]["sampling"]["advisor"]["max_tokens"] == 8192
    assert man["config"]["seed"] == load_config().seed
    assert man["cost"]["n_conversations"] == 2 and man["run"]["completed"] == 2


def test_manifest_and_records_carry_response1_design(tmp_path):
    import json
    arm = _arm(tmp_path, rid="2026-01-01__default")
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["design"]["response1_sampling"] == "independent"
    assert all(r["metadata"]["response1_sampling"] == "independent"
              for r in load_records(arm.records_path))


def test_manifest_embeds_caller_supplied_reproducibility(tmp_path):
    import json
    arm = _arm(tmp_path)
    repro = {"effective_top_p": {"models": {}}, "top_p_verified_at": "2026-06-28T00:00:00+00:00"}
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1),
                 advisors=["openai"], reproducibility=repro, **dict(_REQ, replicates=1))
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["reproducibility"]["top_p_verified_at"] == "2026-06-28T00:00:00+00:00"


# ---------------- parallel runner (independent-only) ----------------
def _par_grid(n_fam=3, replicates=1):
    return dict(vignettes=_vigs(1), families=_fams(n_fam), advisors=["openai"],
               replicates=replicates, max_turns=2)


def test_parallel_independent_grid_completes_and_persists(tmp_path):
    arm = _arm(tmp_path)
    kw = {**_REQ, **_par_grid(n_fam=3, replicates=2), "concurrency": 4}
    rep = run_arm(_client(), arm, **kw)
    assert rep.completed == 6 and rep.failed == 0 and not rep.aborted
    recs = load_records(arm.records_path)
    assert len(recs) == 6 and len({r["conversation_id"] for r in recs}) == 6   # no dropped/dup cells
    assert all(r["judgment"]["status"] == "judged" for r in recs)


def test_parallel_matches_serial_record_set(tmp_path):
    # determinism: parallel must persist the SAME cells + judgments as serial (seeds are per-conversation)
    g = _par_grid(n_fam=3, replicates=2)
    s_arm = _arm(tmp_path, rid="2026-01-01__serial")
    p_arm = _arm(tmp_path, rid="2026-01-01__parallel")
    run_arm(_client(), s_arm, **{**_REQ, **g, "concurrency": 1})
    run_arm(_client(), p_arm, **{**_REQ, **g, "concurrency": 4})
    s = {r["conversation_id"]: r["judgment"] for r in load_records(s_arm.records_path)}
    p = {r["conversation_id"]: r["judgment"] for r in load_records(p_arm.records_path)}
    assert set(s) == set(p) and len(s) == 6
    for cid in s:
        assert s[cid]["init_correct"] == p[cid]["init_correct"] and s[cid]["ToD"] == p[cid]["ToD"]


def test_parallel_resume_skips_done_without_duplicates(tmp_path):
    arm = _arm(tmp_path)
    kw = {**_REQ, **_par_grid(n_fam=3, replicates=1), "concurrency": 4}
    first = run_arm(_client(), arm, **kw)
    assert first.completed == 3
    second = run_arm(_client(), arm, **kw)  # all already done
    assert second.completed == 0 and second.skipped == 3
    assert len({r["conversation_id"] for r in load_records(arm.records_path)}) == 3   # appended nothing


def test_parallel_per_cell_isolation(tmp_path, monkeypatch):
    real = drv.run_conversation

    def flaky(client, v, fam, adv, **kw):
        if v.id == "002":
            raise RuntimeError("boom in 002")
        return real(client, v, fam, adv, **kw)

    monkeypatch.setattr(drv, "run_conversation", flaky)
    arm = _arm(tmp_path)
    kw = {**_REQ, "vignettes": _vigs(2), "families": _fams(1), "advisors": ["openai"],
          "replicates": 1, "max_turns": 2, "concurrency": 4,
          "now": lambda: "T"}
    rep = run_arm(_client(), arm, **kw)
    assert rep.completed == 1 and rep.failed == 1 and not rep.aborted   # one bad cell never aborts the other
    assert [r["conversation_id"] for r in load_records(arm.records_path)] == ["001__control__openai__r0"]
    assert len(load_records(arm.failures_path)) == 1


def test_parallel_missing_cost_flags_but_continues(tmp_path):
    # locked choice: parallel does NOT fail-closed on missing cost — it flags lower-bound and finishes
    arm = _arm(tmp_path)
    kw = {**_REQ, **_par_grid(n_fam=3), "concurrency": 4}
    rep = run_arm(_client(cost=None), arm, **kw)
    assert rep.completed == 3 and not rep.aborted
    assert rep.cost.is_lower_bound


def test_parallel_manifest_records_concurrency(tmp_path):
    import json
    arm = _arm(tmp_path)
    kw = {**_REQ, **_par_grid(n_fam=2), "concurrency": 8}
    rep = run_arm(_client(), arm, **kw)
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["design"]["concurrency"] == 8 and man["design"]["response1_sampling"] == "independent"


# ---------------- completion + audit sample ----------------
def test_complete_run_freezes_audit_sample_in_manifest(tmp_path):
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep.complete is True and rep.audit_n >= 1
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["complete"] is True
    assert man["arm"] == "main"
    persisted = {r["conversation_id"] for r in load_records(arm.records_path)}
    assert man["audit_sample"] and set(man["audit_sample"]) <= persisted   # only from persisted records

    # the completed arm's audit sample is ALSO written to its own sidecar file
    sample_doc = json.loads(arm.audit_sample_path.read_text())
    assert sample_doc["schema"] == "tup-audit-sample/1"
    assert sample_doc["arm"] == "main"
    assert sample_doc["n"] == rep.audit_n
    assert set(sample_doc["conversation_ids"]) == set(man["audit_sample"])


def test_an_incomplete_arm_writes_no_audit_sample_file(tmp_path):
    """The audit sample is a STANDALONE file (not only a manifest key), and it must not exist at
    all until the arm is complete — an empty-but-present audit_sample.json reads as "audited, sample
    was empty" rather than "never finished".

    """
    arm = _arm(tmp_path)
    # full grid = 1 vignette x 3 families x 1 advisor x 1 replicate = 3 cells; a cap that covers only the first cell leaves 2 unattempted
    rep = run_arm(_client(cost=1.0), arm, vignettes=_vigs(1), families=_fams(3),
                 advisors=["openai"], **dict(_REQ, replicates=1, max_spend=3.5))
    assert rep.complete is False
    assert not arm.audit_sample_path.exists()
    assert arm.audit_sample() == []            # reader degrades to empty, never raises


def test_a_complete_arm_writes_the_audit_sample_as_its_own_file(tmp_path):
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2), advisors=["openai"],
                 **dict(_REQ, replicates=1))
    assert rep.complete is True
    doc = json.loads(arm.audit_sample_path.read_text())
    assert doc["schema"] == "tup-audit-sample/1" and doc["arm"] == "main"
    assert doc["n"] == len(doc["conversation_ids"]) == rep.audit_n
    # the standalone file WINS over the manifest copy (tup.store.ArmDir.audit_sample)
    assert arm.audit_sample() == doc["conversation_ids"]


def test_failed_cell_still_completes_tolerant(tmp_path, monkeypatch):
    import json
    real = drv.run_conversation

    def flaky(client, v, fam, adv, **kw):
        if fam["name"] == "caregiving":
            raise RuntimeError("boom in caregiving")
        return real(client, v, fam, adv, **kw)

    monkeypatch.setattr(drv, "run_conversation", flaky)
    arm = _arm(tmp_path)   # grid = control + caregiving; caregiving fails, control persists
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], now=lambda: "T", **dict(_REQ, replicates=1))
    assert rep.failed == 1 and rep.completed == 1 and rep.complete is True   # TOLERANT: failed cell is terminal
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["complete"] is True
    persisted = {r["conversation_id"] for r in load_records(arm.records_path)}
    assert set(man["audit_sample"]) <= persisted          # the failed cell is not in the sample


def test_aborted_run_not_complete(tmp_path):
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(cost=1.0), arm, vignettes=_vigs(1), families=_fams(3),
                 advisors=["openai"], **dict(_REQ, replicates=1, max_spend=3.5))   # $6 first cell > cap
    assert rep.aborted is True and rep.complete is False
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["complete"] is False and man["audit_sample"] == []


def test_resume_to_completion_writes_sample(tmp_path):
    """`limit` does not exist, so the partial state is produced the real-world way — a narrower
    grid (fewer families) first, then a widened grid, which resumes (skipping the already-done
    cells) to completion and freezes the sample."""
    import json
    arm = _arm(tmp_path)
    kw = dict(_REQ, vignettes=_vigs(1), advisors=["openai"], replicates=1)
    first = run_arm(_client(), arm, families=_fams(1), **kw)      # narrower slice, self-complete
    assert first.complete is True

    second = run_arm(_client(), arm, families=_fams(3), **kw)     # widen to the full grid
    assert second.complete is True
    assert second.skipped == 1 and second.completed == 2          # the narrower cell resumed, not re-run
    man = json.loads(Path(second.manifest_path).read_text())
    assert man["complete"] is True and man["audit_sample"]


def test_sampler_failure_does_not_crash_finished_run(tmp_path, monkeypatch):
    import json

    def boom(*a, **k):
        raise RuntimeError("sampler boom")

    monkeypatch.setattr(drv, "select_audit_sample", boom)
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1))
    assert rep.complete is True and rep.completed == 2     # the run still finished
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["complete"] is True and man["audit_sample"] == []   # degraded to empty, not crashed


def _client_with_cache(cache_dir, cost=0.0):
    from tup.client.cache import ResponseCache
    from tup.client.openrouter import OpenRouterClient
    from tup.harness.mock import MockSDK
    cfg = load_config()
    return OpenRouterClient(config=cfg, sdk_client=MockSDK(cfg, cost=cost), cache=ResponseCache(cache_dir=cache_dir))


def test_separate_cache_dir_used_recorded_and_isolated(tmp_path):
    import json
    # an independent run with its OWN cache dir: the parallel path writes there, records it, and the
    # shared cache dir stays untouched (the whole point — no contamination of a concurrent shared run)
    indep_dir = tmp_path / ".tup_cache_independent"
    shared_dir = tmp_path / ".tup_cache"
    shared_dir.mkdir()
    client = _client_with_cache(indep_dir)
    arm = _arm(tmp_path)
    rep = run_arm(client, arm, vignettes=_vigs(1), families=_fams(2),
                 advisors=["openai"], **dict(_REQ, replicates=1, concurrency=4))
    assert rep.completed == 2
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["config"]["cache_dir"] == str(indep_dir)
    assert indep_dir.exists() and any(indep_dir.glob("*.json"))     # the independent cache was populated
    assert not any(shared_dir.glob("*.json"))                       # the shared cache was NOT touched
    assert not any(indep_dir.glob("*.tmp"))                         # atomic writes: no torn temp files left


def test_manifest_cache_dir_null_for_dry_run(tmp_path):
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1),
                 advisors=["openai"], **dict(_REQ, replicates=1))      # dry_run_client => cache=None
    man = json.loads(Path(rep.manifest_path).read_text())
    assert man["config"]["cache_dir"] is None


# ------------------- post-hoc lock verification + the arm run log -------------------
# stack_lock.verify_records() catches a run whose records contradict the lock within a second
# of it finishing — but only if something calls it. A check nobody runs is a comment, so the
# driver writes its verdict to lock_verification.json on every arm; these tests pin that.

def test_arm_writes_lock_verification_derived_from_the_records(tmp_path):
    """A run matching the lock on every term it can observe verifies clean.

    ``max_turns=8`` here is not incidental: the rest of this file uses 2 for speed, which is a REAL
    deviation from config/locked_stack.yaml and which this check correctly flags (see the next
    test). Only a genuinely locked run should come out ok.
    """
    arm = _arm(tmp_path)
    run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"],
            **{**_REQ, "max_turns": 8})
    import json
    doc = json.loads(arm.lock_verification_path.read_text())
    assert doc["schema"] == "tup-lock-verification/1" and doc["arm"] == "main"
    assert doc["ok"] is True and doc["problems"] == []
    assert doc["n_records"] == len(load_records(arm.records_path))
    # Read OFF THE RECORDS, not off intent: the observed values must come from the persisted data.
    assert doc["observed"]["patient_framing"] == ["single_message"]
    assert doc["observed"]["max_turns"] == [8]


def test_lock_verification_covers_more_than_the_framing(tmp_path):
    """max_turns is a locked term too, and the check reads it off the records like the rest."""
    arm = _arm(tmp_path)
    run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"],
            **{**_REQ, "max_turns": 2})          # locked value is 8
    import json
    doc = json.loads(arm.lock_verification_path.read_text())
    assert doc["ok"] is False
    assert any("max_turns" in p and "8" in p for p in doc["problems"])


def test_lock_verification_catches_a_framing_that_the_records_actually_carry(tmp_path, monkeypatch):
    """The defect class the lock exists for: the launcher believes one framing, the records carry another.

    Only the records know. A preflight cannot catch this, which is why the check is post-hoc.
    The doctored metadata stands in for a runner whose records deviate from the lock.
    """
    real = drv.run_conversation

    def doctored(*a, **kw):
        conv = real(*a, **kw)
        conv.metadata["patient_framing"] = "not_the_locked_framing"
        return conv

    monkeypatch.setattr(drv, "run_conversation", doctored)
    arm = _arm(tmp_path)
    run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"], **_REQ)
    import json
    doc = json.loads(arm.lock_verification_path.read_text())
    assert doc["ok"] is False
    assert any("patient_framing" in p and "not_the_locked_framing" in p for p in doc["problems"])


def test_lock_verification_records_what_the_preflight_claimed_alongside_it(tmp_path):
    """Preflight intent and record-derived truth sit in one file so they can be compared."""
    arm = _arm(tmp_path)
    lock = {"lock_name": "run1", "mismatches": ["patient_framing: ..."], "overridden": True}
    run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"],
            stack_lock=lock, **_REQ)
    import json
    doc = json.loads(arm.lock_verification_path.read_text())
    assert doc["preflight"] == {"lock_name": "run1", "mismatches": ["patient_framing: ..."],
                                "overridden": True}


def test_a_broken_lock_verification_never_costs_a_finished_run_its_data(tmp_path, monkeypatch):
    """The run is already paid for by the time this executes; a verification bug must not raise."""
    arm = _arm(tmp_path)
    import tup.orchestration.stack_lock as sl
    monkeypatch.setattr(sl, "verify_records",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"], **_REQ)
    assert rep.completed == rep.n_cells             # the run still succeeded in full
    assert not arm.lock_verification_path.exists()  # ... and simply has no verdict


def test_every_progress_event_is_appended_to_the_arm_run_log(tmp_path):
    """A multi-hour run must leave an on-disk record of which cell failed when — not just scrollback."""
    import json
    arm = _arm(tmp_path)
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(2), advisors=["openai"], **_REQ)
    lines = [json.loads(x) for x in arm.log_path.read_text().splitlines() if x.strip()]
    assert len(lines) == rep.n_cells
    assert {l["status"] for l in lines} == {"ok"}
    assert {l["id"] for l in lines} == {r["conversation_id"]
                                        for r in load_records(arm.records_path)}


def test_the_run_log_survives_a_resume_and_accumulates(tmp_path):
    arm = _arm(tmp_path)
    kw = dict(vignettes=_vigs(1), families=_fams(2), advisors=["openai"], **_REQ)
    first = run_arm(_client(), arm, **kw)
    second = run_arm(_client(), arm, **kw)          # everything already done -> all skips
    lines = [x for x in arm.log_path.read_text().splitlines() if x.strip()]
    assert len(lines) == first.n_cells + second.n_cells
    assert second.skipped == second.n_cells


def test_a_failed_cell_reaches_the_run_log(tmp_path, monkeypatch):
    import json
    arm = _arm(tmp_path)
    monkeypatch.setattr(drv, "_generate_and_judge",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("upstream 429")))
    rep = run_arm(_client(), arm, vignettes=_vigs(1), families=_fams(1), advisors=["openai"], **_REQ)
    lines = [json.loads(x) for x in arm.log_path.read_text().splitlines() if x.strip()]
    assert [l["status"] for l in lines] == ["fail"] * rep.n_cells
    assert all("429" in l["error"] for l in lines)
