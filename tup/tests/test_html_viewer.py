"""HTML run-explorer builder.

Covers the Python side that the embedded JS trusts: per-conversation CLASSIFICATION must match
tup.output.metrics, the payload must skip failures manifests, and the data must embed into the
template as parseable, injection-safe JSON. The interactive JS is not exercised here.
"""
from __future__ import annotations

import json
import re

import pytest

from tup.output import html_viewer as hv
from tup.output.persist import append_record, save_records
from tup.store import Store


# ---------------------------------------------------------------- record fixtures
def _turn(speaker, text, n=None, **kw):
    return {"speaker": speaker, "text": text, "advisor_response_number": n, **kw}


def _rec(cid="001__control__openai__r0", *, vignette="001", condition_id=0, condition_name="control",
         provider="openai", model="openai/m", replicate=0, n_advisor=3, init=1, tod=4,
         status="judged", complete=True, quote="", turns=None):
    j = None
    if status is not None:
        j = {"status": status, "init_correct": init, "ToD": tod, "degraded_turn_quote": quote,
             "rationale": "r", "judge_model": "x-ai/grok", "judge_provider": "xai",
             "judge_usage": {"cost": 0.001}}
    ts = turns if turns is not None else (
        [_turn("patient", "sym", runner_authored=True)]
        + sum(([_turn("advisor", f"a{i}", n=i), _turn("patient", f"p{i}")] for i in range(1, n_advisor + 1)), [])
    )
    return {"conversation_id": cid, "vignette_id": vignette, "condition_id": condition_id,
            "condition_name": condition_name, "advisor_provider": provider, "advisor_model": model,
            "replicate": replicate, "seed": 7, "turns": ts, "metadata": {"complete": complete},
            "judgment": j}


# ---------------------------------------------------------------- classification
def test_conversation_view_degraded_when_tod_le_T():
    v = hv.conversation_view(_rec(n_advisor=5, init=1, tod=4))
    assert v["analyzable"] and v["init"] == 1 and v["tod"] == 4 and v["n_advisor"] == 5
    assert v["degraded"] is True


def test_conversation_view_survived_when_tod_is_T_plus_1():
    # T = 5 advisor responses, no degradation => ToD = 6 = T+1
    v = hv.conversation_view(_rec(n_advisor=5, init=1, tod=6))
    assert v["init"] == 1 and v["tod"] == 6 and v["degraded"] is False   # survived, not degraded


def test_conversation_view_init0_has_na_tod_and_not_degraded():
    v = hv.conversation_view(_rec(init=0, tod="NA"))
    assert v["init"] == 0 and v["tod"] is None and v["tod_raw"] == "NA" and v["degraded"] is False


def test_incomplete_is_not_analyzable_and_not_degraded():
    v = hv.conversation_view(_rec(complete=False, status="skipped_incomplete", init=None, tod=None))
    assert v["analyzable"] is False and v["degraded"] is False
    assert v["excluded_reason"] == "incomplete"


def test_unparseable_and_unjudged_excluded_reasons():
    assert hv.conversation_view(_rec(status="unparseable", init=None, tod=None))["excluded_reason"] == "unparseable"
    assert hv.conversation_view(_rec(status=None))["excluded_reason"] == "unjudged"


def test_malformed_judgment_excluded_not_half_counted():
    # init==1 with ToD 'NA' is internally inconsistent -> excluded, degraded False (never half-counted)
    v = hv.conversation_view(_rec(init=1, tod="NA"))
    assert v["analyzable"] is False and v["degraded"] is False and v["excluded_reason"] == "malformed"


def test_classification_matches_metrics_module():
    from tup.output import metrics as M
    recs = [_rec("a", init=1, tod=4, n_advisor=5), _rec("b", init=1, tod=6, n_advisor=5),
            _rec("c", init=0, tod="NA"), _rec("d", complete=False, status="skipped_incomplete", init=None, tod=None)]
    views = [hv.conversation_view(r) for r in recs]
    assert sum(v["analyzable"] for v in views) == sum(M.is_analyzable(r) for r in recs)
    assert [v["analyzable"] for v in views] == [M.is_analyzable(r) for r in recs]


def test_turns_carry_number_and_opener_flag():
    v = hv.conversation_view(_rec(n_advisor=2))
    assert v["turns"][0]["opener"] is True and v["turns"][0]["speaker"] == "patient"
    advs = [t for t in v["turns"] if t["speaker"] == "advisor"]
    assert [t["n"] for t in advs] == [1, 2]


# ---------------------------------------------------------------- vignette slug (not number)
def test_vignette_shown_as_slug_and_number_rewritten_in_id():
    slugs = {"001": "asthma"}
    v = hv.conversation_view(_rec("001__work__openai__r0", vignette="001"), slugs)
    assert v["vignette"] == "asthma"                       # field is the slug, not "001"
    assert v["id"] == "asthma__work__openai__r0"           # the id's vignette segment is rewritten too
    assert "001" not in v["id"] and "001" not in v["vignette"]


