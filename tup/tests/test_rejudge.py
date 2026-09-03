"""Re-judge script (extraction robustness): fresh judgments re-attach to persisted records; identity preserved."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from tup.client.openrouter import OpenRouterClient
from tup.output.persist import load_records, save_records, to_record
from tup.store import Store

from .conftest import FakeSDK, _Resp, _Usage
from .test_judge import _conv, _judge_json

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import rejudge  # noqa: E402


def _record_with_status(status, **conv_kwargs):
    rec = to_record(_conv(n=2, **conv_kwargs))
    rec["judgment"] = {"status": status, "init_correct": None, "ToD": None}
    return rec


def test_rejudge_replaces_only_target_judgments(sample_config):
    target = _record_with_status("unparseable")
    keep = to_record(_conv(n=2))
    keep["conversation_id"] = "001__cost_medical_debt__openai__r1"
    keep["judgment"] = {"status": "judged", "init_correct": 1, "ToD": 3, "rationale": "keep"}
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [target, keep])
    assert (n, n_failed) == (1, 0) and sdk.create_calls == 3   # three uncached panel-seat calls
    assert out[0]["judgment"]["status"] == "judged" and out[0]["judgment"]["ToD"] == 3
    assert out[0]["turns"] == target["turns"]            # conversation identity untouched
    assert out[0]["seed"] == target["seed"]
    assert out[1]["judgment"]["rationale"] == "keep"     # non-target record passes through unchanged


def test_rejudge_panel_mode_reseats_full_panel(sample_config):
    panel_config = dataclasses.replace(
        sample_config, advisors=list(sample_config.providers), judge_panel=3
    )
    target = _record_with_status("panel_incomplete")
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=panel_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [target])
    assert (n, n_failed) == (1, 0) and sdk.create_calls == 3   # three real, uncached seat calls
    j = out[0]["judgment"]
    assert j["status"] == "judged" and len(j["panel"]) == 3
    models = [s["judge_model"] for s in j["panel"]]
    assert len(set(models)) == 3                         # distinct seats (provider-passthrough holds here too)


def test_rejudge_never_touches_incomplete_conversations(sample_config):
    rec = _record_with_status("skipped_incomplete", complete=False)
    sdk = FakeSDK()
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [rec], rejudge_all=True)
    assert (n, n_failed) == (0, 0) and sdk.create_calls == 0
    assert out[0]["judgment"]["status"] == "skipped_incomplete"


# ---- judge_failed is IN the default filter -----------------------------------------
def test_judge_failed_is_rejudged_by_default(sample_config):
    """The driver stamps ``judge_failed`` and documents this script as the recovery path
    (test_harness.py::test_judge_failure_is_persisted_not_discarded), but the default status filter
    omitted it — so the documented path matched nothing on exactly the records it exists to fix."""
    assert "judge_failed" in rejudge.DEFAULT_STATUSES
    target = _record_with_status("judge_failed")
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [target])   # NO --statuses override
    assert (n, n_failed) == (1, 0)
    assert out[0]["judgment"]["status"] == "judged"


# ---- per-record failure isolation (one transient 429 must not kill a batch) ----------
def _boom(*a, **kw):
    raise RuntimeError("RateLimitError: 429 - google/gemini-3.6-flash rate-limited upstream")


def test_one_raising_judge_does_not_discard_the_batch(sample_config, monkeypatch):
    """One judge call raising must not discard the records already re-judged (uncached, i.e. paid
    for) in the same batch: the loop continues and persists them."""
    first, third = _record_with_status("judge_failed"), _record_with_status("judge_failed")
    first["conversation_id"] = "001__work__openai__r0"
    boom_rec = _record_with_status("judge_failed")
    boom_rec["conversation_id"] = "002__work__openai__r0"
    third["conversation_id"] = "003__work__openai__r0"

    calls = {"n": 0}
    real = rejudge.judge_conversation_panel

    def flaky(client, conv, vignette, **kw):
        calls["n"] += 1
        if conv.conversation_id.startswith("002__"):
            _boom()
        return real(client, conv, vignette, **kw)

    monkeypatch.setattr(rejudge, "judge_conversation_panel", flaky)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)

    errors = []
    out, n, n_failed = rejudge.rejudge_records(
        client, [first, boom_rec, third], on_error=lambda cid, e: errors.append(cid))

    assert (n, n_failed) == (2, 1)
    assert calls["n"] == 3                                    # the loop ran past the failure
    assert errors == ["002__work__openai__r0"]
    assert out[0]["judgment"]["status"] == "judged"           # survived
    assert out[2]["judgment"]["status"] == "judged"           # survived, AFTER the failure
    assert out[1] is boom_rec                                 # failed record kept verbatim
    assert out[1]["judgment"]["status"] == "judge_failed"     # ... so a re-run retries exactly it
    assert [r["conversation_id"] for r in out] == [
        "001__work__openai__r0", "002__work__openai__r0", "003__work__openai__r0"]  # order preserved


def test_failed_record_is_still_selected_on_a_later_run(sample_config, monkeypatch):
    """Idempotence: the retry pass must pick up precisely the records that failed, and no others."""
    ok, bad = _record_with_status("judge_failed"), _record_with_status("judge_failed")
    ok["conversation_id"] = "001__work__openai__r0"
    bad["conversation_id"] = "002__work__openai__r0"
    real = rejudge.judge_conversation_panel

    def flaky(client, conv, vignette, **kw):
        if conv.conversation_id.startswith("002__"):
            _boom()
        return real(client, conv, vignette, **kw)

    monkeypatch.setattr(rejudge, "judge_conversation_panel", flaky)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, _, _ = rejudge.rejudge_records(client, [ok, bad])

    still = [r for r in out if rejudge.needs_rejudge(r, rejudge.DEFAULT_STATUSES, False)]
    assert [r["conversation_id"] for r in still] == ["002__work__openai__r0"]

    monkeypatch.setattr(rejudge, "judge_conversation_panel", real)   # pool recovers
    out2, n2, f2 = rejudge.rejudge_records(client, out)
    assert (n2, f2) == (1, 0)
    assert all(r["judgment"]["status"] == "judged" for r in out2)


def test_panel_mode_failure_is_isolated_too(sample_config, monkeypatch):
    panel_config = dataclasses.replace(
        sample_config, advisors=list(sample_config.providers), judge_panel=3
    )
    bad, good = _record_with_status("judge_failed"), _record_with_status("judge_failed")
    bad["conversation_id"] = "002__work__openai__r0"
    good["conversation_id"] = "003__work__openai__r0"
    real = rejudge.judge_conversation_panel

    def flaky(client, conv, vignette, **kw):
        if conv.conversation_id.startswith("002__"):
            _boom()
        return real(client, conv, vignette, **kw)

    monkeypatch.setattr(rejudge, "judge_conversation_panel", flaky)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=panel_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [bad, good])
    assert (n, n_failed) == (1, 1)
    assert out[0]["judgment"]["status"] == "judge_failed"
    assert len(out[1]["judgment"]["panel"]) == 3


def test_config_error_still_aborts_and_is_not_swallowed(sample_config):
    """A missing vignette is not transient — every record would hit it. It must NOT be caught."""
    rec = _record_with_status("judge_failed")
    rec["vignette_id"] = "999"
    sdk = FakeSDK()
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    with pytest.raises(SystemExit):
        rejudge.rejudge_records(client, [rec])
    assert sdk.create_calls == 0


# ---- main(): partial progress reaches disk; exit status reports failure -------------------------
RID = "2026-08-06__t"


def _live_sdk(sample_config, **kw):
    """A fake SDK whose live model list carries the configured slate, so main()'s startup slug
    validation passes (a retired judge-seat slug must refuse the batch before any spend)."""
    return FakeSDK(model_ids=list(sample_config.providers.values()), **kw)


def _write(tmp_path, records, monkeypatch=None, arm="main"):
    """Seed one arm of one run in a store rooted at tmp_path; return its records path.

    rejudge.py addresses data by RUN ID + ARM — never by an arbitrary path: the store
    owns every path, so a re-judge cannot be pointed at a file outside it.
    """
    p = Store(tmp_path).run(RID).arm(arm).mkdir().records_path
    save_records(records, p)
    return p


def test_main_writes_partial_progress_and_exits_nonzero(sample_config, tmp_path, monkeypatch):
    ok, bad = _record_with_status("judge_failed"), _record_with_status("judge_failed")
    ok["conversation_id"] = "001__work__openai__r0"
    bad["conversation_id"] = "002__work__openai__r0"
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, [ok, bad])
    real = rejudge.judge_conversation_panel

    def flaky(client, conv, vignette, **kw):
        if conv.conversation_id.startswith("002__"):
            _boom()
        return real(client, conv, vignette, **kw)

    monkeypatch.setattr(rejudge, "judge_conversation_panel", flaky)
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))

    rc = rejudge.main([RID, "--arm", "main", "--max-spend", "5"])
    assert rc == 1                                        # a failure is reported, not hidden
    written = {r["conversation_id"]: r for r in load_records(path)}
    assert written["001__work__openai__r0"]["judgment"]["status"] == "judged"   # progress persisted
    assert written["002__work__openai__r0"]["judgment"]["status"] == "judge_failed"
    assert path.with_suffix(".jsonl.bak").exists()


def test_main_leaves_file_untouched_when_every_record_fails(sample_config, tmp_path, monkeypatch):
    """Nothing succeeded: rewriting would only clobber an earlier .bak with identical content."""
    rec = _record_with_status("judge_failed")
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, [rec])
    before = path.read_bytes()
    monkeypatch.setattr(rejudge, "judge_conversation_panel", _boom)
    sdk = _live_sdk(sample_config)
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))

    rc = rejudge.main([RID, "--arm", "main", "--max-spend", "5"])
    assert rc == 1
    assert path.read_bytes() == before
    assert not path.with_suffix(".jsonl.bak").exists()


def test_main_reports_nothing_to_do_without_touching_the_file(sample_config, tmp_path, monkeypatch):
    rec = to_record(_conv(n=2))
    rec["judgment"] = {"status": "judged", "init_correct": 1, "ToD": 3}
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, [rec])
    before = path.read_bytes()
    sdk = _live_sdk(sample_config)
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5"]) == 0
    assert path.read_bytes() == before and sdk.create_calls == 0


# ---- concurrency: order, identity and isolation survive the thread pool ---------------------
def _targets(k, prefix="judge_failed"):
    recs = []
    for i in range(k):
        r = _record_with_status(prefix)
        r["conversation_id"] = f"{i + 1:03d}__work__openai__r0"
        recs.append(r)
    return recs


def test_concurrent_rejudge_preserves_order_and_identity(sample_config):
    recs = _targets(6)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, recs, concurrency=4)
    assert (n, n_failed) == (6, 0)
    assert [r["conversation_id"] for r in out] == [r["conversation_id"] for r in recs]   # order
    assert all(r["judgment"]["status"] == "judged" for r in out)
    assert all(o["turns"] == r["turns"] and o["seed"] == r["seed"] for o, r in zip(out, recs))


def test_concurrent_failure_is_isolated_per_record(sample_config, monkeypatch):
    recs = _targets(5)
    real = rejudge.judge_conversation_panel

    def flaky(client, conv, vignette, **kw):
        if conv.conversation_id.startswith("003__"):
            _boom()
        return real(client, conv, vignette, **kw)

    monkeypatch.setattr(rejudge, "judge_conversation_panel", flaky)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    errors = []
    out, n, n_failed = rejudge.rejudge_records(
        client, recs, concurrency=3, on_error=lambda cid, e: errors.append(cid))
    assert (n, n_failed) == (4, 1) and errors == ["003__work__openai__r0"]
    assert out[2] is recs[2] and out[2]["judgment"]["status"] == "judge_failed"
    assert [r["judgment"]["status"] for r in out] == ["judged", "judged", "judge_failed", "judged", "judged"]


# ---- the spend cap: read off the client, checked before every dispatch ----------------------
def test_cap_stops_dispatch_and_leaves_the_rest_verbatim(sample_config):
    """Three seats at $0.50 each = $1.50 per record; a $1 cap admits exactly one record serially."""
    recs = _targets(3)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.5))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    report = {}
    out, n, n_failed = rejudge.rejudge_records(client, recs, max_spend=1.0, report=report)
    assert (n, n_failed) == (1, 0)
    assert out[0]["judgment"]["status"] == "judged"
    assert out[1] is recs[1] and out[2] is recs[2]                       # untouched, verbatim
    assert report["capped"] is True and report["deferred"] == 2
    assert report["spent_usd"] == pytest.approx(1.5)
    assert sdk.create_calls == 3                                          # not one call past the cap


def test_cap_overshoot_is_bounded_by_concurrency(sample_config):
    """In the parallel path the pool is filled before any cost returns, so at most `concurrency`
    records overshoot; everything after them is deferred."""
    recs = _targets(5)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.5))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    report = {}
    out, n, n_failed = rejudge.rejudge_records(client, recs, concurrency=2, max_spend=1.0, report=report)
    assert n <= 2 and n >= 1 and n_failed == 0
    assert report["capped"] is True and report["deferred"] == 5 - n
    assert sum(1 for r in out if r["judgment"]["status"] == "judged") == n


def test_cap_counts_spend_the_records_would_not_show(sample_config):
    """A seat's corrective retry is paid for even though the record keeps only the last attempt's
    usage: the cap must see it. First seat response is unparseable (retry), so 4 calls for 3 seats."""
    recs = _targets(1)
    bad = _Resp(content="not json at all", usage=_Usage(1, 1, 0.25))
    good = _Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.25))
    sdk = FakeSDK(responses=[bad, good, good, good])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    report = {}
    rejudge.rejudge_records(client, recs, max_spend=10.0, report=report)
    assert sdk.create_calls == 4
    assert report["spent_usd"] == pytest.approx(1.0)                      # 4 x 0.25, retry included


# ---- main(): preflight refusals and the audit trail -----------------------------------------
def test_main_refuses_a_lock_mismatch_before_any_call(sample_config, tmp_path, monkeypatch):
    from tup.orchestration.stack_lock import StackLockError
    rec = _record_with_status("judge_failed")
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, [rec])
    before = path.read_bytes()

    def refuse(*a, **k):
        raise StackLockError("judge_prompt_version: locked=9 but this run resolves to 8")
    monkeypatch.setattr(rejudge, "assert_locked_stack", refuse)
    sdk = _live_sdk(sample_config)
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5"]) == 2
    assert sdk.create_calls == 0 and path.read_bytes() == before
    assert not Store(tmp_path).run(RID).launch_cmd_path.exists()          # refused before the audit line


def test_main_refuses_a_retired_slug_before_any_call(sample_config, tmp_path, monkeypatch):
    rec = _record_with_status("judge_failed")
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, [rec])
    sdk = FakeSDK(model_ids=[])                                           # nothing on the live list
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5"]) == 2
    assert sdk.create_calls == 0 and not path.with_suffix(".jsonl.bak").exists()


def test_main_requires_the_cap(sample_config, tmp_path, monkeypatch):
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    _write(tmp_path, [_record_with_status("judge_failed")])
    with pytest.raises(SystemExit):
        rejudge.main([RID, "--arm", "main"])


def test_main_appends_its_invocation_to_launch_cmd(sample_config, tmp_path, monkeypatch):
    rec = _record_with_status("judge_failed")
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    _write(tmp_path, [rec])
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.01))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5", "--concurrency", "2"]) == 0
    text = Store(tmp_path).run(RID).launch_cmd_path.read_text(encoding="utf-8")
    assert "scripts/rejudge.py" in text and "--max-spend 5" in text and "--concurrency 2" in text


def test_main_exit_status_reports_a_cap_stop(sample_config, tmp_path, monkeypatch):
    recs = _targets(3)
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, recs)
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.5))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    rc = rejudge.main([RID, "--arm", "main", "--max-spend", "1", "--concurrency", "1"])
    assert rc == 1                                                        # partial: re-run to continue
    written = load_records(path)
    assert [r["judgment"]["status"] for r in written] == ["judged", "judge_failed", "judge_failed"]


# ---- checkpoints and idempotent resume ------------------------------------------------------
def test_checkpoint_fires_every_n_completed_records_with_the_current_state(sample_config):
    recs = _targets(5)
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    seen = []
    rejudge.rejudge_records(client, recs, checkpoint=lambda cur: seen.append(
        sum(1 for r in cur if r["judgment"]["status"] == "judged")), checkpoint_every=2)
    assert seen == [2, 4]                                     # after 2 and 4 completions; caller writes the end


def test_a_killed_run_keeps_its_last_checkpoint_and_the_pristine_bak(sample_config, tmp_path, monkeypatch):
    """A KeyboardInterrupt mid-batch (the process being killed) must leave the checkpointed
    progress on disk and the original .bak untouched — the paid work survives."""
    recs = _targets(4)
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, recs)
    original = path.read_bytes()
    monkeypatch.setattr(rejudge, "CHECKPOINT_EVERY", 2)
    real = rejudge.judge_conversation_panel

    def killed_on_third(client, conv, vignette, **kw):
        if conv.conversation_id.startswith("003__"):
            raise KeyboardInterrupt
        return real(client, conv, vignette, **kw)
    monkeypatch.setattr(rejudge, "judge_conversation_panel", killed_on_third)
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    with pytest.raises(KeyboardInterrupt):
        rejudge.main([RID, "--arm", "main", "--max-spend", "5", "--concurrency", "1"])
    written = load_records(path)
    assert [r["judgment"]["status"] for r in written] == ["judged", "judged", "judge_failed", "judge_failed"]
    assert path.with_suffix(".jsonl.bak").read_bytes() == original


def test_all_skips_records_already_judged_under_the_current_rubric(sample_config):
    from tup.data.prompts import load_judge_prompt
    sha = load_judge_prompt().sha256
    done = to_record(_conv(n=2))
    done["conversation_id"] = "001__work__openai__r0"
    done["judgment"] = {"status": "judged", "init_correct": 1, "ToD": 3, "judge_prompt": {"sha256": sha, "version": 9}}
    stale = to_record(_conv(n=2))
    stale["conversation_id"] = "002__work__openai__r0"
    stale["judgment"] = {"status": "judged", "init_correct": 1, "ToD": 3, "judge_prompt": {"sha256": "old", "version": 8}}
    broken = to_record(_conv(n=2))
    broken["conversation_id"] = "003__work__openai__r0"
    broken["judgment"] = {"status": "unparseable", "judge_prompt": {"sha256": sha, "version": 9}}
    sdk = FakeSDK(responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    client = OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None)
    out, n, n_failed = rejudge.rejudge_records(client, [done, stale, broken], rejudge_all=True)
    assert (n, n_failed) == (2, 0)
    assert out[0] is done                                     # current rubric, parsed: left alone
    assert out[1]["judgment"]["judge_prompt"]["sha256"] == sha   # stale rubric: re-judged
    assert out[2]["judgment"]["status"] == "judged"           # current rubric but unparsed: re-judged


def test_bak_is_never_overwritten_by_a_second_pass(sample_config, tmp_path, monkeypatch):
    recs = _targets(2)
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    path = _write(tmp_path, recs)
    original = path.read_bytes()
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.0))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5"]) == 0
    # second pass: force by clearing statuses so the (now judged) records are targeted again
    assert rejudge.main([RID, "--arm", "main", "--max-spend", "5", "--statuses", "judged"]) == 0
    assert path.with_suffix(".jsonl.bak").read_bytes() == original


# ---- studies: free-form arms, no launch trail ---------------------------------------------
def test_main_rejudges_a_study_arm_without_a_launch_trail(sample_config, tmp_path, monkeypatch):
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    study = Store(tmp_path).study("2026-08-05__t_study")
    p = study.arm("roleswap").mkdir().records_path
    rec = _record_with_status("judge_failed")
    save_records([rec], p)
    sdk = _live_sdk(sample_config, responses=[_Resp(content=_judge_json(1, 3, ""), usage=_Usage(1, 1, 0.01))])
    monkeypatch.setattr(rejudge, "OpenRouterClient",
                        lambda **kw: OpenRouterClient(config=sample_config, sdk_client=sdk, cache=None))
    assert rejudge.main(["2026-08-05__t_study", "--study", "--arm", "roleswap", "--max-spend", "5"]) == 0
    assert load_records(p)[0]["judgment"]["status"] == "judged"
    assert not (study.path / "LAUNCH_CMD.txt").exists()


def test_main_rejects_a_free_form_arm_for_a_run(sample_config, tmp_path, monkeypatch):
    monkeypatch.setenv("TUP_RESULTS_ROOT", str(tmp_path))
    _write(tmp_path, [_record_with_status("judge_failed")])
    assert rejudge.main([RID, "--arm", "roleswap", "--max-spend", "5"]) == 2
