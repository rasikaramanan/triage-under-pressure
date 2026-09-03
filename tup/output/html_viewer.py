"""Build a self-contained HTML run explorer.

ONE static, dependency-free HTML file with all run data embedded inline, so it opens by
double-click with no server (browsers can neither list ``runs/`` nor ``fetch`` local files under
``file://``). It provides: a run selector → a run-level dashboard (init_correct / ToD / Resistance
across advisor / vignette / barrier, reactive to a filter bar) → a filtered conversation list → an
iMessage-style conversation detail view with the judge's verdict pinned on top.

Per-conversation CLASSIFICATION (analyzable / init / ToD / degraded) is computed HERE in Python by
reusing ``tup.output.metrics`` and ``tup.output.cost`` so those are the single source of truth and
the viewer matches the by-family aggregator exactly; the embedded JS only filters and sums these
precomputed fields. Rebuild after a run changes: ``python scripts/build_viewer.py``.
"""
from __future__ import annotations

import json
import re
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from tup.output import cost as costmod
from tup.output import metrics as M
from tup.output.persist import load_records

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / "viewer_template.html"
#: Sentinel. The real defaults are properties of the STORE, resolved at call time so a viewer
#: build honours TUP_RESULTS_ROOT instead of baking one checkout's paths into a module constant.
FROM_STORE = None
VIGNETTES_DIR = REPO_ROOT / "vignettes"
DATA_MARKER = "/*__TUP_DATA__*/"
_VIGNETTE_FILE = re.compile(r"^(\d+)_(.+)$")


def _resolve_store(store):
    """``FROM_STORE`` (or a bare path) -> a real :class:`tup.store.Store`.

    Accepting a path keeps the viewer testable against a tmp_path without an env var, while the
    default still resolves through the environment at CALL time rather than at import time.
    """
    from tup.store import Store
    if store is FROM_STORE:
        return Store.from_env()
    return store if isinstance(store, Store) else Store(store)


def vignette_slugs(vignettes_dir=VIGNETTES_DIR) -> dict:
    """Map ``vignette_id -> slug`` from the vignette filenames (``001_asthma.md`` -> {'001': 'asthma'}).

    The viewer shows the human-readable slug everywhere a vignette is identified — the bare number is
    never surfaced. A missing dir / unmatched file just yields an empty/partial map (callers fall back
    to the id, which only happens for a run whose vignette is absent from the current ``vignettes/``).
    """
    slugs: dict = {}
    d = Path(vignettes_dir)
    if d.exists():
        for p in d.glob("*.md"):
            m = _VIGNETTE_FILE.match(p.stem)
            if m:
                slugs[m.group(1)] = m.group(2)
    return slugs


# Viewer-only short labels for long barrier-family names (display only — the locked family names
# in prompts/patient/families.yaml and the raw JSONL are unchanged).
BARRIER_SHORT = {
    "transport_ambulance_cost": "transport",
    "cost_medical_debt": "cost",
    "hospital_fear": "fear",
}


def short_barrier(name: Optional[str]) -> Optional[str]:
    """Map a barrier family name to its short viewer label (pass-through if not in the table)."""
    return BARRIER_SHORT.get(name, name)


def _tod_int(judgment: dict) -> Optional[int]:
    """ToD as a real int, else None ('NA', missing, or non-integral)."""
    tod = (judgment or {}).get("ToD")
    return tod if isinstance(tod, int) and not isinstance(tod, bool) else None


def _panel_member_view(m: dict) -> dict:
    """Trim one panel member's judgment to what the viewer shows (full run, 3-judge panel).

    Keeps each judge's complete verdict + rationale (all three are stored so
    they can be READ), plus the audit flags — but drops ``raw`` and ``judge_prompt`` (bulky, duplicated
    across members; the prompt version is surfaced once per conversation instead)."""
    err = m.get("error")
    return {
        "provider": m.get("judge_provider"),
        "model": m.get("judge_model"),
        "status": m.get("status"),
        "init": m.get("init_correct") if m.get("init_correct") in (0, 1) else None,
        "irn": m.get("init_response_number"),
        "tod": _tod_int(m),
        "tod_raw": m.get("ToD"),
        "quote": m.get("degraded_turn_quote") or "",
        "rationale": m.get("rationale") or "",
        "attempts": m.get("attempts"),
        "quote_verbatim": m.get("quote_verbatim"),
        "error": (err[:300] if isinstance(err, str) else err),
    }


_GUARD_TEXT_CAP = 4000   # patient drafts run well under this; a cap bounds a pathological embed


def _cap(s, n: int = _GUARD_TEXT_CAP):
    return s[:n] if isinstance(s, str) else s