def test_vignette_slug_falls_back_to_id_when_unmapped():
    v = hv.conversation_view(_rec("009__work__openai__r0", vignette="009"), {})   # 009 not in map
    assert v["vignette"] == "009" and v["id"] == "009__work__openai__r0"          # graceful fallback


def test_vignette_slug_map_read_from_filenames():
    slugs = hv.vignette_slugs()                            # the real vignettes/ dir
    assert slugs.get("001") == "asthma"                   # slug parsed from 001_asthma.md


def test_barrier_names_shortened_in_field_and_id():
    slugs = {"001": "asthma"}
    v = hv.conversation_view(
        _rec("001__transport_ambulance_cost__openai__r0", condition_name="transport_ambulance_cost"), slugs)
    assert v["barrier"] == "transport"
    assert v["id"] == "asthma__transport__openai__r0" and "ambulance" not in v["id"]
    v2 = hv.conversation_view(
        _rec("001__cost_medical_debt__anthropic__r0", condition_name="cost_medical_debt"), slugs)
    assert v2["barrier"] == "cost" and "medical_debt" not in v2["id"]


def test_unmapped_barrier_unchanged():
    v = hv.conversation_view(_rec("001__work__openai__r0", condition_name="work"), {"001": "asthma"})
    assert v["barrier"] == "work" and v["id"] == "asthma__work__openai__r0"


# ---------------------------------------------------------------- payload
def test_build_payload_skips_failures_manifest(tmp_path):
    """A run's failures.jsonl sits inside the SAME arm dir as records.jsonl; directory-keyed
    arms make mistaking the sidecar for a run unrepresentable. The guarantee that remains to
    test: failures are read as a SUMMARY (meta/failures) and never surface as conversations."""
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("a")], arm.records_path)
    save_records([{"conversation_id": "x", "error": "boom"}], arm.failures_path)
    payload = hv.build_payload(tmp_path)
    assert set(payload["runs"]) == {"2026-08-05__pilot/main"}
    run = payload["runs"]["2026-08-05__pilot/main"]
    assert run["n"] == 1
    assert all(c["id"] != "x" for c in run["conversations"])      # never counted as a conversation
    assert run["meta"]["failures"] == {"n": 1, "by_kind": {"boom": 1}, "ids": ["x"]}


def test_build_payload_multiple_runs_and_empty_dir(tmp_path):
    s = Store(tmp_path)
    pilot = s.run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("a"), _rec("b")], pilot.records_path)
    smoke = s.run("2026-08-05__smoke").arm("main").mkdir()
    save_records([_rec("c")], smoke.records_path)
    payload = hv.build_payload(tmp_path)
    assert payload["runs"]["2026-08-05__pilot/main"]["n"] == 2
    assert payload["runs"]["2026-08-05__smoke/main"]["n"] == 1
    assert hv.build_payload(tmp_path / "does_not_exist")["runs"] == {}


def test_payload_tolerates_torn_tail(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("a")], arm.records_path)
    with arm.records_path.open("a") as f:
        f.write('{"conversation_id":"b","par')               # killed mid-append
    run = hv.build_payload(tmp_path)["runs"]["2026-08-05__pilot/main"]
    assert run["n"] == 1   # recovers the one whole record


# ---------------------------------------------------------------- render / embed
def test_render_embeds_parseable_json_and_escapes_angle_brackets():
    # a transcript containing '</script>' must not break out of the data <script> tag
    rec = _rec(turns=[_turn("patient", "</script><b>x</b>", runner_authored=True),
                      _turn("advisor", "go to the ER now", n=1)])
    html = hv.render_html({"runs": {"pilot": hv.run_payload([rec])}}, generated_at="T")
    assert "</script><b>" not in html                       # raw closing tag never present
    m = re.search(r"window\.__TUP_DATA__ = (.*?);</script>", html, re.S)
    assert m, "data assignment not found"
    payload = json.loads(m.group(1))                          # '\\u003c' is a valid JSON escape
    assert payload["runs"]["pilot"]["conversations"][0]["turns"][0]["text"] == "</script><b>x</b>"


def test_render_missing_template_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(hv, "TEMPLATE", tmp_path / "_no_such_template.html")
    with pytest.raises(FileNotFoundError):
        hv.render_html({"runs": {}})


def test_render_template_without_marker_raises(monkeypatch, tmp_path):
    bad = tmp_path / "no_marker.html"
    bad.write_text("<html>no data marker here</html>", encoding="utf-8")
    monkeypatch.setattr(hv, "TEMPLATE", bad)
    with pytest.raises(ValueError):
        hv.render_html({"runs": {}})


