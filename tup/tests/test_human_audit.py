"""The blind human judge-agreement audit: sample draw, verdict validation, recording, embedding.

The audit's frozen sample and the human verdicts back published agreement figures, so the properties that make
them citable are pinned here: the draw is deterministic and quota-exact, the freeze is
write-once, verdict validation mirrors the judge's own output contract, and recording is
append-only with last-row-wins revision semantics.
"""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from tup.output import human_audit as HA
from tup.output.html_viewer import build_payload, make_server
from tup.output.persist import save_records
from tup.store import Store


def _rec(cid, vig, fam_id, fam, adv, init, tod, n_adv=4):
    turns = [{"speaker": "patient", "text": "sym", "runner_authored": True}]
    for i in range(1, n_adv + 1):
        turns.append({"speaker": "advisor", "text": f"a{i}", "advisor_response_number": i})
        turns.append({"speaker": "patient", "text": f"p{i}"})
    return {"conversation_id": cid, "vignette_id": vig, "condition_id": fam_id,
            "condition_name": fam, "advisor_provider": adv, "advisor_model": f"m/{adv}",
            "replicate": 0, "seed": 1, "turns": turns, "metadata": {"complete": True},
            "judgment": {"status": "judged", "init_correct": init, "ToD": tod,
                         "degraded_turn_quote": "", "rationale": "r"}}


def _population(n_deg=25, n_init0=15, n_held=30):
    recs = []
    advisors = ["a1", "a2", "a3"]
    fams = [("control", 0), ("caregiving", 1), ("work", 3)]
    for i in range(n_deg):
        fam, fid = fams[i % 3]
        recs.append(_rec(f"deg{i}", f"{i % 5:03d}", fid, fam, advisors[i % 3], 1, 3))
    for i in range(n_init0):
        fam, fid = fams[i % 3]
        recs.append(_rec(f"i0_{i}", f"{i % 5:03d}", fid, fam, advisors[i % 3], 0, "NA"))
    for i in range(n_held):
        fam, fid = fams[i % 3]
        recs.append(_rec(f"held{i}", f"{i % 5:03d}", fid, fam, advisors[i % 3], 1, 5))  # T+1=5
    return recs


QUOTAS = {"degraded": 8, "init0": 5, "held_firm": 8}


def test_draw_is_deterministic_quota_exact_and_shuffled():
    recs = _population()
    d1 = HA.draw_sample(recs, seed=7, quotas=QUOTAS)
    d2 = HA.draw_sample(recs, seed=7, quotas=QUOTAS)
    assert d1["sample"] == d2["sample"]                       # deterministic
    by = {}
    for e in d1["sample"]:
        by[e["stratum"]] = by.get(e["stratum"], 0) + 1
    assert by == QUOTAS                                       # quota-exact
    assert [e["order"] for e in d1["sample"]] == list(range(21))
    # presentation order must not be sorted by stratum (the shuffle is the blinding)
    strata_seq = [e["stratum"] for e in d1["sample"]]
    assert strata_seq != sorted(strata_seq)
    # population counts recorded for the reweighting analysis
    assert d1["population"] == {"degraded": 25, "init0": 15, "held_firm": 30, "analyzable": 70}


def test_draw_spreads_across_advisors():
    d = HA.draw_sample(_population(), seed=7, quotas=QUOTAS)
    cids = {e["conversation_id"] for e in d["sample"]}
    by_adv = {}
    for r in _population():
        if r["conversation_id"] in cids:
            by_adv[r["advisor_provider"]] = by_adv.get(r["advisor_provider"], 0) + 1
    assert max(by_adv.values()) - min(by_adv.values()) <= 1   # 21 picks over 3 advisors: 7±0


def test_draw_refuses_short_stratum():
    with pytest.raises(ValueError, match="init0"):
        HA.draw_sample(_population(n_init0=3), seed=7, quotas=QUOTAS)


def test_freeze_is_write_once(tmp_path):
    store = Store(tmp_path)
    p = HA.freeze_sample(store, "r1", "main", _population(), seed=7, quotas=QUOTAS)
    assert p.exists()
    with pytest.raises(FileExistsError):
        HA.freeze_sample(store, "r1", "main", _population(), seed=8, quotas=QUOTAS)


def test_validate_verdict_mirrors_judge_contract():
    sample = {"sample": [{"conversation_id": "c1"}], "n": 1}
    n_adv = {"c1": 4}
    ok = HA.validate_verdict({"conversation_id": "c1", "init_correct": 1, "ToD": 5, "note": "x"},
                             sample, n_adv)
    assert ok["ToD"] == 5 and ok["schema"] == HA.VERDICT_SCHEMA     # T+1 survived is legal
    with pytest.raises(ValueError, match="not in the frozen sample"):
        HA.validate_verdict({"conversation_id": "zz", "init_correct": 1, "ToD": 2}, sample, n_adv)
    with pytest.raises(ValueError, match="init_correct"):
        HA.validate_verdict({"conversation_id": "c1", "init_correct": 2, "ToD": 2}, sample, n_adv)
    with pytest.raises(ValueError, match="NA"):
        HA.validate_verdict({"conversation_id": "c1", "init_correct": 0, "ToD": 3}, sample, n_adv)
    with pytest.raises(ValueError, match="outside"):
        HA.validate_verdict({"conversation_id": "c1", "init_correct": 1, "ToD": 6}, sample, n_adv)
    with pytest.raises(ValueError, match="integer ToD"):
        HA.validate_verdict({"conversation_id": "c1", "init_correct": 1, "ToD": "NA"}, sample, n_adv)


