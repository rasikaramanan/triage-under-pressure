"""Representative audit sample for the post-run human audit of judge decisions.

Picks a small, stratified set of conversations so a human can review "at least one of each KIND of
judge decision" with minimal manual effort, instead of the whole arm. Buckets are judge-DECISION kinds (the
judge sees the vignette but never its gold standard — the gold is a fixed constant in the rubric — so vignette identity is a weak axis); the sample spreads across
barriers/vignettes and oversamples the rare and the self-inconsistent cases.

Pure + deterministic: given the same records and seed it returns the SAME list, every time — the harness
computes it once at run completion and freezes it (a standalone audit_sample.json on current
invocations; older runs carry the copy inside manifest.json); the viewer only reads it. Reuses
``tup.output.metrics`` so analyzable / ToD / T semantics match the by-family aggregator exactly.

Returns CANONICAL ``conversation_id`` strings: at most ``max_n`` bucketed records PLUS every
``skipped_incomplete`` record (appended on top of the cap, so a reviewer can confirm each skip was right).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from tup.output import metrics as M

# Bucket quotas in PRIORITY order (dict preserves insertion order); they sum to the default cap 20.
_QUOTAS = {
    "init0": 5,
    "degraded_early": 4,
    "degraded_late": 6,
    "held_firm": 5,
}

_NULL_GROUP = (None, None, None)


@dataclass(frozen=True)
class _Facts:
    cid: str
    vig: Optional[str]
    adv: Optional[str]
    rep: object
    cond_id: object
    group: tuple
    analyzable: bool
    init: Optional[int]      # 0/1 or None
    tod: Optional[int]       # integer ToD or None
    T: int                   # number of advisor responses
    skipped_incomplete: bool


def _facts(rec: dict) -> _Facts:
    """The per-record fields the buckets need, reusing the metrics classifiers. Never raises — a malformed
    record degrades to not-analyzable / not-skipped so a single bad line can't crash a finished run."""
    try:
        j = rec.get("judgment") or {}
        cid = rec.get("conversation_id") or ""
        vig, adv, rep = rec.get("vignette_id"), rec.get("advisor_provider"), rec.get("replicate")
        init_raw = j.get("init_correct")
        init = init_raw if init_raw in (0, 1) else None
        tod_raw = j.get("ToD")
        tod = tod_raw if isinstance(tod_raw, int) and not isinstance(tod_raw, bool) else None
        return _Facts(
            cid=cid, vig=vig, adv=adv, rep=rep, cond_id=rec.get("condition_id"),
            group=(vig, adv, rep), analyzable=M.is_analyzable(rec), init=init, tod=tod,
            T=M.num_advisor_responses(rec), skipped_incomplete=(j.get("status") == "skipped_incomplete"),
        )
    except Exception:  # noqa: BLE001 — defense; the caller also guards the whole sampling pass
        cid = rec.get("conversation_id", "") if isinstance(rec, dict) else ""
        return _Facts(cid, None, None, None, None, _NULL_GROUP, False, None, None, 0, False)


def _bucket(f: _Facts) -> Optional[str]:
    """The mutually-exclusive degradation bucket of an analyzable init==1 record (else None).
    (init0 is group-level, handled separately.)"""
    if not (f.analyzable and f.init == 1 and f.tod is not None):
        return None
    if 2 <= f.tod <= 3:
        return "degraded_early"
    if 4 <= f.tod <= f.T:
        return "degraded_late"
    if f.tod == f.T + 1:
        return "held_firm"
    return None


def _round_robin_order(pairs: list, rng: random.Random) -> list:
    """Flatten ``[(spread_key, cid), ...]`` into one cid list in round-robin order across spread_keys
    (seeded-shuffled within each key), so any PREFIX is spread across keys rather than clustered."""
    cells: dict = {}
    for key, cid in pairs:
        cells.setdefault(key, []).append(cid)
    order = sorted(cells.keys(), key=lambda k: str(k))      # deterministic key order
    for k in order:
        lst = sorted(set(cells[k]))                          # deterministic before the shuffle
        rng.shuffle(lst)
        cells[k] = lst
    out: list = []
    idx = {k: 0 for k in order}
    total = sum(len(v) for v in cells.values())
    while len(out) < total:
        progressed = False
        for k in order:
            if idx[k] < len(cells[k]):
                out.append(cells[k][idx[k]])
                idx[k] += 1
                progressed = True
        if not progressed:
            break
    return out


def select_audit_sample(records: list, *, seed: int, max_n: int = 20) -> list:
    """Canonical conversation_ids for the audit sample (see module docstring). Deterministic; never raises."""
    rng = random.Random(seed)
    facts = [_facts(r) for r in records]

    # skipped_incomplete: ALL of them, appended on top of the cap (deterministic order).
    skipped = sorted({f.cid for f in facts if f.skipped_incomplete})

    by_group: dict = {}
    for f in facts:
        by_group.setdefault(f.group, []).append(f)

    quotas = _QUOTAS

    # Build each bucket's ordered candidate-cid list IN A FIXED SEQUENCE so rng is consumed deterministically.
    ordered: dict = {}

    # init0: DEDUPE to one representative per (vig,adv,rep) group, spread across vignettes.
    init0_pairs: list = []
    init0_groups = sorted({f.group for f in facts
                           if f.analyzable and f.init == 0 and f.group != _NULL_GROUP}, key=lambda k: str(k))
    for g in init0_groups:
        members = sorted((m for m in by_group[g] if m.analyzable and m.init == 0), key=lambda m: m.cid)
        if members:
            init0_pairs.append((members[0].vig, rng.choice(members).cid))   # spread key = vignette
    ordered["init0"] = _round_robin_order(init0_pairs, rng)

    # degradation buckets: every matching record, spread across barriers (spread key = condition_id).
    for bucket in ("degraded_early", "degraded_late", "held_firm"):
        pairs = [(f.cond_id, f.cid) for f in facts if _bucket(f) == bucket]
        ordered[bucket] = _round_robin_order(pairs, rng)

    # Fill in priority order, min(quota, remaining budget), skipping anything already chosen.
    chosen: list = []
    seen: set = set()
    budget = max_n
    for bucket, quota in quotas.items():
        if budget <= 0:
            break
        take = min(quota, budget)
        for cid in ordered.get(bucket, []):
            if take <= 0 or budget <= 0:
                break
            if cid and cid not in seen:
                chosen.append(cid)
                seen.add(cid)
                take -= 1
                budget -= 1

    chosen.extend(c for c in skipped if c not in seen)
    return chosen
