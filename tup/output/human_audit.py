"""The blind human judge-agreement audit: sample draw + verdict recording.

The audit measures human–panel agreement on the run of record's two load-bearing verdicts. The
author scores each sampled conversation blind (same information the panel had: transcript only),
entering ``init_correct`` and ``ToD`` in the viewer; rows land in an append-only JSONL here.

Design:
  - Frame: the MAIN arm of the run of record only, n=50.
  - Strata by PANEL decision kind — degraded 20 / init0 10 / held-firm 20 — with fixed quotas
    (no deliberate enrichment for panel-splits or other hard cases; splits land at their natural
    rates). Allocation is a PRECISION choice, not a bias one: the analysis
    reweights per-stratum agreement back to the run's label distribution, so oversampling the
    degraded stratum sharpens the reported judge-validity verdict without biasing the overall
    estimate.
  - Spread: a greedy diversity pass keeps every advisor, condition and vignette represented rather
    than letting the RNG cluster.
  - Presentation order is shuffled (own seed) so position carries no signal; the viewer shows the
    rater only "conversation k of 50" while judging — never the id, never the stratum.
  - The audit measures; it never re-judges. Disagreements are reported as judge-validity/
    limitations evidence, never as corrections to the frozen results.

Layout (under ``<store>/analysis/human_audit/<run_id>/``):
  - ``sample.json``    — the frozen draw: quotas, seeds, population counts (the weights), and the
                         50 conversations in presentation order. Written once; never regenerated.
                         May additionally carry a ``reshuffles`` block: an audit-trail record of
                         an authorized pre-judging reorder of the presentation positions (order
                         carries no analysis weight; membership and strata never change). This
                         module does not write it — the process that performs a reshuffle does,
                         and the recorded order IS the presentation order of record.
  - ``verdicts.jsonl`` — append-only human verdicts, one JSON row per save; the EFFECTIVE verdict
                         for a conversation is its LAST row (re-saving a conversation revises it).
  - ``review.jsonl``   — optional append-only per-disagreement annotations (may be absent).

Everything here is pure given (records, seeds) — ``freeze_sample`` writes one draw and refuses
to overwrite it.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tup.output import metrics as M

SAMPLE_SCHEMA = "tup-human-audit-sample/1"
VERDICT_SCHEMA = "tup-human-audit-verdict/1"
REVIEW_SCHEMA = "tup-human-audit-review/1"

#: Stratum quotas. Keys are the panel-decision strata.
QUOTAS = {"degraded": 20, "init0": 10, "held_firm": 20}

#: Presentation-order shuffle gets its own derived seed so changing one draw parameter can never
#: silently reorder an already-frozen presentation.
ORDER_SEED_OFFSET = 1


def audit_dir(store, run_id: str) -> Path:
    return store.human_audit_dir_for(run_id)


def sample_path(store, run_id: str) -> Path:
    return audit_dir(store, run_id) / "sample.json"


def verdicts_path(store, run_id: str) -> Path:
    return audit_dir(store, run_id) / "verdicts.jsonl"


def review_path(store, run_id: str) -> Path:
    """Post-completion disagreement annotations (``review.jsonl``) — the rater's analysis of WHY a
    verdict differed from the panel's, recorded per conversation from the viewer's review page.
    Same append-only / last-row-wins semantics as verdicts. Annotations never alter verdicts or
    the frozen results; they are write-up material."""
    return audit_dir(store, run_id) / "review.jsonl"


def stratum_of(rec: dict) -> Optional[str]:
    """Panel-decision stratum of one analyzable record (None if not analyzable)."""
    if not M.is_analyzable(rec):
        return None
    j = rec["judgment"]
    if j["init_correct"] == 0:
        return "init0"
    tod = j["ToD"]
    if isinstance(tod, int) and tod <= M.num_advisor_responses(rec):
        return "degraded"
    return "held_firm"


def _diversity_pick(candidates: list, chosen: list) -> dict:
    """Pick the candidate that best balances advisor/condition/vignette coverage.

    Score = how often this candidate's advisor + condition + vignette already appear in the chosen
    set (lexicographically: max axis count first, then the sum). Ties resolve by the pre-shuffled
    candidate order, so the draw is deterministic for a given seed.
    """
    counts: dict = {"adv": {}, "cond": {}, "vig": {}}
    for r in chosen:
        counts["adv"][r.get("advisor_provider")] = counts["adv"].get(r.get("advisor_provider"), 0) + 1
        counts["cond"][r.get("condition_id")] = counts["cond"].get(r.get("condition_id"), 0) + 1
        counts["vig"][r.get("vignette_id")] = counts["vig"].get(r.get("vignette_id"), 0) + 1

    def score(r):
        a = counts["adv"].get(r.get("advisor_provider"), 0)
        c = counts["cond"].get(r.get("condition_id"), 0)
        v = counts["vig"].get(r.get("vignette_id"), 0)
        return (max(a, c, v), a + c + v)

    best = min(candidates, key=score)
    return best


def draw_sample(records: list[dict], *, seed: int, quotas: Optional[dict] = None) -> dict:
    """Deterministic stratified draw. Returns the frozen-sample document (see SAMPLE_SCHEMA).

    Raises ``ValueError`` if a stratum cannot fill its quota — a silent short draw would produce a
    sample that no longer matches its stated design.
    """
    quotas = dict(QUOTAS if quotas is None else quotas)
    by_stratum: dict = {k: [] for k in quotas}
    population: dict = {k: 0 for k in quotas}
    n_analyzable = 0
    for r in records:
        s = stratum_of(r)
        if s is None:
            continue
        n_analyzable += 1
        population[s] = population.get(s, 0) + 1
        if s in by_stratum:
            by_stratum[s].append(r)

    rng = random.Random(seed)
    chosen: list = []
    chosen_meta: list = []
    for stratum, k in quotas.items():
        pool = list(by_stratum[stratum])
        if len(pool) < k:
            raise ValueError(f"stratum {stratum!r} has {len(pool)} candidates < quota {k}")
        rng.shuffle(pool)                       # deterministic tie-break order for the greedy pass
        for _ in range(k):
            pick = _diversity_pick(pool, chosen)
            pool.remove(pick)
            chosen.append(pick)
            chosen_meta.append({"conversation_id": pick["conversation_id"], "stratum": stratum})

    order_rng = random.Random(seed + ORDER_SEED_OFFSET)
    order = list(range(len(chosen_meta)))
    order_rng.shuffle(order)
    presented = [chosen_meta[i] for i in order]
    for pos, entry in enumerate(presented):
        entry["order"] = pos

    return {
        "schema": SAMPLE_SCHEMA,
        "seed": seed,
        "order_seed": seed + ORDER_SEED_OFFSET,
        "quotas": quotas,
        # population counts ARE the analysis weights: per-stratum agreement is reweighted by these
        # to give the run-level agreement estimate (the sample deliberately over-represents the
        # rare strata, so the raw sample rate is NOT the headline number).
        "population": {**population, "analyzable": n_analyzable},
        "n": len(presented),
        "sample": presented,                    # in PRESENTATION order
    }


def freeze_sample(store, run_id: str, arm: str, records: list[dict], *, seed: int,
                  quotas: Optional[dict] = None, now: Optional[str] = None) -> Path:
    """Draw once and write ``sample.json``; refuses to overwrite an existing frozen draw."""
    path = sample_path(store, run_id)
    if path.exists():
        raise FileExistsError(f"{path} already exists — the draw is frozen; delete it deliberately "
                              f"if you truly intend a fresh draw (any recorded verdicts would no "
                              f"longer match their sample)")
    doc = draw_sample(records, seed=seed, quotas=quotas)
    doc["run_id"] = run_id
    doc["arm"] = arm
    doc["drawn_at"] = now or datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ verdict recording (server side)

def validate_verdict(body: dict, sample_doc: dict, n_advisor_by_cid: dict) -> dict:
    """Validate one verdict submission against the frozen sample; return the row to append.

    Rules mirror the judge's own output contract so the analysis can compare like with like:
      - the conversation must be in the frozen sample;
      - ``init_correct`` is 0 or 1;
      - init 0  -> ToD must be "NA";
      - init 1  -> ToD is an integer in [2, T+1]; T+1 means survived/no degradation (the viewer's
        "survived" button submits the computed integer, exactly as the judge does).
    Raises ``ValueError`` with a human-readable reason on any violation.
    """
    cid = body.get("conversation_id")
    in_sample = {e["conversation_id"] for e in sample_doc.get("sample", [])}
    if cid not in in_sample:
        raise ValueError(f"conversation {cid!r} is not in the frozen sample")
    init = body.get("init_correct")
    if init not in (0, 1):
        raise ValueError(f"init_correct must be 0 or 1, got {init!r}")
    tod = body.get("ToD")
    T = n_advisor_by_cid.get(cid)
    if init == 0:
        if tod != "NA":
            raise ValueError(f"init_correct=0 requires ToD='NA', got {tod!r}")
    else:
        if not isinstance(tod, int) or isinstance(tod, bool):
            raise ValueError(f"init_correct=1 requires an integer ToD, got {tod!r}")
        if T is not None and not (2 <= tod <= T + 1):
            raise ValueError(f"ToD {tod} outside [2, {T + 1}] for this conversation (T={T})")
    note = body.get("note") or ""
    if not isinstance(note, str):
        raise ValueError("note must be a string")
    return {
        "schema": VERDICT_SCHEMA,
        "conversation_id": cid,
        "init_correct": init,
        "ToD": tod,
        "note": note[:2000],
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_last_wins(path: Path) -> dict:
    """Effective rows: last row wins per conversation_id. Tolerates a torn final line."""
    out: dict = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("conversation_id"):
            out[row["conversation_id"]] = row
    return out


def append_verdict(store, run_id: str, row: dict) -> int:
    """Append one validated row; returns the number of DISTINCT conversations now judged."""
    _append_row(verdicts_path(store, run_id), row)
    return len(load_verdicts(store, run_id))


def load_verdicts(store, run_id: str) -> dict:
    return _load_last_wins(verdicts_path(store, run_id))


# ------------------------------------------------------------- disagreement annotations (review)

def validate_review(body: dict, sample_doc: dict) -> dict:
    """Validate one disagreement-annotation submission; return the row to append.

    ``category`` is a short free-text tag (the rater's own taxonomy — deliberately not an enum so
    the taxonomy can emerge from the analysis); ``note`` is free text. Saving both empty is legal
    and, by last-row-wins, clears the annotation.
    """
    cid = body.get("conversation_id")
    in_sample = {e["conversation_id"] for e in sample_doc.get("sample", [])}
    if cid not in in_sample:
        raise ValueError(f"conversation {cid!r} is not in the frozen sample")
    category = body.get("category") or ""
    note = body.get("note") or ""
    if not isinstance(category, str) or not isinstance(note, str):
        raise ValueError("category and note must be strings")
    if len(category) > 120:
        raise ValueError(f"category too long ({len(category)} > 120 chars) — it is a tag, "
                         f"put the detail in the note")
    return {
        "schema": REVIEW_SCHEMA,
        "conversation_id": cid,
        "category": category.strip(),
        "note": note[:2000],
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def append_review(store, run_id: str, row: dict) -> int:
    """Append one validated annotation; returns the number of DISTINCT conversations annotated."""
    _append_row(review_path(store, run_id), row)
    return len(load_reviews(store, run_id))


def load_reviews(store, run_id: str) -> dict:
    """Effective annotations (last row wins); rows cleared to empty category+note are dropped."""
    rows = _load_last_wins(review_path(store, run_id))
    return {cid: r for cid, r in rows.items() if (r.get("category") or r.get("note"))}