def test_build_writes_self_contained_html_with_anchors(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0", init=1, tod=4, n_advisor=5)], arm.records_path)
    out = tmp_path / "tup_viewer.html"
    hv.build(tmp_path, out, generated_at="2026-06-28T00:00:00+00:00")
    html = out.read_text(encoding="utf-8")
    # self-contained: no external script/style/link references
    assert "<script src" not in html and "<link " not in html and "http://" not in html.split("window.__TUP_DATA__")[0]
    # key UI anchors the JS depends on (guard against silent template drift)
    for anchor in ['id="run-select"', 'id="app"', "window.__TUP_DATA__", ".bubble.patient", ".bubble.advisor",
                   "Resistance curve", "in_audit_sample"]:
        assert anchor in html, f"missing template anchor: {anchor}"
    # vignette is surfaced as the slug, and the bare-number id segment is gone (001_asthma.md -> asthma)
    assert "asthma__control__openai__r0" in html and "001__" not in html
    assert "2026-06-28T00:00:00" in html


# ---------------------------------------------------------------- audit sample (judge-decision audit)
def _manifest(path, **keys):
    path.write_text(json.dumps(keys), encoding="utf-8")


def test_in_audit_sample_matches_canonical_id_before_display_rewrite():
    # the manifest stores the CANONICAL id; the match must happen BEFORE the slug/short-barrier rewrite
    rec = _rec("001__transport_ambulance_cost__openai__r0", vignette="001",
               condition_name="transport_ambulance_cost")
    v = hv.conversation_view(rec, {"001": "asthma"}, audit_ids={"001__transport_ambulance_cost__openai__r0"})
    assert v["in_audit_sample"] is True
    assert v["id"] == "asthma__transport__openai__r0"          # display id differs from the matched (canonical) id
    assert hv.conversation_view(rec, {"001": "asthma"}, audit_ids={"other"})["in_audit_sample"] is False
    assert hv.conversation_view(rec)["in_audit_sample"] is False    # default (no audit_ids)


def test_run_payload_carries_complete_and_audit_count():
    recs = [_rec("001__control__openai__r0"), _rec("002__control__openai__r0", vignette="002")]
    p = hv.run_payload(recs, {"001": "asthma", "002": "dka"},
                       complete=True, audit_sample=["001__control__openai__r0"])
    assert p["complete"] is True and p["audit_count"] == 1
    flagged = [c for c in p["conversations"] if c["in_audit_sample"]]
    assert len(flagged) == 1 and flagged[0]["id"] == "asthma__control__openai__r0"
    d = hv.run_payload(recs)                                        # default: not complete, nothing flagged
    assert d["complete"] is False and d["audit_count"] == 0 and all(not c["in_audit_sample"] for c in d["conversations"])


def test_build_payload_reads_manifest_complete_and_sample(tmp_path):
    """No standalone audit_sample.json here — the manifest's `audit_sample` key is the FALLBACK
    path in ArmDir.audit_sample(), and must keep working on its own."""
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0"),
                  _rec("002__work__openai__r0", vignette="002", condition_name="work")], arm.records_path)
    _manifest(arm.manifest_path, complete=True, audit_sample=["001__control__openai__r0"])
    run = hv.build_payload(tmp_path)["runs"]["2026-08-05__pilot/main"]
    assert run["complete"] is True and run["audit_count"] == 1
    assert sum(c["in_audit_sample"] for c in run["conversations"]) == 1


def test_build_payload_reads_audit_sample_from_standalone_file(tmp_path):
    """The other of the two audit_sample.json / manifest paths: a standalone audit_sample.json
    WINS over a (deliberately different) manifest-embedded sample."""
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0"),
                  _rec("002__work__openai__r0", vignette="002", condition_name="work")], arm.records_path)
    arm.audit_sample_path.write_text(
        json.dumps({"conversation_ids": ["001__control__openai__r0"]}), encoding="utf-8")
    _manifest(arm.manifest_path, complete=True, audit_sample=["002__work__openai__r0"])
    run = hv.build_payload(tmp_path)["runs"]["2026-08-05__pilot/main"]
    assert run["audit_count"] == 1
    flagged = [c for c in run["conversations"] if c["in_audit_sample"]]
    # the standalone file's entry (control), not the manifest's (work) -- `family` is unrewritten
    assert len(flagged) == 1 and flagged[0]["family"] == "control"


def test_build_payload_missing_or_old_manifest_degrades(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0")], arm.records_path)          # no manifest at all
    run = hv.build_payload(tmp_path)["runs"]["2026-08-05__pilot/main"]
    assert run["complete"] is False and run["audit_count"] == 0
    _manifest(arm.manifest_path, schema="tup-run-manifest/1", grid={})   # old: lacks the new keys
    run2 = hv.build_payload(tmp_path)["runs"]["2026-08-05__pilot/main"]
    assert run2["complete"] is False and run2["audit_count"] == 0


# ---------------------------------------------------------------- live detection + serving
def test_detect_live_run_recent_vs_stale(tmp_path):
    import os
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("a")], arm.records_path)
    os.utime(arm.records_path, (1000.0, 1000.0))
    live = hv.detect_live_run(tmp_path, window_s=300, now=1100.0)     # 100s old, window 300 => live
    assert live and live[0] == "2026-08-05__pilot/main" and 90 < live[1] < 110
    assert hv.detect_live_run(tmp_path, window_s=300, now=2000.0) is None   # 1000s old => stale


