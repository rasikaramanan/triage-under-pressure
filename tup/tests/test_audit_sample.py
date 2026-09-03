"""Stratified audit sampler (for the post-run judge-decision audit): cap, skipped-all, determinism, buckets, robustness."""
from __future__ import annotations

from tup.output.audit_sample import _bucket, _facts, select_audit_sample


def _r(cid, *, vig=None, cond_id=0, cond="control", adv="openai", rep=0, T=10, init=1, tod=11,
       status="judged", complete=True):
    """One persisted-record dict (same shape as an arm's records.jsonl). T = number of advisor responses."""
    if vig is None:
        vig = cid.split("__")[0]
    j = {"status": status, "init_correct": init, "ToD": tod} if status is not None else None
    turns = [{"speaker": "patient", "text": "p"}]
    for i in range(1, T + 1):
        turns += [{"speaker": "advisor", "text": "a", "advisor_response_number": i},
                  {"speaker": "patient", "text": "p"}]
    return {"conversation_id": cid, "vignette_id": vig, "condition_id": cond_id,
            "condition_name": cond, "advisor_provider": adv, "replicate": rep,
            "turns": turns, "metadata": {"complete": complete}, "judgment": j}


def _skipped(cid, **kw):
    return _r(cid, status="skipped_incomplete", complete=False, init=None, tod=None, **kw)


def _sel(records, *, seed=0, max_n=20):
    return select_audit_sample(records, seed=seed, max_n=max_n)


# --------------------------- cap + skipped ---------------------------
def test_cap_honored_and_no_duplicates():
    recs = ([_r(f"v{i}__control__openai__r0", vig=f"v{i}", init=0, tod="NA") for i in range(8)]      # init0 groups
            + [_r(f"x__b{i}__openai__r0", cond_id=i, tod=2) for i in range(8)]                        # degraded_early
            + [_r(f"y__b{i}__openai__r0", cond_id=i, tod=6) for i in range(8)]                        # degraded_late
            + [_r(f"z__b{i}__openai__r0", cond_id=i, tod=11) for i in range(8)])                      # held_firm
    skipped = [_skipped(f"s{i}__control__openai__r0", vig=f"s{i}") for i in range(5)]
    out = _sel(recs + skipped)
    skip_cids = {r["conversation_id"] for r in skipped}
    bucketed = [c for c in out if c not in skip_cids]
    assert len(bucketed) <= 20                      # the cap bites
    assert len(out) == len(set(out))                # no duplicates
    assert skip_cids <= set(out)                    # all skipped included


def test_all_skipped_included_on_top_of_cap():
    recs = [_r(f"z__b{i}__openai__r0", cond_id=i, tod=11) for i in range(30)]   # 30 held_firm (quota 5)
    skipped = [_skipped(f"s{i}__c__openai__r0", vig=f"s{i}") for i in range(25)]
    out = _sel(recs + skipped)
    assert {r["conversation_id"] for r in skipped} <= set(out)                  # every skip present
    assert len(out) >= 25                                                       # cap is on bucketed only


# --------------------------- determinism ---------------------------
def test_deterministic_for_fixed_seed():
    recs = [_r(f"v{i}__b{i%6}__openai__r{i%3}", vig=f"v{i%6}", cond_id=i % 6, rep=i % 3,
               tod=(2 + i % 9)) for i in range(40)]
    assert _sel(recs, seed=7) == _sel(recs, seed=7)            # stable
    assert isinstance(_sel(recs, seed=7), list)


# --------------------------- quotas ---------------------------
def test_init0_quota():
    # 6 distinct init0 groups; the init0 quota is 5
    recs = [_r(f"v{i}__control__openai__r0", vig=f"v{i}", init=0, tod="NA") for i in range(6)]
    assert len(_sel(recs)) == 5


def test_mixed_init_group_flows_through_normal_buckets():
    # a group whose init differs across barriers (each conversation has its own response-1)
    # is not special — its records flow through init0/held like any others.
    recs = [_r("v1__control__openai__r0", vig="v1", cond_id=0, cond="control", init=0, tod="NA"),
            _r("v1__work__openai__r0", vig="v1", cond_id=3, cond="work", init=1, tod=11)]
    out = _sel(recs)
    assert set(out) <= {"v1__control__openai__r0", "v1__work__openai__r0"}   # no crash, valid cids


# --------------------------- bucket boundaries ---------------------------
def test_bucket_boundaries():
    assert _bucket(_facts(_r("a__b__o__r0", T=10, init=1, tod=2))) == "degraded_early"
    assert _bucket(_facts(_r("a__b__o__r0", T=10, init=1, tod=3))) == "degraded_early"
    assert _bucket(_facts(_r("a__b__o__r0", T=10, init=1, tod=4))) == "degraded_late"
    assert _bucket(_facts(_r("a__b__o__r0", T=10, init=1, tod=10))) == "degraded_late"
    assert _bucket(_facts(_r("a__b__o__r0", T=10, init=1, tod=11))) == "held_firm"      # T+1 = survived
    assert _bucket(_facts(_r("a__b__o__r0", init=0, tod="NA"))) is None                  # init0 not here


def test_init0_deduped_to_one_per_group():
    # one (vig,adv,rep) group, 3 barriers all init0 -> at most ONE of its cids in the sample
    grp = [_r(f"v1__b{i}__openai__r0", vig="v1", cond_id=i, init=0, tod="NA") for i in range(3)]
    out = _sel(grp)
    assert len({c for c in out} & {r["conversation_id"] for r in grp}) <= 1


# --------------------------- robustness ---------------------------
def test_empty_and_tiny_and_malformed_do_not_raise():
    assert _sel([]) == []
    one = _r("v1__control__openai__r0", vig="v1", init=1, tod=11)
    assert _sel([one]) == ["v1__control__openai__r0"]
    # malformed: no judgment, bad ToD type, missing fields — must be silently non-analyzable
    bad = [{"conversation_id": "x", "judgment": None},
           {"conversation_id": "y", "judgment": {"status": "judged", "init_correct": 1, "ToD": "weird"},
            "turns": []},
           {"not": "a record"}]
    assert _sel(bad) == []                                     # nothing analyzable, no crash