def _guard_event_view(e: dict) -> dict:
    """Trim one guard event for the embed. Keeps the full audit signal — the
    rejected draft verbatim, the fired rules/evidence, the injected correction, and the resample's
    outcome — dropping nothing but pathological length (see ``_GUARD_TEXT_CAP``)."""
    out: dict = {"kind": e.get("kind")}
    for k in ("after_response", "attempt", "outcome", "rule", "error", "rejected_cost"):
        if e.get(k) is not None:
            out[k] = _cap(e[k], 600) if k == "error" else e[k]
    if isinstance(e.get("violations"), list):
        out["violations"] = [{"layer": v.get("layer"), "rule": v.get("rule"),
                              "evidence": _cap(v.get("evidence"), 600)}
                             for v in e["violations"] if isinstance(v, dict)]
    for k in ("rejected_text", "correction", "candidate"):
        if e.get(k) is not None:
            out[k] = _cap(e[k])
    ev = e.get("evidence")
    if ev is not None:
        out["evidence"] = ([_cap(x, 600) for x in ev] if isinstance(ev, list) else _cap(ev, 600))
    rs = e.get("resample")
    if isinstance(rs, dict):
        out["resample"] = {"accepted_text": _cap(rs.get("accepted_text")),
                           "violations": [{"layer": v.get("layer"), "rule": v.get("rule"),
                                           "evidence": _cap(v.get("evidence"), 600)}
                                          for v in (rs.get("violations") or []) if isinstance(v, dict)]}
    elif rs is not None:
        out["resample"] = _cap(str(rs), 300)   # e.g. "empty_patient_message" (flag_accepted_original)
    return out


def _guard_view(g) -> Optional[dict]:
    """Trim ``metadata.guard`` for the embed; None when the guard was off (guard-free records)."""
    if not (isinstance(g, dict) and g.get("enabled")):
        return None
    return {
        "model": g.get("model"),
        # Records self-identify their guard mechanics; the rule-text hash catches a forgotten
        # version bump. Both are None when a record lacks the field.
        "version": g.get("version"),
        "rules_sha256": g.get("rules_sha256"),
        "n_flagged": g.get("n_flagged") or 0,
        "n_cured": g.get("n_cured") or 0,
        # flag-and-continue: the transcript CONTAINS >=1 accepted-with-uncured-violation turn
        # (records from guard versions that aborted instead have metadata.complete=False)
        "violation": bool(g.get("patient_violation")),
        "flag_turns": [x for x in (g.get("flag_accepted_after_responses") or [])
                       if isinstance(x, int) and not isinstance(x, bool)],
        "extra_cost_usd": g.get("extra_cost_usd"),
        "events": [_guard_event_view(e) for e in (g.get("events") or []) if isinstance(e, dict)],
    }


def _cache_view(rec: dict) -> Optional[dict]:
    """Prompt-cache telemetry summed over the conversation's turns (None when nothing was reported).
    ``discount_usd`` is OpenRouter's ``cache_discount`` — USD credited (can be negative on
    cache-write turns); ``cached_tokens`` sums ``prompt_tokens_details.cached_tokens``."""
    disc = toks = 0
    seen = False
    for t in rec.get("turns", []):
        if not isinstance(t, dict):
            continue
        u = t.get("usage")
        if not isinstance(u, dict):
            continue
        if isinstance(u.get("cache_discount"), (int, float)) and not isinstance(u.get("cache_discount"), bool):
            disc += u["cache_discount"]
            seen = True
        if isinstance(u.get("cached_tokens"), int) and not isinstance(u.get("cached_tokens"), bool):
            toks += u["cached_tokens"]
            seen = seen or u["cached_tokens"] > 0
    return {"discount_usd": round(disc, 6), "cached_tokens": toks} if seen else None


def _turn_view(t: dict) -> dict:
    return {
        "speaker": t.get("speaker"),
        "n": t.get("advisor_response_number"),
        "text": t.get("text") or "",
        "opener": bool(t.get("runner_authored")),
        "truncated": bool(t.get("truncated")),
    }


def _verdict_core(rec: dict) -> dict:
    """The classification every verdict view shares (current or prior): analyzable / init / irn /
    tod / degraded / outcome, derived through ``tup.output.metrics`` so both agree with the
    aggregator. ``outcome`` is the one-word reading of a verdict: ``init0`` (first response never
    directed emergency care), ``held`` (init=1, no downgrade), ``degraded`` (init=1, ToD <= T), or
    ``excluded`` (not analyzable)."""
    j = rec.get("judgment") or {}
    n_adv = M.num_advisor_responses(rec)
    analyzable = M.is_analyzable(rec)
    tod_int = _tod_int(j)
    init = j.get("init_correct") if j.get("init_correct") in (0, 1) else None
    degraded = bool(analyzable and init == 1 and tod_int is not None and tod_int <= n_adv)
    irn = j.get("init_response_number")
    outcome = ("excluded" if not analyzable else "init0" if init == 0 else "degraded" if degraded else "held")
    return {"n_adv": n_adv, "analyzable": analyzable, "init": init, "irn": (irn if irn in (1, 2) else None),
            "tod": tod_int, "tod_raw": j.get("ToD"), "degraded": degraded, "outcome": outcome}


def _prior_view(prior: dict) -> dict:
    """A compact view of the judgment a record carried BEFORE it was re-judged (the arm's
    ``records.jsonl.bak``, which ``scripts/rejudge.py`` takes before its first call). Enough to
    read the two verdicts side by side and to count what moved; the bulky fields stay out."""
    j = prior.get("judgment") or {}
    core = _verdict_core(prior)
    jp = j.get("judge_prompt") if isinstance(j.get("judge_prompt"), dict) else {}
    panel = j.get("panel") if isinstance(j.get("panel"), list) else []
    return {
        "status": (j.get("status") if j else "unjudged") or "unjudged",
        "init": core["init"], "irn": core["irn"], "tod": core["tod"], "tod_raw": core["tod_raw"],
        "degraded": core["degraded"], "outcome": core["outcome"],
        "quote": j.get("degraded_turn_quote") or "",
        "rationale": j.get("rationale") or "",
        "judge_prompt_version": jp.get("version"),
        "judge_prompt_sha": (jp.get("sha256") or "")[:12] or None,
        "median_judge": j.get("median_judge"),
        "aggregation": j.get("aggregation"),
        "panel": [{"provider": m.get("judge_provider"), "status": m.get("status"),
                   "init": m.get("init_correct") if m.get("init_correct") in (0, 1) else None,
                   "tod": _tod_int(m)} for m in panel if isinstance(m, dict)],
    }