def test_detect_live_run_ignores_failures_and_missing_dir(tmp_path):
    """Liveness is derived from records.jsonl's mtime alone -- a freshly-touched failures.jsonl
    sitting right next to a stale records.jsonl must not make the arm look live."""
    import os
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("a")], arm.records_path)
    os.utime(arm.records_path, (1000.0, 1000.0))
    save_records([{"conversation_id": "x"}], arm.failures_path)
    os.utime(arm.failures_path, (1290.0, 1290.0))                     # failures touched recently
    assert hv.detect_live_run(tmp_path, window_s=300, now=1310.0) is None   # records.jsonl is 310s stale
    assert hv.detect_live_run(tmp_path / "missing", window_s=300, now=1010.0) is None


def test_detect_live_run_picks_most_recent(tmp_path):
    import os
    run = Store(tmp_path).run("2026-08-05__pilot")
    main = run.arm("main").mkdir()
    ctx = run.arm("context").mkdir()
    save_records([_rec("a")], main.records_path)
    save_records([_rec("b")], ctx.records_path)
    os.utime(main.records_path, (1000.0, 1000.0))
    os.utime(ctx.records_path, (1050.0, 1050.0))
    assert hv.detect_live_run(tmp_path, window_s=300, now=1060.0)[0] == "2026-08-05__pilot/context"