def test_validate_review_contract():
    sample = {"sample": [{"conversation_id": "c1"}], "n": 1}
    ok = HA.validate_review({"conversation_id": "c1", "category": " tag ", "note": "why"}, sample)
    assert ok["schema"] == HA.REVIEW_SCHEMA and ok["category"] == "tag" and ok["note"] == "why"
    empty = HA.validate_review({"conversation_id": "c1"}, sample)   # both empty = a legal clear
    assert empty["category"] == "" and empty["note"] == ""
    with pytest.raises(ValueError, match="not in the frozen sample"):
        HA.validate_review({"conversation_id": "zz", "category": "x"}, sample)
    with pytest.raises(ValueError, match="too long"):
        HA.validate_review({"conversation_id": "c1", "category": "x" * 121}, sample)
    with pytest.raises(ValueError, match="strings"):
        HA.validate_review({"conversation_id": "c1", "category": 3}, sample)


def test_review_append_last_wins_and_clear(tmp_path):
    store = Store(tmp_path)
    row = {"schema": HA.REVIEW_SCHEMA, "conversation_id": "c1", "category": "a", "note": "n", "ts": "t1"}
    assert HA.append_review(store, "r1", row) == 1
    assert HA.append_review(store, "r1", {**row, "category": "b", "ts": "t2"}) == 1
    assert HA.load_reviews(store, "r1")["c1"]["category"] == "b"       # last row wins
    # clearing: an empty save drops the annotation from the effective view (history kept)
    assert HA.append_review(store, "r1", {**row, "category": "", "note": "", "ts": "t3"}) == 0
    assert HA.load_reviews(store, "r1") == {}
    assert len(HA.review_path(store, "r1").read_text().strip().splitlines()) == 3


def test_append_is_append_only_and_last_row_wins(tmp_path):
    store = Store(tmp_path)
    row1 = {"schema": HA.VERDICT_SCHEMA, "conversation_id": "c1", "init_correct": 1, "ToD": 3,
            "note": "", "ts": "t1"}
    row2 = {**row1, "init_correct": 0, "ToD": "NA", "ts": "t2"}
    assert HA.append_verdict(store, "r1", row1) == 1
    assert HA.append_verdict(store, "r1", row2) == 1          # same conversation: revision, not new
    lines = HA.verdicts_path(store, "r1").read_text().strip().splitlines()
    assert len(lines) == 2                                    # both rows kept (append-only history)
    assert HA.load_verdicts(store, "r1")["c1"]["ToD"] == "NA"  # effective = last


def _store_with_run(tmp_path, recs):
    store = Store(tmp_path)
    arm = store.run("2026-01-01__t").arm("main")
    arm.path.mkdir(parents=True, exist_ok=True)
    save_records(recs, arm.records_path)
    (store.run("2026-01-01__t").path / "README.md").write_text("status: EXPERIMENT — test\n")
    return store


def test_payload_embeds_sample_and_effective_verdicts(tmp_path):
    recs = _population()
    store = _store_with_run(tmp_path, recs)
    HA.freeze_sample(store, "2026-01-01__t", "main", recs, seed=7, quotas=QUOTAS)
    cid = json.loads(HA.sample_path(store, "2026-01-01__t").read_text())["sample"][0]["conversation_id"]
    HA.append_verdict(store, "2026-01-01__t",
                      {"schema": HA.VERDICT_SCHEMA, "conversation_id": cid, "init_correct": 1,
                       "ToD": 2, "note": "", "ts": "t"})
    HA.append_review(store, "2026-01-01__t",
                     {"schema": HA.REVIEW_SCHEMA, "conversation_id": cid, "category": "tag",
                      "note": "", "ts": "t"})
    p = build_payload(store)
    ha = p["human_audit"]["2026-01-01__t/main"]
    assert ha["n"] == 21 and len(ha["order"]) == 21
    assert ha["verdicts"][cid]["ToD"] == 2
    assert ha["population"]["analyzable"] == 70
    assert ha["reviews"][cid]["category"] == "tag"
    assert ha["review_path"].endswith("review.jsonl")


def test_server_endpoint_records_and_validates(tmp_path):
    recs = _population()
    store = _store_with_run(tmp_path, recs)
    HA.freeze_sample(store, "2026-01-01__t", "main", recs, seed=7, quotas=QUOTAS)
    cid = json.loads(HA.sample_path(store, "2026-01-01__t").read_text())["sample"][0]["conversation_id"]
    srv = make_server(store, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/human-audit"

        def post(body):
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, j = post({"run_id": "2026-01-01__t", "conversation_id": cid,
                        "init_correct": 1, "ToD": 3, "note": "hi"})
        assert code == 200 and j["ok"] and j["n_saved"] == 1 and j["total"] == 21
        code, j = post({"run_id": "2026-01-01__t", "conversation_id": "nope",
                        "init_correct": 1, "ToD": 3})
        assert code == 400 and not j["ok"] and "not in the frozen sample" in j["error"]
        assert HA.load_verdicts(store, "2026-01-01__t")[cid]["note"] == "hi"

        # the review-annotation endpoint shares the route machinery
        rurl = url.replace("/human-audit", "/human-audit-review")

        def post_r(body):
            req = urllib.request.Request(rurl, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, j = post_r({"run_id": "2026-01-01__t", "conversation_id": cid,
                          "category": "judge read a co-mention as a substitution", "note": "turn 3"})
        assert code == 200 and j["ok"] and j["n_saved"] == 1
        code, j = post_r({"run_id": "2026-01-01__t", "conversation_id": "nope", "category": "x"})
        assert code == 400 and "not in the frozen sample" in j["error"]
        assert HA.load_reviews(store, "2026-01-01__t")[cid]["note"] == "turn 3"
    finally:
        srv.shutdown()
        srv.server_close()
