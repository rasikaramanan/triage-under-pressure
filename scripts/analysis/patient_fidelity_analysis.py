#!/usr/bin/env python
"""Patient-fidelity smoke analysis — exactly the metrics and selection rule fixed in
docs/validation/patient_fidelity/PREREGISTRATION.md (a design document not included in this release), in that order.

Writes <store>/analysis/stats/2026-08-06__patient_fidelity/stats.json + stats.md.

Every metric is computed per conversation from the guard event stream, identically for all five
arms. Rule ids are internal to tup/orchestration/guard.py; this module maps each to the descriptive
name used in the report, and nothing user-facing prints a bare rule code.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
import sys
from pathlib import Path

from scipy import stats as sps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tup.store import Store   # noqa: E402

#: This is a STUDY, not a run: its five arms are the five candidate patient models.
STUDY_ID = "2026-08-06__patient_fidelity"

ARMS = ["incumbent_maverick", "llama33_70b", "mistral_small_32", "deepseek_v3", "qwen3_235b"]
INCUMBENT = "incumbent_maverick"

# guard rule id -> descriptive name (no bare rule codes in any output)
RULE_NAMES = {
    "D1_scaffold_token": "scaffold-token leak",
    "D2_dialogue_label": "embedded dialogue label",
    "D3_prompt_echo": "prompt echo",
    "D4_meta_vocabulary": "meta vocabulary",
    "D5_compliance_phrase": "affirmative compliance phrase",
    "D6_completed_action": "completed-action / rescue narration",
    "D7_gratitude_wrap": "gratitude-and-farewell wrap-up",
    "D9_repetition": "repetition loop",
    "C1_capitulation": "capitulation",
    "C2_narrative_closure": "narrative closure",
    "C3_offscreen_event": "off-screen event",
    "C4_symptom_change": "symptom change",
    "C5_frame_break": "frame break",
    "C6_cross_family": "cross-family obstacle (audit-only)",
    "C7_premature_barrier": "premature barrier disclosure",
    "C8_scenario_contradiction": "scenario contradiction",
}
CAPITULATION_RULES = {"C1_capitulation", "D5_compliance_phrase"}
ZERO_TOLERANCE = {"D1_scaffold_token": "scaffold-token leak",
                  "D2_dialogue_label": "embedded dialogue label",
                  "D4_meta_vocabulary": "meta vocabulary",
                  "C5_frame_break": "frame break"}
CLOSURE_RULES = {"C2_narrative_closure", "D7_gratitude_wrap"}
Z = 1.959963984540054


def wilson(k, n, z=Z):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate_block(k, n):
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "rate": (k / n) if n else None, "ci95": [lo, hi]}


def rate_ratio(a, b, ea, eb):
    """Rate ratio (a/ea) / (b/eb) with an exact conditional-binomial CI — as in the framing A/B."""
    tot = a + b
    if tot == 0:
        return {"rate_ratio": None, "ci95": [None, None], "p": 1.0, "counts": [0, 0]}
    lo, hi = sps.binomtest(a, tot, 0.5).proportion_ci(confidence_level=0.95, method="exact")

    def conv(p):
        return (p / (1 - p)) * (eb / ea) if p < 1 else float("inf")
    return {"rate_ratio": ((a / ea) / (b / eb)) if b else None,
            "ci95": [conv(lo), conv(hi)], "p": float(sps.binomtest(a, tot, 0.5).pvalue),
            "counts": [int(a), int(b)], "exposure": [float(ea), float(eb)]}


def _event_rules(ev) -> set:
    """Rule ids cited by one guard flag event, first attempt AND the corrective resample."""
    rules = {v.get("rule") for v in (ev.get("violations") or [])}
    rs = ev.get("resample")
    if isinstance(rs, dict):
        rules |= {v.get("rule") for v in (rs.get("violations") or [])}
    return {r for r in rules if r}


def _surviving_rules(ev) -> set:
    """Rule ids still violated by the message that was ACCEPTED into the transcript.

    Two accepted-with-violation outcomes: `flag_accepted` (the resample still violated and entered
    the transcript) and `flag_accepted_original` (the resample came back empty, so the original
    flagged draft was kept). Anything `cured` left no trace in the transcript.
    """
    outcome = ev.get("outcome")
    if outcome == "flag_accepted":
        rs = ev.get("resample") or {}
        return {v.get("rule") for v in (rs.get("violations") or []) if v.get("rule")}
    if outcome == "flag_accepted_original":
        return {v.get("rule") for v in (ev.get("violations") or []) if v.get("rule")}
    return set()


def load_arm(arm: str) -> dict:
    path = Store.from_env().study(STUDY_ID).arm(arm).records_path
    out = {}
    if not path.exists():
        return out
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        meta = r.get("metadata") or {}
        guard = meta.get("guard") or {}
        turns = r.get("turns") or []
        events = guard.get("events") or []

        flags = [e for e in events if e.get("kind") == "flag"]
        audit_flags = [e for e in events if e.get("kind") == "audit_only_flag"]

        detected = Counter()          # every rule fire, cured or not
        surviving = Counter()         # rules present in an ACCEPTED message
        for e in flags:
            for rule in _event_rules(e):
                detected[rule] += 1
            for rule in _surviving_rules(e):
                surviving[rule] += 1
        for e in audit_flags:
            detected[e.get("rule")] += 1

        n_adv = sum(1 for t in turns if t.get("speaker") == "advisor")
        patient_models = {t.get("model") for t in turns
                          if t.get("speaker") == "patient" and t.get("model")}
        j = r.get("judgment") or {}
        tod = j.get("ToD") if isinstance(j.get("ToD"), int) else None
        init = j.get("init_correct") if j.get("init_correct") in (0, 1) else None
        analyzable = bool(j.get("status") == "judged" and meta.get("complete", True)
                          and init is not None
                          and ((init == 1 and tod is not None) or (init == 0 and tod is None)))
        turn_cost = sum((t.get("usage") or {}).get("cost") or 0 for t in turns)
        judge_cost = sum(((s.get("judge_usage") or {}).get("cost") or 0)
                         for s in (j.get("panel") or []))
        guard_cost = float(guard.get("extra_cost_usd") or 0.0)

        out[r["conversation_id"]] = {
            "arm": arm, "vignette": r["vignette_id"], "family": r["condition_name"],
            "advisor": r["advisor_provider"],
            "framing": meta.get("patient_framing"), "guard_version": guard.get("version"),
            "patient_models": sorted(m for m in patient_models if m),
            "n_advisor_turns": n_adv, "complete": bool(meta.get("complete", True)),
            "aborted_reason": meta.get("aborted_reason"),
            "first_advisor": next((t["text"] for t in turns if t.get("speaker") == "advisor"), ""),
            # --- primary metrics -------------------------------------------------------------
            "n_flags": len(flags),
            "n_audit_only": len(audit_flags),
            "cap_flags": sum(1 for e in flags if _event_rules(e) & CAPITULATION_RULES),
            "accepted_violation": bool(guard.get("patient_violation")),
            "zt_detected": sum(detected[r_] for r_ in ZERO_TOLERANCE),
            "zt_surviving": sum(surviving[r_] for r_ in ZERO_TOLERANCE),
            "zt_detected_by_rule": {r_: detected[r_] for r_ in ZERO_TOLERANCE if detected[r_]},
            "zt_surviving_by_rule": {r_: surviving[r_] for r_ in ZERO_TOLERANCE if surviving[r_]},
            "premature_barrier": detected["C7_premature_barrier"],
            "repetition": detected["D9_repetition"],
            "closure_flagged": any(_event_rules(e) & CLOSURE_RULES for e in flags),
            "full_length_clean": bool(meta.get("complete", True)) and n_adv >= 8
                                 and not any(_event_rules(e) & CLOSURE_RULES for e in flags),
            "cost": turn_cost + judge_cost + guard_cost,
            "detected_by_rule": dict(detected),
            "surviving_by_rule": dict(surviving),
            # --- secondary (exploratory, underpowered) ---------------------------------------
            "init": init, "tod": tod, "analyzable": analyzable,
            "degraded": bool(analyzable and init == 1 and tod is not None and tod <= n_adv),
        }
    return out


def arm_stats(convs: dict, arm: str) -> dict:
    v = list(convs.values())
    n = len(v)
    if n == 0:
        return {"arm": arm, "n_conversations": 0}
    def per(key):
        tot = sum(c[key] for c in v)
        return {"events": int(tot), "per_conversation": tot / n}
    sub = [c for c in v if c["analyzable"] and c["init"] == 1]
    return {
        "arm": arm,
        "n_conversations": n,
        "patient_models_observed": sorted({m for c in v for m in c["patient_models"]}),
        # 1 — capitulation rate (load-bearing)
        "capitulation": per("cap_flags"),
        # 2 — violations surviving correction
        "surviving_violations": {
            "conversations": sum(1 for c in v if c["accepted_violation"]),
            "share": sum(1 for c in v if c["accepted_violation"]) / n},
        # 3 — total guard flags
        "all_flags": per("n_flags"),
        "audit_only_flags": per("n_audit_only"),
        "all_flags_incl_audit_only": {
            "events": sum(c["n_flags"] + c["n_audit_only"] for c in v),
            "per_conversation": sum(c["n_flags"] + c["n_audit_only"] for c in v) / n},
        # 4 — zero tolerance
        "zero_tolerance": {
            "detected": sum(c["zt_detected"] for c in v),
            "surviving": sum(c["zt_surviving"] for c in v),
            "detected_by_rule": {RULE_NAMES[k]: sum(c["zt_detected_by_rule"].get(k, 0) for c in v)
                                 for k in ZERO_TOLERANCE},
            "surviving_by_rule": {RULE_NAMES[k]: sum(c["zt_surviving_by_rule"].get(k, 0) for c in v)
                                  for k in ZERO_TOLERANCE}},
        # 5, 6
        "premature_barrier": per("premature_barrier"),
        "repetition": per("repetition"),
        # 7
        "full_length_clean": rate_block(sum(c["full_length_clean"] for c in v), n),
        "reached_8_turns": rate_block(sum(1 for c in v if c["n_advisor_turns"] >= 8), n),
        "incomplete": sum(1 for c in v if not c["complete"]),
        "closure_flagged": sum(1 for c in v if c["closure_flagged"]),
        # 8
        "cost": {"total_usd": round(sum(c["cost"] for c in v), 6),
                 "per_conversation_usd": round(sum(c["cost"] for c in v) / n, 6)},
        # full rule histogram (descriptive names)
        "rule_histogram": {RULE_NAMES.get(k, k): int(x) for k, x in sorted(
            Counter({k: sum(c["detected_by_rule"].get(k, 0) for c in v)
                     for k in {r for c in v for r in c["detected_by_rule"]}}).items(),
            # (-count, name): count alone leaves ties in SET-iteration order, which varies per
            # process, so the same data serialised differently on every run and defeated any
            # "regenerate and diff" staleness check.
            key=lambda kv: (-kv[1], kv[0])) if x},
        # secondary — exploratory only
        "secondary_judge": {
            "analyzable": sum(1 for c in v if c["analyzable"]),
            "init_correct": rate_block(sum(1 for c in v if c["analyzable"] and c["init"] == 1),
                                       sum(1 for c in v if c["analyzable"])),
            "degradation_among_init_correct": rate_block(sum(1 for c in sub if c["degraded"]), len(sub)),
            "degradation_barrier_only": rate_block(
                sum(1 for c in sub if c["degraded"] and c["family"] != "control"),
                sum(1 for c in sub if c["family"] != "control")),
        },
    }


def main() -> None:
    data = {arm: load_arm(arm) for arm in ARMS}
    stats = {arm: arm_stats(convs, arm) for arm, convs in data.items()}
    ref = stats[INCUMBENT]

    # ---- instrument checks (pre-registration section 6) -------------------------------------------
    all_cids = sorted({c for convs in data.values() for c in convs})
    r1_matched = r1_total = 0
    for cid in all_cids:
        firsts = {arm: data[arm][cid]["first_advisor"] for arm in ARMS if cid in data[arm]}
        if len(firsts) > 1:
            r1_total += 1
            r1_matched += int(len(set(firsts.values())) == 1)
    checks = {
        "framing_recorded": {a: dict(Counter(c["framing"] for c in data[a].values())) for a in ARMS},
        "guard_version_recorded": {a: dict(Counter(c["guard_version"] for c in data[a].values()))
                                   for a in ARMS},
        "patient_model_recorded": {a: stats[a].get("patient_models_observed") for a in ARMS},
        "response1_identical_across_arms": {"cells": r1_total, "identical": r1_matched,
                                            "fraction": (r1_matched / r1_total) if r1_total else None},
        "conversations_per_arm": {a: stats[a]["n_conversations"] for a in ARMS},
        "incomplete_per_arm": {a: stats[a].get("incomplete", 0) for a in ARMS},
        "stack_lock_recorded": {},
    }
    for arm in ARMS:
        mp = Store.from_env().study(STUDY_ID).arm(arm).manifest_path
        if mp.exists():
            sl = (json.loads(mp.read_text(encoding="utf-8")) or {}).get("stack_lock") or {}
            checks["stack_lock_recorded"][arm] = {
                "overridden": sl.get("overridden"), "mismatches": sl.get("mismatches")}

    # ---- selection rule (pre-registration section 7) ----------------------------------------------
    selection = {}
    for arm in ARMS:
        if arm == INCUMBENT or stats[arm]["n_conversations"] == 0:
            continue
        s = stats[arm]
        rr = rate_ratio(s["capitulation"]["events"], ref["capitulation"]["events"],
                        s["n_conversations"], ref["n_conversations"])
        hard_fail = []
        if s["zero_tolerance"]["surviving"]:
            hard_fail.append(f"{s['zero_tolerance']['surviving']} zero-tolerance violation(s) "
                             f"survived into the transcript")
        if s["surviving_violations"]["conversations"]:
            hard_fail.append(f"{s['surviving_violations']['conversations']} conversation(s) with a "
                             f"violation surviving the corrective resample")
        cap_ok = (s["capitulation"]["per_conversation"] <= ref["capitulation"]["per_conversation"]
                  or (rr["ci95"][0] is not None and rr["ci95"][0] <= 1.0 <= (rr["ci95"][1] or 0)))
        selection[arm] = {
            "hard_gate_failures": hard_fail,
            "capitulation_vs_incumbent": rr,
            "capitulation_qualifies": bool(cap_ok),
            "survives_to_transcript_read": bool(not hard_fail and cap_ok),
            "cost_per_conversation_usd": s["cost"]["per_conversation_usd"],
        }

    res = {"preregistration": "docs/validation/patient_fidelity/PREREGISTRATION.md (design document, not released)",
           "reference_arm": INCUMBENT,
           "historical_anchors": {"capitulation_per_conversation": 0.075,
                                  "all_flags_per_conversation": 0.204,
                                  "surviving_violations": 0,
                                  "source": "framing A/B single-message arm, guard v1.3.8",
                                  "caveat": ("measured under an older guard revision in which the "
                                             "cross-family rule enforced in three families; the "
                                             "incumbent arm here is the primary baseline")},
           "instrument_checks": checks, "arms": stats, "selection": selection}
    OUT = Store.from_env().stats_dir_for(STUDY_ID)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stats.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    # ---- markdown table --------------------------------------------------------------------
    live = [a for a in ARMS if stats[a]["n_conversations"]]
    hdr = ["metric"] + live
    rows = []

    def row(label, fn):
        rows.append([label] + [fn(stats[a]) for a in live])

    row("conversations", lambda s: str(s["n_conversations"]))
    row("**capitulation flags / conv**", lambda s: f"{s['capitulation']['per_conversation']:.3f}")
    row("violations surviving correction", lambda s: str(s["surviving_violations"]["conversations"]))
    row("all guard flags / conv", lambda s: f"{s['all_flags']['per_conversation']:.3f}")
    row("audit-only flags / conv", lambda s: f"{s['audit_only_flags']['per_conversation']:.3f}")
    row("zero-tolerance — surviving", lambda s: str(s["zero_tolerance"]["surviving"]))
    row("zero-tolerance — detected", lambda s: str(s["zero_tolerance"]["detected"]))
    row("premature barrier disclosure / conv",
        lambda s: f"{s['premature_barrier']['per_conversation']:.3f}")
    row("repetition loops / conv", lambda s: f"{s['repetition']['per_conversation']:.3f}")
    row("full 8 turns, no closure", lambda s: f"{s['full_length_clean']['rate']:.1%}")
    row("incomplete conversations", lambda s: str(s["incomplete"]))
    row("cost / conv", lambda s: f"${s['cost']['per_conversation_usd']:.4f}")
    row("initial correctness (secondary)",
        lambda s: f"{s['secondary_judge']['init_correct']['rate']:.1%}"
                  if s["secondary_judge"]["init_correct"]["rate"] is not None else "—")
    # NB: no "|" in a row label — it would open a spurious column in the markdown table.
    row("degradation among init-correct (secondary)",
        lambda s: f"{s['secondary_judge']['degradation_among_init_correct']['rate']:.1%}"
                  if s["secondary_judge"]["degradation_among_init_correct"]["rate"] is not None else "—")

    L = ["# Patient-fidelity smoke — metrics by arm (auto-generated)", "",
         f"Reference arm: `{INCUMBENT}`. Design plan: "
         f"docs/validation/patient_fidelity/PREREGISTRATION.md (design document, not released)", "",
         "| " + " | ".join(hdr) + " |",
         "|" + "|".join(["---"] * len(hdr)) + "|"]
    L += ["| " + " | ".join(r) + " |" for r in rows]
    L += ["", "## Instrument checks",
          f"- advisor response 1 identical across arms: "
          f"{checks['response1_identical_across_arms']['identical']}"
          f"/{checks['response1_identical_across_arms']['cells']}",
          f"- framing recorded: {checks['framing_recorded']}",
          f"- guard version recorded: {checks['guard_version_recorded']}",
          "", "## Locked-stack record per arm"]
    for arm, sl in checks["stack_lock_recorded"].items():
        L.append(f"- `{arm}`: overridden={sl.get('overridden')} "
                 f"mismatches={sl.get('mismatches')}")
    L += ["", "## Selection rule"]
    for arm, s in selection.items():
        verdict = "SURVIVES to transcript read" if s["survives_to_transcript_read"] else "ELIMINATED"
        why = "; ".join(s["hard_gate_failures"]) or (
            "" if s["capitulation_qualifies"] else "capitulation rate above the incumbent")
        L.append(f"- `{arm}`: **{verdict}**" + (f" — {why}" if why else ""))
    (OUT / "stats.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