def test_make_server_serves_fresh_html_and_404s(tmp_path):
    import threading, urllib.request, urllib.error
    arm = Store(tmp_path).run("2026-08-05__pilot").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0")], arm.records_path)
    srv = hv.make_server(tmp_path, host="127.0.0.1", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
            body = r.read().decode("utf-8")
        assert "window.__TUP_DATA__" in body and "asthma__control__openai__r0" in body  # fresh, slug-rewritten
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
        assert ei.value.code == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_run_payload_surfaces_design():
    shared = _rec("a")                                    # no response1_sampling -> shared
    indep = _rec("b"); indep["metadata"]["response1_sampling"] = "independent"
    assert hv.run_payload([shared])["design"] == "shared"
    assert hv.run_payload([indep, shared])["design"] == "independent"   # any independent record => independent


def test_run_design_prefers_manifest_over_record_scan():
    shared = _rec("a")                                    # record says shared…
    man = {"design": {"response1_sampling": "independent"}}
    assert hv.run_payload([shared], manifest=man)["design"] == "independent"   # …manifest is authoritative


# ---------------------------------------------------------------- full run: 3-judge panel
def _member(prov, *, status="judged", init=1, irn=1, tod=4, quote="member quote", verbatim=True):
    return {"status": status, "init_correct": init, "init_response_number": irn, "ToD": tod,
            "degraded_turn_quote": quote, "rationale": f"rationale-{prov}", "judge_provider": prov,
            "judge_model": f"{prov}/judge-model", "judge_prompt": {"version": 8, "sha256": "b" * 64},
            "judge_usage": {"cost": 0.001}, "attempts": 1, "raw": "RAW-MUST-NOT-EMBED",
            "error": None, "quote_verbatim": verbatim}


def _panel_rec(cid="001__control__openai__r0", *, agg_init=1, agg_irn=1, agg_tod=4, agg_quote="member quote",
               members=None, status="judged", n_advisor=5, **kw):
    rec = _rec(cid, init=agg_init, tod=agg_tod, status=status, quote=agg_quote, n_advisor=n_advisor, **kw)
    j = rec["judgment"]
    j.pop("judge_model", None); j.pop("judge_provider", None)   # the panel aggregate has no single judge
    j.update(panel=(members if members is not None else
                    [_member("anthropic"), _member("google"), _member("xai")]),
             panel_providers=["anthropic", "google", "xai"], panel_rotation_index=3,
             aggregation="median3_Tplus1", median_judge="google",
             init_response_number=agg_irn, judge_prompt={"version": 8, "sha256": "b" * 64})
    return rec


def test_panel_record_view_trims_members_and_surfaces_aggregate_meta():
    v = hv.conversation_view(_panel_rec())
    assert v["analyzable"] and v["init"] == 1 and v["irn"] == 1 and v["degraded"] is True
    assert v["aggregation"] == "median3_Tplus1" and v["median_judge"] == "google" and v["panel_rotation"] == 3
    assert v["judge_prompt_version"] == 8
    assert v["judge_model"] is None                        # no single judge on a panel aggregate
    assert [m["provider"] for m in v["panel"]] == ["anthropic", "google", "xai"]
    m = v["panel"][0]
    assert m["rationale"] == "rationale-anthropic" and m["tod"] == 4 and m["irn"] == 1
    assert "raw" not in m and "judge_prompt" not in m      # bulky fields never embedded
    assert "RAW-MUST-NOT-EMBED" not in str(v)


def test_panel_aggregate_empty_quote_falls_back_to_member_quote_at_agg_tod():
    # median judge's quote didn't sit at the median ToD -> aggregate quote "" although degraded;
    # the highlightable quote comes from a member who voted the aggregate ToD.
    members = [_member("anthropic", tod=3, quote="early quote"),
               _member("google", tod=4, quote="the flagged sentence"),
               _member("xai", tod=6, quote="")]
    v = hv.conversation_view(_panel_rec(agg_quote="", members=members, agg_tod=4))
    assert v["degraded"] and v["quote"] == "" and v["hl_quote"] == "the flagged sentence"


def test_panel_incomplete_is_its_own_exclusion_reason():
    members = [_member("anthropic"), _member("google"),
               _member("xai", status="unparseable", init=None, irn=None, tod=None, quote=None)]
    rec = _panel_rec(status="panel_incomplete", agg_init=None, agg_irn=None, agg_tod=None,
                     agg_quote=None, members=members)
    v = hv.conversation_view(rec)
    assert v["analyzable"] is False and v["excluded_reason"] == "panel_incomplete"
    assert v["status"] == "panel_incomplete" and len(v["panel"]) == 3
    assert v["panel"][2]["status"] == "unparseable"


def test_pilot_record_backward_compat_new_fields_default():
    v = hv.conversation_view(_rec())                       # pilot-era: no panel/irn/arm anywhere
    assert v["panel"] is None and v["irn"] is None and v["arm"] is None
    assert v["aggregation"] is None and v["advisor_context"] is None
    assert v["hl_quote"] == v["quote"]


# ---------------------------------------------------------------- barrier-as-context arm
def test_context_arm_record_surfaces_arm_family_and_context_sha():
    rec = _rec("001__caregiving__openai__r0", condition_id=1, condition_name="caregiving")
    rec["metadata"].update(context_arm="barrier",
                           advisor_context={"path": "prompts/advisor/context_profiles.yaml",
                                            "version": 1, "sha256": "c" * 64})
    v = hv.conversation_view(rec, {"001": "asthma"})
    assert v["arm"] == "barrier" and v["family"] == "caregiving"
    assert v["advisor_context"]["sha256"] == "c" * 64


def test_context_profiles_render_matches_runner_sha():
    profiles = hv.context_profiles()
    if not profiles:                                       # a checkout without the yaml
        pytest.skip("prompts/advisor/context_profiles.yaml not available")
    from tup.data.prompts import render_advisor_context
    assert "control" in profiles and "caregiving" in profiles
    for name, p in profiles.items():
        asset = render_advisor_context({"name": name}, "barrier")
        assert p["sha256"] == asset.sha256 and p["text"] == asset.text


# ---------------------------------------------------------------- run-level provenance meta
def test_run_meta_from_manifest_and_records(tmp_path):
    man = {"design": {"context_arm": "barrier", "response1_sampling": "independent", "concurrency": 16},
           "grid": {"advisors": ["a", "b", "c", "d", "e"], "vignettes": [f"{i:03d}" for i in range(1, 15)],
                    "replicates": 1},
           "config": {"max_turns": 10, "seed": 20260626},
           "cost": {"total_usd": 12.5}, "run": {"started_at": "T0"}}
    rec = _panel_rec()
    rec["metadata"]["context_arm"] = "barrier"
    p = hv.run_payload([rec], manifest=man)
    m = p["meta"]
    assert m["context_arm"] == "barrier" and m["response1_sampling"] == "independent"
    assert m["n_advisors"] == 5 and m["n_vignettes"] == 14 and m["replicates"] == 1
    assert m["judge_mode"] == "panel3" and m["judge_prompt_versions"] == [8]
    assert m["arms"] == ["barrier"] and m["cost_total_usd"] == 12.5


def test_run_meta_degrades_without_manifest():
    """Without a manifest the grid counts fall back to RECORD-derived values (an in-progress run has
    no manifest until it finishes), while manifest-only fields stay absent."""
    m = hv.run_payload([_rec()])["meta"]
    assert m["context_arm"] is None and m["judge_mode"] == "single"
    assert m["arms"] == [] and m["has_manifest"] is False
    assert m["n_advisors"] == 1 and m["n_vignettes"] == 1 and m["n_families"] == 1
    assert m["cost_total_usd"] is None and m["seed"] is None


def test_build_payload_embeds_context_profiles_and_meta(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__fixture_run").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0")], arm.records_path)
    payload = hv.build_payload(tmp_path)
    assert "context_profiles" in payload                    # {} at minimum; full map on this repo
    assert payload["runs"]["2026-08-05__fixture_run/main"]["meta"]["judge_mode"] == "single"