def conversation_view(rec: dict, slugs: Optional[dict] = None, audit_ids: Optional[set] = None,
                      prior: Optional[dict] = None) -> dict:
    """Trim one persisted record to the fields the viewer needs, with derived classification.

    Derived fields reuse the metrics module so analyzable/init/ToD/degraded match the aggregator:
      - ``analyzable`` — complete AND cleanly judged (enters the dashboard metrics);
      - ``init``       — 0/1 or None (None when not a clean 0/1 judgment);
      - ``tod``        — the integer ToD (incl. the no-degradation value T+1) or None ('NA'/missing);
      - ``degraded``   — analyzable, init==1, and ToD <= T (T = number of advisor responses).

    The vignette is surfaced by its SLUG, never its number, and long barrier names are shortened
    (see ``BARRIER_SHORT``): the ``vignette`` / ``barrier`` fields carry the display labels, and the
    matching segments of ``conversation_id`` (``001__transport_ambulance_cost__…``) are rewritten to them
    (``asthma__transport__…``) so the long forms appear nowhere in the viewer. ``slugs`` defaults to the
    map read from ``vignettes/``; the batch builder passes it once to avoid re-reading per conversation.

    ``prior`` is the same conversation's record from the arm's pre-re-judge backup, when one exists:
    the view then carries ``prior`` (a compact view of that earlier verdict), ``rescored`` (the current
    judgment was produced under a different rubric than the prior one) and ``changed`` (the outcome
    moved, or both verdicts are degradations at different turns), so the page can show progress and
    compare the two rubrics' verdicts per conversation.
    """
    slugs = vignette_slugs() if slugs is None else slugs
    j = rec.get("judgment") or {}
    meta = rec.get("metadata") or {}
    core = _verdict_core(rec)
    n_adv, analyzable, tod_int, init, degraded = (core["n_adv"], core["analyzable"], core["tod"],
                                                  core["init"], core["degraded"])
    c = costmod.conversation_cost(rec)
    vid = rec.get("vignette_id")
    slug = slugs.get(vid, vid)
    cond_name = rec.get("condition_name")
    barrier = short_barrier(cond_name)
    cid = rec.get("conversation_id") or ""
    in_audit = bool(audit_ids and cid in audit_ids)        # match on the CANONICAL id, BEFORE the rewrite
    parts = cid.split("__")
    if parts and parts[0] == vid:                          # vignette-id segment -> slug
        parts[0] = slug
    if len(parts) > 1 and parts[1] == cond_name:           # barrier segment -> short name
        parts[1] = barrier
    cid = "__".join(parts)

    # 3-judge panel (full run): trim every member; the panel aggregate carries no judge_model of its
    # own, so the members + median_judge are what the viewer displays for "judge".
    raw_panel = j.get("panel")
    panel = [_panel_member_view(m) for m in raw_panel if isinstance(m, dict)] if isinstance(raw_panel, list) else None
    # Highlightable quote: the aggregate's quote, else (aggregate empty — median judge's quote didn't sit
    # at the median ToD) any panel member's quote cast at the aggregate ToD, so a degraded conversation
    # still gets its bubble highlight.
    quote = j.get("degraded_turn_quote") or ""
    hl_quote = quote
    if degraded and not hl_quote and panel:
        for m in panel:
            if m["tod"] == tod_int and m["quote"]:
                hl_quote = m["quote"]
                break

    irn = j.get("init_response_number")                    # K=2 anchor: 1 | 2 | "NA" | None (older records)
    ctx = meta.get("advisor_context")
    jp = j.get("judge_prompt") if isinstance(j.get("judge_prompt"), dict) else {}
    prior_view = _prior_view(prior) if isinstance(prior, dict) else None
    rescored = bool(prior_view and (
        (jp.get("version"), (jp.get("sha256") or "")[:12] or None)
        != (prior_view["judge_prompt_version"], prior_view["judge_prompt_sha"])))
    changed = bool(prior_view and rescored and (
        prior_view["outcome"] != core["outcome"]
        or (prior_view["outcome"] == "degraded" == core["outcome"] and prior_view["tod"] != tod_int)))
    return {
        "id": cid,
        "in_audit_sample": in_audit,
        "vignette": slug,
        "condition_id": rec.get("condition_id"),
        "barrier": barrier,
        "family": cond_name,                               # full family name (keys context_profiles)
        "provider": rec.get("advisor_provider"),
        "model": rec.get("advisor_model"),
        "replicate": rec.get("replicate"),
        "seed": rec.get("seed"),
        "arm": meta.get("context_arm"),                    # "none" | "barrier" | None (records that predate the field)
        "advisor_context": (ctx if isinstance(ctx, dict) else None),
        "status": (j.get("status") if j else "unjudged") or "unjudged",
        "complete": M.is_complete(rec),
        "aborted_reason": meta.get("aborted_reason"),
        "analyzable": analyzable,
        "excluded_reason": M.exclusion_reason(rec),
        "init": init,
        "irn": (irn if irn in (1, 2) else None),
        "tod": tod_int,
        "tod_raw": j.get("ToD"),
        "n_advisor": n_adv,
        "degraded": degraded,
        "quote": quote,
        "hl_quote": hl_quote,
        "rationale": j.get("rationale") or "",
        "judge_model": j.get("judge_model"),
        "judge_provider": j.get("judge_provider"),
        "judge_prompt_version": jp.get("version"),
        "judge_prompt_sha": (jp.get("sha256") or "")[:12] or None,
        "outcome": core["outcome"],
        "prior": prior_view,
        "rescored": rescored,
        "changed": changed,
        "quote_verbatim": j.get("quote_verbatim"),
        "panel": panel,
        "panel_rotation": j.get("panel_rotation_index"),
        "panel_providers": j.get("panel_providers"),
        "aggregation": j.get("aggregation"),
        "median_judge": j.get("median_judge"),
        # Two-seat fallback (median2_Tplus1_fallback): which seat died and which fields the two
        # surviving seats disagreed on — the aggregate is degradation-sensitive on every split.
        "aggregate_splits": j.get("aggregate_splits") if isinstance(j.get("aggregate_splits"), list) else None,
        "failed_seat": j.get("failed_seat") if isinstance(j.get("failed_seat"), dict) else None,
        # SOFT JUDGE: the judge call itself errored; the transcript survives and is re-judgeable.
        "judge_error": (j.get("error")[:400] if isinstance(j.get("error"), str) else None),
        "cost": {k: (round(v, 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                 for k, v in c.items()},
        "guard": _guard_view(meta.get("guard")),
        "cache": _cache_view(rec),
        "patient_framing": meta.get("patient_framing"),
        # Per-record instrument provenance: every prompt asset's version + sha, so
        # a conversation can be traced to the exact instrument that produced it.
        "prompts": (meta.get("prompts") if isinstance(meta.get("prompts"), dict) else None),
        "turns": [_turn_view(t) for t in rec.get("turns", []) if isinstance(t, dict)],
    }


def _run_design(records: list[dict], manifest: Optional[dict] = None) -> str:
    """'independent' if the manifest's design section says so (authoritative when present), else if any
    record was generated with independent response-1 sampling; else 'shared' (records that
    predate the field → None → shared). Drives the dashboard's test choice: shared → McNemar /
    stratified log-rank (matched on the shared response-1); independent → Fisher / χ²."""
    d = ((manifest or {}).get("design") or {}).get("response1_sampling")
    if d in ("independent", "shared"):
        return d
    for r in records:
        if (r.get("metadata") or {}).get("response1_sampling") == "independent":
            return "independent"
    return "shared"


def _run_meta(manifest: dict, convos: list[dict], *, failures: Optional[dict] = None) -> dict:
    """Run-level provenance the dashboard header shows, so an older single-judge dataset
    could never be mistaken for the full experiment's (5 advisors,
    3-judge panel, per-arm records).

    The count fields (conversations, advisors, vignettes, conditions, replicates) FALL BACK to
    record-derived values when the manifest is missing — the manifest is only written when a run
    finishes, so an IN-PROGRESS run would otherwise show an empty provenance card; the remaining
    manifest-only fields (sampling mode, concurrency, seed, cost, started_at, the stack-lock
    block) simply stay empty until it lands. Judge mode and the prompt/guard versions are always
    derived from the RECORDS, so a mixed or mislabeled file is visible.
    """
    man = manifest or {}
    design = man.get("design") or {}
    grid = man.get("grid") or {}
    cfg = man.get("config") or {}
    uniq = lambda f: sorted({v for v in (f(c) for c in convos) if v})   # noqa: E731

    def _prompt_bit(kind, field):
        return sorted({(c["prompts"][kind] or {}).get(field) for c in convos
                       if isinstance(c.get("prompts"), dict) and isinstance(c["prompts"].get(kind), dict)
                       and (c["prompts"][kind] or {}).get(field) is not None})

    return {
        "context_arm": design.get("context_arm") or (uniq(lambda c: c.get("arm")) or [None])[0],
        "response1_sampling": design.get("response1_sampling"),
        "patient_framing": design.get("patient_framing")
                           or (uniq(lambda c: c.get("patient_framing")) or [None])[0],
        "concurrency": design.get("concurrency"),
        "n_advisors": len(grid.get("advisors") or cfg.get("advisors") or [])
                      or len({c.get("model") for c in convos if c.get("model")}) or None,
        "n_vignettes": len(grid.get("vignettes") or [])
                       or len({c.get("vignette") for c in convos if c.get("vignette")}) or None,
        "n_families": len({c.get("condition_id") for c in convos if c.get("condition_id") is not None}) or None,
        "replicates": grid.get("replicates")
                      or (len({c.get("replicate") for c in convos if c.get("replicate") is not None}) or None),
        "providers": cfg.get("providers"),
        "max_turns": cfg.get("max_turns"),
        "seed": cfg.get("seed"),
        "cost_total_usd": (man.get("cost") or {}).get("total_usd"),
        "started_at": (man.get("run") or {}).get("started_at"),
        "has_manifest": bool(man),
        # The launcher's fail-closed locked-stack record (None on an old run; an OVERRIDDEN run is
        # self-identifying here — the viewer flags it loudly).
        "stack_lock": man.get("stack_lock") if isinstance(man.get("stack_lock"), dict) else None,
        "failures": failures or None,
        # derived from the records themselves:
        "judge_mode": ("panel3" if any(c.get("panel") for c in convos) else "single"),
        "judge_prompt_versions": sorted({c["judge_prompt_version"] for c in convos
                                         if c.get("judge_prompt_version")}),
        # re-scoring progress against the arm's pre-re-judge backup (absent when there is none)
        "rescore": _rescore_meta(convos),
        "arms": uniq(lambda c: c.get("arm")),
        "guard_model": next((c["guard"]["model"] for c in convos
                             if c.get("guard") and c["guard"].get("model")), None),
        "guard_versions": uniq(lambda c: (c.get("guard") or {}).get("version")),
        "guard_rules_sha": uniq(lambda c: (c.get("guard") or {}).get("rules_sha256")),
        "patient_prompt_versions": _prompt_bit("patient", "version"),
        "families_versions": _prompt_bit("families", "version"),
        "families_sha": _prompt_bit("families", "sha256"),
        "patient_prompt_sha": _prompt_bit("patient", "sha256"),
        "advisor_option": (_prompt_bit("advisor", "option") or [None])[0],
    }


def _rescore_meta(convos: list[dict]) -> Optional[dict]:
    """Progress of a re-judge in flight or finished: how many conversations carry a verdict from a
    rubric other than their prior one, and how many of those verdicts moved. None without a backup."""
    with_prior = [c for c in convos if c.get("prior")]
    if not with_prior:
        return None
    rescored = [c for c in with_prior if c.get("rescored")]
    return {
        "n_total": len(convos),
        "n_with_prior": len(with_prior),
        "n_rescored": len(rescored),
        "n_changed": sum(1 for c in rescored if c.get("changed")),
        "prior_versions": sorted({c["prior"]["judge_prompt_version"] for c in with_prior
                                  if c["prior"].get("judge_prompt_version")}),
        "current_versions": sorted({c["judge_prompt_version"] for c in rescored
                                    if c.get("judge_prompt_version")}),
    }


def _prior_records_path(records_path: Path) -> Path:
    """The pre-re-judge backup ``scripts/rejudge.py`` takes next to an arm's records (gitignored)."""
    return records_path.with_suffix(records_path.suffix + ".bak")


def run_payload(records: list[dict], slugs: Optional[dict] = None,
                *, complete: bool = False, audit_sample: Optional[list] = None,
                manifest: Optional[dict] = None, failures: Optional[dict] = None,
                prior_records: Optional[list] = None) -> dict:
    audit_ids = set(audit_sample or [])
    prior_by_id = {r.get("conversation_id"): r for r in (prior_records or []) if isinstance(r, dict)}
    convos = [conversation_view(r, slugs, audit_ids, prior=prior_by_id.get(r.get("conversation_id")))
              for r in records]
    return {"n": len(convos), "complete": bool(complete), "design": _run_design(records, manifest),
            "audit_count": len(audit_ids),
            "meta": _run_meta(manifest or {}, convos, failures=failures),
            "conversations": convos}


def _failures_summary(p: Path, max_ids: int = 200) -> Optional[dict]:
    """Summarize an arm's ``failures.jsonl`` — cells that errored out and were never persisted.

    These conversations are absent from the records entirely, so without this the viewer cannot
    show that they were attempted at all (an in-progress run's rate-limit casualties, say). Returns
    None when there is no failures file."""
    if not p.exists():
        return None
    n = 0
    by_kind: dict = {}
    ids: list = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue           # tolerate a torn final line, like load_records
                n += 1
                kind = str(rec.get("error") or "").split(":", 1)[0] or "unknown"
                by_kind[kind] = by_kind.get(kind, 0) + 1
                if len(ids) < max_ids:
                    ids.append(rec.get("conversation_id"))
    except OSError:
        return None
    return {"n": n, "by_kind": by_kind, "ids": ids} if n else None


def _display_id(canonical: str, slugs: dict) -> str:
    """The viewer's display form of a canonical conversation_id (mirrors ``conversation_view``'s
    rewrite: vignette number -> slug, long barrier name -> short label)."""
    parts = (canonical or "").split("__")
    if parts:
        parts[0] = slugs.get(parts[0], parts[0])
    if len(parts) > 1:
        parts[1] = short_barrier(parts[1])
    return "__".join(parts)


def _human_audit_embed(store, runs: dict, slugs: dict) -> dict:
    """Embed every frozen human-audit sample whose run/arm is in this build, plus saved verdicts.

    BLINDNESS NOTE: the embed necessarily carries each conversation's stratum (the completion
    summary needs it for reweighting) and the payload elsewhere carries the panel verdicts — the
    audit UI shows the rater NONE of it until all conversations are judged. A self-audit cannot be
    cryptographically blind against its own auditor; the UI just never puts the answer on screen.
    """
    from tup.output import human_audit as HA
    out: dict = {}
    base = store.human_audit_dir
    if not base.exists():
        return out
    for sp in sorted(base.glob("*/sample.json")):
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        run_key = f"{doc.get('run_id')}/{doc.get('arm')}"
        if run_key not in runs:
            continue                     # sample for a run this build doesn't embed
        verdicts = HA.load_verdicts(store, doc["run_id"])
        out[run_key] = {
            "run_id": doc.get("run_id"),
            "arm": doc.get("arm"),
            "n": doc.get("n"),
            "quotas": doc.get("quotas"),
            "population": doc.get("population"),
            "order": [{"cid": e["conversation_id"],
                       "display": _display_id(e["conversation_id"], slugs),
                       "stratum": e["stratum"], "order": e["order"]}
                      for e in doc.get("sample", [])],
            "verdicts": {cid: {k: row.get(k) for k in ("init_correct", "ToD", "note", "ts")}
                         for cid, row in verdicts.items()},
            "verdicts_path": str(HA.verdicts_path(store, doc["run_id"])),
            # post-completion disagreement annotations (the review page writes these)
            "reviews": {cid: {k: row.get(k) for k in ("category", "note", "ts")}
                        for cid, row in HA.load_reviews(store, doc["run_id"]).items()},
            "review_path": str(HA.review_path(store, doc["run_id"])),
        }
    return out


def _read_manifest(mpath: Path) -> dict:
    """Read an arm's ``manifest.json`` (its PROJECT_SPEC.md section 14 reproducibility metadata). Returns ``{}`` on missing / torn /
    old-without-the-new-keys, so an arm without a current manifest degrades to ``complete=False`` +
    empty sample (no checkbox) rather than erroring."""
    try:
        man = json.loads(mpath.read_text(encoding="utf-8"))
        return man if isinstance(man, dict) else {}
    except (OSError, ValueError):
        return {}


#: Runs whose README ``status:`` starts with this are excluded unless asked for by name or by
#: ``include_smokes``. Together they can dwarf the embedded payload,
#: which lands in a single self-contained HTML file a person has to open in a browser.
SMOKE_STATUS = "validation smoke"

#: Runs the store itself marks as NOT FOR ANALYSIS. Excluded by default for the same reason the
#: smokes are — the viewer is a reading surface, and a superseded run is the one thing a reader must
#: not quote (a superseded run can be a large fraction of the default page, and its
#: numbers must not be quotable by accident). Available by name via ``run_ids`` or with ``include_archived``.
ARCHIVED_STATUSES = ("superseded", "invalid")


def excluded_by_status(status: Optional[str], *, include_smokes: bool = False,
                       include_archived: bool = False) -> Optional[str]:
    """Why this run is left out of the default viewer, or None to embed it.

    Reads the store's own ``status:`` line rather than a second list kept in sync by hand.
    """
    s = (status or "").strip().lower()
    if not include_smokes and s.startswith(SMOKE_STATUS):
        return "validation smoke"
    if not include_archived:
        for tag in ARCHIVED_STATUSES:
            if s.startswith(tag):
                return tag
    return None


def _arms_to_show(store, run_ids=None, include_smokes: bool = False,
                  include_archived: bool = False, skipped: Optional[list] = None) -> list:
    """Arms to embed, as ``(display_key, ArmDir)``, runs before studies.

    The display key is ``<run-id>/<arm>``. Keying on the arm directory (never a filename stem)
    is what makes arm identity unambiguous: which arm a record belongs to is a structural fact,
    so the key can just say what it is.

    ``run_ids`` selects explicitly (studies included; an unknown id is the caller's error to catch).
    Otherwise every run and study is embedded EXCEPT any validation smokes, which stay on disk
    and one flag away — the viewer is a reading surface, and a 100MB page is not one.
    """
    from tup.store import _read_status
    out = []
    for run_id in store.list_runs():
        run = store.run(run_id)
        if run_ids is not None:
            if run_id not in run_ids:
                continue
        else:
            why = excluded_by_status(_read_status(run), include_smokes=include_smokes,
                                     include_archived=include_archived)
            if why:
                if skipped is not None:
                    skipped.append((run_id, why))
                continue
        for a in run.arms():
            if a.has_records():
                out.append((f"{run_id}/{a.arm}", a))
    for study_id in store.list_studies():
        if run_ids is not None and study_id not in run_ids:
            continue
        for a in store.study(study_id).arms():
            if a.has_records():
                out.append((f"{study_id}/{a.arm}", a))
    return out


def build_payload(store=FROM_STORE, *, run_ids=None, include_smokes: bool = False,
                  include_archived: bool = False, skipped: Optional[list] = None) -> dict:
    """Build the embed payload from the store's arms (validation smokes and archived runs
    excluded unless requested).

    Each arm also carries its manifest's ``complete`` flag + frozen ``audit_sample`` (for the
    post-run judge-decision audit), so the viewer can show the audit-sample checkbox only for finished arms."""
    store = _resolve_store(store)
    slugs = vignette_slugs()        # read the vignette-number → slug map once for the whole build
    runs: dict = {}
    for key, arm in _arms_to_show(store, run_ids, include_smokes, include_archived, skipped):
        man = _read_manifest(arm.manifest_path)
        bak = _prior_records_path(arm.records_path)
        prior = load_records(bak) if bak.exists() else None
        runs[key] = run_payload(load_records(arm.records_path), slugs,
                                complete=bool(man.get("complete", False)),
                                audit_sample=arm.audit_sample() or [],
                                manifest=man, failures=_failures_summary(arm.failures_path),
                                prior_records=prior)
    briefs = family_briefs()
    # Every families.yaml version the runs actually used, resolved from git when it is not this
    # checkout's — so a conversation always shows the brief that drove it.
    run_shas = {c.get("prompts", {}).get("families", {}).get("sha256")
                for r in runs.values() for c in r["conversations"]
                if isinstance(c.get("prompts"), dict) and isinstance(c["prompts"].get("families"), dict)}
    run_shas.discard(briefs.get("sha256"))
    briefs["by_sha"] = _families_from_git(run_shas)
    return {"runs": runs, "runs_dir": str(store.runs_dir),
            "human_audit": _human_audit_embed(store, runs, slugs),
            "context_profiles": context_profiles(),
            "family_briefs": briefs,
            "barrier_short": dict(BARRIER_SHORT)}


def _families_from_git(want_shas) -> dict:
    """Resolve family briefs for families.yaml versions that are NOT the working tree's.

    A run records the sha256 of the families.yaml it used. The viewer is often built from a checkout
    whose prompts tree is older or newer than the run, and the brief for a family added since — the non-structural comparator, say —
    would simply be missing. So for every sha a run recorded that the working tree does not match,
    walk that file's git history, hash each historical version, and embed the one that matches. Pure
    read-only git; returns ``{}`` if git is unavailable or nothing matches (e.g. a released tree
    with no git history — there the run's instrument snapshot is the provenance surface instead).
    """
    import hashlib
    import subprocess
    from tup.data.prompts import PATIENT_FAMILIES
    rel = Path(PATIENT_FAMILIES).relative_to(REPO_ROOT).as_posix()
    want = {s for s in want_shas if s}
    if not want:
        return {}
    try:
        revs = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--all", "--format=%H", "--", rel],
                              capture_output=True, text=True, timeout=30, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return {}
    out: dict = {}
    for rev in revs[:400]:                      # bounded walk; newest first
        if not want:
            break
        try:
            blob = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{rev}:{rel}"],
                                  capture_output=True, timeout=30, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        sha = hashlib.sha256(blob).hexdigest()
        if sha not in want:
            continue
        want.discard(sha)
        try:
            import yaml as _yaml
            doc = _yaml.safe_load(blob.decode("utf-8")) or {}
        except Exception:  # noqa: BLE001 — an unparseable historical version is simply skipped
            continue
        out[sha] = {"version": doc.get("version"), "sha256": sha, "source": "git",
                    "families": _brief_map(doc)}
    return out


def _brief_map(doc: dict) -> dict:
    """families.yaml document -> {family name: brief} (the patient-side instrument, per condition)."""
    fams: dict = {}
    for fam in doc.get("families") or []:
        if not isinstance(fam, dict) or not fam.get("name"):
            continue
        fams[fam["name"]] = {
            "id": fam.get("id"),
            "resists": bool(fam.get("resists", False)),
            "scenario": fam.get("scenario"),
            "core_barrier": fam.get("core_barrier"),
            "allowed": [str(a) for a in (fam.get("allowed") or [])],
            "not_allowed": fam.get("not_allowed"),
        }
    return fams


def family_briefs() -> dict:
    """The patient-side brief for each barrier family, keyed by full family name.

    What the PATIENT was told: its situation, the one obstacle it may raise, the sanctioned concern
    ladder, and what it must never do. Lets a conversation be read against the instrument that drove
    it (the record's families sha says whether this text is the one that ran). ``{}`` when the yaml
    is unavailable."""
    try:
        import hashlib

        from tup.data.prompts import PATIENT_FAMILIES, load_families
        doc = load_families() or {}
        sha = hashlib.sha256(Path(PATIENT_FAMILIES).read_bytes()).hexdigest()
        # sha256 of the yaml AS THE RUNNER HASHES IT, so the viewer can tell whether the brief shown
        # is the one that actually ran (this build's prompts tree may be older/newer than the run).
        return {"version": doc.get("version"), "sha256": sha, "families": _brief_map(doc)}
    except Exception:  # noqa: BLE001 — a missing/foreign prompts tree must not break the build
        return {}


def context_profiles() -> dict:
    """The barrier-as-context arm's per-family advisor system blocks, rendered EXACTLY as the runner
    renders them (same template + sha), keyed by full family name — so a ctx-arm conversation's detail
    view can show the standing context its advisor actually saw, and flag a sha mismatch if the yaml
    has drifted since the run. Returns {} when the yaml is absent (older checkout) — the viewer then
    shows only the record's sha."""
    try:
        import yaml as _yaml
        from tup.data.prompts import ADVISOR_CONTEXT, render_advisor_context
        doc = _yaml.safe_load(Path(ADVISOR_CONTEXT).read_text())
        out = {}
        for name in (doc.get("profiles") or {}):
            asset = render_advisor_context({"name": name}, "barrier")
            out[name] = {"text": asset.text, "sha256": asset.sha256,
                         "version": asset.version, "path": asset.path}
        return out
    except Exception:  # noqa: BLE001 — a missing/foreign prompts tree must not break the build
        return {}


def render_html(payload: dict, *, generated_at: Optional[str] = None) -> str:
    """Inject the payload JSON into the template at the data marker (escaping ``<`` and line/para
    separators so the blob can't break out of the ``<script>`` or trip a JS parser)."""
    tmpl = TEMPLATE.read_text(encoding="utf-8")
    n_markers = tmpl.count(DATA_MARKER)
    if n_markers != 1:
        # str.replace hits EVERY occurrence — a second marker (e.g. quoted in a comment) would embed
        # the entire multi-MB blob twice and silently double the built file.
        raise ValueError(f"template {TEMPLATE} must contain the data marker {DATA_MARKER!r} exactly "
                         f"once, found {n_markers}")
    payload = {**payload, "generated_at": generated_at}
    blob = (json.dumps(payload, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(chr(0x2028), "\\u2028").replace(chr(0x2029), "\\u2029"))
    return tmpl.replace(DATA_MARKER, blob)


def build(store=FROM_STORE, out_path=FROM_STORE, *, generated_at: Optional[str] = None,
          run_ids=None, include_smokes: bool = False, include_archived: bool = False) -> Path:
    """Build the self-contained viewer HTML from the store and write it into the store.

    The viewer is a REBUILDABLE ARTIFACT, so it belongs under ``analysis/`` with the stats —
    not at the repo root, where a generated file reads as source and invites hand edits.
    """
    store = _resolve_store(store)
    out_path = store.viewer_path if out_path is FROM_STORE else Path(out_path)
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat()
    html = render_html(build_payload(store, run_ids=run_ids, include_smokes=include_smokes,
                                     include_archived=include_archived),
                       generated_at=generated_at)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- live serving
# When a run is actively writing, the static snapshot goes stale; serving instead lets a browser
# refresh show the latest with no rebuild. "Live" is detected purely from file mtime (no cooperation
# from the runner needed, so it catches runs already in flight). The window is generous because a
# serial cell — generate + judge — can take a couple of minutes between appends.
LIVE_WINDOW_S = 300


def detect_live_run(store=FROM_STORE, *, window_s: float = LIVE_WINDOW_S, now: Optional[float] = None):
    """Return ``(display_key, age_seconds)`` of the most-recently-written arm if it was modified
    within ``window_s`` (a run is probably in progress), else ``None``."""
    store = _resolve_store(store)
    now = time.time() if now is None else now
    best = None
    for key, arm in _arms_to_show(store):
        try:
            age = now - arm.records_path.stat().st_mtime
        except OSError:
            continue
        if age <= window_s and (best is None or age < best[1]):
            best = (key, age)
    return best


def make_server(store=FROM_STORE, *, host: str = "127.0.0.1", port: int = 0,
                run_ids=None, include_smokes: bool = False,
                include_archived: bool = False) -> ThreadingHTTPServer:
    """Build (but don't start) a server that RE-RENDERS the viewer from the store on every GET, so a
    browser refresh always reflects the store's current contents (the dropdown included)."""
    store = _resolve_store(store)

    # Lazy per-run caches for the human-audit endpoint: the frozen sample and each conversation's
    # advisor-response count T (needed to validate ToD's [2, T+1] range) — loading 1,470 records on
    # every POST would make each save sluggish for no reason.
    _audit_cache: dict = {}

    def _audit_facts(run_id: str):
        if run_id not in _audit_cache:
            from tup.output import human_audit as HA
            sample_doc = json.loads(HA.sample_path(store, run_id).read_text(encoding="utf-8"))
            arm = store.run(run_id).arm(sample_doc.get("arm") or "main")
            n_adv = {r.get("conversation_id"): M.num_advisor_responses(r)
                     for r in load_records(arm.records_path)}
            _audit_cache[run_id] = (sample_doc, n_adv)
        return _audit_cache[run_id]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split("?", 1)[0] not in ("/", "/index.html", "/tup_viewer.html"):
                self.send_response(404)
                self.end_headers()
                return
            html = render_html(build_payload(store, run_ids=run_ids,
                                             include_smokes=include_smokes,
                                             include_archived=include_archived),
                               generated_at=datetime.now(timezone.utc).isoformat())
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 — the human-audit recorders (verdicts + review annotations)
            route = self.path.split("?", 1)[0]
            if route not in ("/human-audit", "/human-audit-review"):
                self._json(404, {"ok": False, "error": "unknown endpoint"})
                return
            from tup.output import human_audit as HA
            from tup.store import RunNotFoundError
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                run_id = body.get("run_id")
                sample_doc, n_adv = _audit_facts(run_id)
                if route == "/human-audit":
                    row = HA.validate_verdict(body, sample_doc, n_adv)
                    n_saved = HA.append_verdict(store, run_id, row)
                else:
                    row = HA.validate_review(body, sample_doc)
                    n_saved = HA.append_review(store, run_id, row)
            except (ValueError, OSError, KeyError, RunNotFoundError) as e:
                self._json(400, {"ok": False, "error": f"{type(e).__name__}: {e}"})
                return
            self._json(200, {"ok": True, "n_saved": n_saved, "total": sample_doc.get("n"),
                             "conversation_id": row["conversation_id"]})

        def log_message(self, *args):  # keep the console quiet
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve(store=FROM_STORE, *, host: str = "127.0.0.1", open_browser: bool = True,
          run_ids=None, include_smokes: bool = False, include_archived: bool = False) -> None:
    """Serve the live viewer on an ephemeral port until interrupted (Ctrl-C)."""
    srv = make_server(store, host=host, port=0, run_ids=run_ids, include_smokes=include_smokes,
                      include_archived=include_archived)
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"  serving live at {url}")
    print("  the run dropdown reflects the store live — refresh the browser for the latest. Ctrl-C to stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — a headless box without a browser must not crash serving
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
    finally:
        srv.server_close()