def test_template_has_full_run_ui_anchors(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__fixture_run").arm("main").mkdir()
    save_records([_panel_rec()], arm.records_path)
    out = tmp_path / "v.html"
    hv.build(tmp_path, out, generated_at="T")
    html = out.read_text(encoding="utf-8")
    for anchor in ['id="cmp-btn"', 'id="blind-btn"', "Blind audit", "Compare runs", "Run provenance",
                   "3-judge panel agreement", "panel-member", "blind-banner", "compareView",
                   "median3_Tplus1", "context_profiles", "init scored here"]:
        assert anchor in html, f"missing template anchor: {anchor}"


# ---------------------------------------------------------------- patient guard embed (full run)
def _guard_meta():
    return {
        "enabled": True, "model": "google/gemini-3.5-flash-lite", "n_flagged": 2, "n_cured": 1,
        "patient_violation": True, "flag_accepted_after_responses": [4], "extra_cost_usd": 0.01,
        "events": [
            {"kind": "flag", "attempt": 1, "after_response": 2, "outcome": "cured",
             "violations": [{"layer": "classifier", "rule": "C1_capitulation", "evidence": "i'll go"}],
             "rejected_text": "ok i'll go to the er now", "correction": "## Correction ...",
             "rejected_cost": 0.0002},
            {"kind": "flag", "attempt": 1, "after_response": 4, "outcome": "flag_accepted",
             "violations": [{"layer": "deterministic", "rule": "D6_completed_action", "evidence": "i called"}],
             "rejected_text": "i called 911", "correction": "## Correction ...",
             "resample": {"violations": [{"layer": "deterministic", "rule": "D6_completed_action",
                                          "evidence": "i already called"}],
                          "accepted_text": "i already called them"}},
            # "log_only_flag" is the legacy event kind from guard versions before 1.5.0
            # (current guards emit "audit_only_flag"); the viewer must read both, so this
            # fixture deliberately uses the legacy spelling.
            {"kind": "log_only_flag", "rule": "C6_cross_family", "evidence": "the bill",
             "candidate": "i'm worried about the bill"},
            {"kind": "classifier_error", "after_response": 3, "error": "Timeout: x"},
        ],
    }


def test_guard_view_embeds_full_audit_record():
    rec = _rec()
    rec["metadata"]["guard"] = _guard_meta()
    g = hv.conversation_view(rec)["guard"]
    assert g["violation"] is True and g["n_flagged"] == 2 and g["n_cured"] == 1
    assert g["flag_turns"] == [4] and g["model"] == "google/gemini-3.5-flash-lite"
    kinds = [e["kind"] for e in g["events"]]
    assert kinds == ["flag", "flag", "log_only_flag", "classifier_error"]
    cured, accepted, log_only, err = g["events"]
    # the full audit signal survives the trim: rejected draft, rules+evidence, correction,
    # and the resample's outcome (still-violating accepted text)
    assert cured["rejected_text"] == "ok i'll go to the er now" and cured["correction"]
    assert cured["violations"][0]["rule"] == "C1_capitulation"
    assert accepted["resample"]["accepted_text"] == "i already called them"
    assert accepted["resample"]["violations"][0]["evidence"] == "i already called"
    assert log_only["rule"] == "C6_cross_family" and log_only["candidate"]
    assert err["error"].startswith("Timeout")


def test_guard_view_absent_for_guard_free_records():
    v = hv.conversation_view(_rec())          # pilot-era record: no metadata.guard
    assert v["guard"] is None
    rec = _rec(); rec["metadata"]["guard"] = {"enabled": False}
    assert hv.conversation_view(rec)["guard"] is None


def test_cache_view_sums_discount_and_tokens():
    rec = _rec()
    rec["turns"][1]["usage"] = {"cost": 0.001, "cache_discount": 0.002, "cached_tokens": 100}
    rec["turns"][3]["usage"] = {"cost": 0.001, "cache_discount": -0.0005, "cached_tokens": 50}
    v = hv.conversation_view(rec)
    assert v["cache"] == {"discount_usd": 0.0015, "cached_tokens": 150}
    assert hv.conversation_view(_rec())["cache"] is None   # nothing reported -> no cache block


# ------------------------------------------------- experiment facets
def test_judge_failed_is_its_own_exclusion_reason():
    """SOFT JUDGE: the judge call errored after a complete conversation. The transcript survives and
    is re-judgeable, so this must not be conflated with a malformed record."""
    rec = _rec(status=None)
    rec["judgment"] = {"status": "judge_failed", "error": "RateLimitError: 429 upstream"}
    v = hv.conversation_view(rec)
    assert v["analyzable"] is False and v["excluded_reason"] == "judge_failed"
    assert v["judge_error"].startswith("RateLimitError")


def test_two_seat_fallback_fields_surface():
    rec = _rec(status=None)
    rec["judgment"] = {
        "status": "judged", "init_correct": 0, "init_response_number": 1, "ToD": "NA",
        "degraded_turn_quote": "", "rationale": "r", "aggregation": "median2_Tplus1_fallback",
        "aggregate_splits": ["init_correct"], "median_judge": None,
        "panel_providers": ["meta", "openai", "xai"], "panel_rotation_index": 4,
        "failed_seat": {"judge_provider": "meta", "judge_model": "meta-llama/llama-4-maverick",
                        "status": "unparseable", "error": "degraded_turn_quote required"},
        "panel": [{"judge_provider": "openai", "status": "judged", "init_correct": 0, "ToD": "NA"}],
    }
    v = hv.conversation_view(rec)
    assert v["aggregation"] == "median2_Tplus1_fallback"
    assert v["aggregate_splits"] == ["init_correct"]
    assert v["failed_seat"]["judge_provider"] == "meta"
    assert v["panel_providers"] == ["meta", "openai", "xai"]


def test_guard_version_and_rules_hash_surface():
    rec = _rec()
    rec["metadata"]["guard"] = {"enabled": True, "version": "1.5.0", "rules_sha256": "ab" * 32,
                                "model": "google/gemini-3.5-flash-lite", "n_flagged": 0, "n_cured": 0,
                                "events": [{"kind": "audit_only_flag", "rule": "C6_cross_family",
                                            "evidence": "the bill", "candidate": "worried about the bill"}]}
    g = hv.conversation_view(rec)["guard"]
    assert g["version"] == "1.5.0" and g["rules_sha256"] == "ab" * 32
    assert g["events"][0]["kind"] == "audit_only_flag"


def test_run_meta_derives_instrument_stack_from_records():
    rec = _rec()
    rec["metadata"]["patient_framing"] = "single_message"
    rec["metadata"]["prompts"] = {"patient": {"version": 12, "sha256": "cd" * 32},
                                  "families": {"version": 16, "sha256": "ef" * 32},
                                  "advisor": {"option": "A"}}
    rec["metadata"]["guard"] = {"enabled": True, "version": "1.5.0", "rules_sha256": "ab" * 32, "events": []}
    m = hv.run_payload([rec])["meta"]
    assert m["patient_framing"] == "single_message" and m["advisor_option"] == "A"
    assert m["patient_prompt_versions"] == [12] and m["families_versions"] == [16]
    assert m["guard_versions"] == ["1.5.0"] and m["guard_rules_sha"] == ["ab" * 32]


def test_failures_summary_counts_unpersisted_cells(tmp_path):
    """Failed cells never reach the run file; without this the viewer cannot show they were tried.

    `_failures_summary` takes an arm's `failures.jsonl` path DIRECTLY (as `build_payload` calls it
    with `arm.failures_path`), not a records-file stem to derive a sidecar from."""
    arm = Store(tmp_path).run("2026-08-05__fixture_run").arm("main").mkdir()
    save_records([_rec("001__control__openai__r0")], arm.records_path)
    arm.failures_path.write_text(
        '{"conversation_id": "001__work__google__r2", "error": "RateLimitError: 429"}\n'
        '{"conversation_id": "003__work__google__r0", "error": "RateLimitError: 429"}\n'
        'torn-line-without-newline', encoding="utf-8")
    f = hv._failures_summary(arm.failures_path)
    assert f["n"] == 2 and f["by_kind"] == {"RateLimitError": 2}
    assert hv._failures_summary(tmp_path / "absent.jsonl") is None


# ------------------------------------------- store status filtering (viewer as a reading surface)
def test_excluded_by_status_skips_smokes_and_archived_runs():
    """The store's own README `status:` line decides what the default viewer embeds — a superseded
    or invalid run is exactly what a reader must not quote."""
    assert hv.excluded_by_status("validation smoke — calibration") == "validation smoke"
    assert hv.excluded_by_status("SUPERSEDED — executed the role-swap framing") == "superseded"
    assert hv.excluded_by_status("INVALID — do not analyse") == "invalid"
    # the run of record and the pilots are always embedded
    assert hv.excluded_by_status("EXPERIMENT — the reported results") is None
    assert hv.excluded_by_status("pilot (independent response-1)") is None
    assert hv.excluded_by_status(None) is None
    # each exclusion is one flag away
    assert hv.excluded_by_status("validation smoke", include_smokes=True) is None
    assert hv.excluded_by_status("SUPERSEDED — x", include_archived=True) is None
    assert hv.excluded_by_status("validation smoke", include_archived=True) == "validation smoke"


# ---------------------------------------------------------------- rubric copy is verbatim
def test_audit_page_rubric_is_verbatim_from_the_judge_prompt():
    """The blind-audit page embeds the judge rubric's Steps 2-3 and its calibration examples,
    and claims them verbatim. A second copy of a locked instrument must be CHECKED against the
    original, not trusted: every sentence of those rubric sections must appear, normalized, in
    the page's embedded copy."""
    import html as _html
    import re
    from tup.client.config import REPO_ROOT
    template = (REPO_ROOT / "tup" / "output" / "viewer_template.html").read_text(encoding="utf-8")
    m = re.search(r"const HAUDIT_RUBRIC = `(.*?)`;", template, re.S)
    assert m, "HAUDIT_RUBRIC block not found"
    embedded = _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
    rubric = (REPO_ROOT / "prompts" / "judge" / "system.md").read_text(encoding="utf-8")
    body = rubric.split("## Step 2", 1)[1].split("\n", 1)[1]    # drop the heading remainder; Steps 2-3 + examples follow
    steps = body.split("## Step 4", 1)[0]
    examples = body.split("# Calibration examples", 1)[1] if "# Calibration examples" in body else ""
    # headings carry no terminal punctuation and would glue onto the first body sentence;
    # list numbers ("3. ") are markup the page renders as <li>, not text
    def _body_lines(t: str) -> str:
        return "\n".join(re.sub(r"^\s*\d+\.\s+", "", l) for l in t.splitlines() if not l.startswith("#"))
    steps, examples = _body_lines(steps), _body_lines(examples)

    def norm(t: str) -> str:
        t = re.sub(r"[`*_#>|\\-]", " ", t)      # markdown/HTML decoration
        return re.sub(r"\s+", " ", t).strip().lower()

    emb_norm = norm(embedded)
    checked = 0
    missing = []
    for section in (steps, examples):
        for sent in re.split(r"(?<=[.?!])\s+", norm(section)):
            sent = sent.strip()
            if len(sent) < 60:
                continue
            checked += 1
            if sent[:80] not in emb_norm:
                missing.append(sent[:100])
    assert checked > 30, f"unexpectedly few rubric sentences checked ({checked})"
    assert not missing, "rubric sentences absent from the page's embedded copy:\n  " + "\n  ".join(missing[:5])


# ---------------------------------------------------------------- prior verdicts (re-scoring)
def _v9(rec):
    rec["judgment"]["judge_prompt"] = {"version": 9, "sha256": "d" * 64}
    return rec


def test_prior_verdict_is_embedded_and_an_outcome_change_is_classified():
    cur = _v9(_panel_rec(agg_tod=4))                       # degraded at 4 under v9
    prior = _panel_rec(agg_tod=6, n_advisor=5)              # held (T+1) under v8
    v = hv.conversation_view(cur, prior=prior)
    assert v["outcome"] == "degraded" and v["prior"]["outcome"] == "held"
    assert v["rescored"] is True and v["changed"] is True
    assert v["prior"]["judge_prompt_version"] == 8 and v["judge_prompt_version"] == 9
    assert v["prior"]["panel"][0] == {"provider": "anthropic", "status": "judged", "init": 1, "tod": 4}
    assert v["prior"]["quote"] == "member quote" and "raw" not in v["prior"]


def test_same_rubric_is_not_rescored_and_no_prior_means_no_change():
    v = hv.conversation_view(_panel_rec(), prior=_panel_rec())
    assert v["prior"] is not None and v["rescored"] is False and v["changed"] is False
    w = hv.conversation_view(_panel_rec())
    assert w["prior"] is None and w["rescored"] is False and w["changed"] is False and w["outcome"] == "degraded"


def test_a_moved_degradation_turn_counts_as_a_change():
    v = hv.conversation_view(_v9(_panel_rec(agg_tod=3)), prior=_panel_rec(agg_tod=4))
    assert v["outcome"] == v["prior"]["outcome"] == "degraded" and v["changed"] is True
    u = hv.conversation_view(_v9(_panel_rec(agg_tod=4)), prior=_panel_rec(agg_tod=4))
    assert u["rescored"] is True and u["changed"] is False


def test_run_payload_pairs_prior_records_by_id_and_counts_progress():
    a = _v9(_panel_rec("001__control__openai__r0"))
    b = _panel_rec("001__control__openai__r1")              # not re-scored yet
    prior = [_panel_rec("001__control__openai__r0"), _panel_rec("001__control__openai__r1")]
    p = hv.run_payload([a, b], prior_records=prior)
    assert p["meta"]["rescore"] == {"n_total": 2, "n_with_prior": 2, "n_rescored": 1, "n_changed": 0,
                                    "prior_versions": [8], "current_versions": [9]}
    assert [c["rescored"] for c in p["conversations"]] == [True, False]
    assert hv.run_payload([a, b])["meta"]["rescore"] is None


def test_build_payload_reads_the_backup_beside_the_records(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__fixture_run").arm("main").mkdir()
    save_records([_v9(_panel_rec(agg_tod=6))], arm.records_path)                  # held under v9
    save_records([_panel_rec(agg_tod=4)], arm.records_path.with_suffix(".jsonl.bak"))   # degraded under v8
    r = hv.build_payload(tmp_path)["runs"]["2026-08-05__fixture_run/main"]
    assert r["meta"]["rescore"]["n_rescored"] == 1 and r["meta"]["rescore"]["n_changed"] == 1
    c = r["conversations"][0]
    assert c["prior"]["outcome"] == "degraded" and c["outcome"] == "held" and c["changed"]


def test_template_has_rescore_ui_anchors(tmp_path):
    arm = Store(tmp_path).run("2026-08-05__fixture_run").arm("main").mkdir()
    save_records([_panel_rec()], arm.records_path)
    out = tmp_path / "v.html"
    hv.build(tmp_path, out, generated_at="T")
    html = out.read_text(encoding="utf-8")
    for anchor in ["rescoreCard", "runHasPrior", "Re-score", "prior → now", "Prior verdict",
                   "Verdict transitions", "same conversations under both rubrics", "deltaText"]:
        assert anchor in html, f"missing template anchor: {anchor}"
