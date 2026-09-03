#!/usr/bin/env python
"""Integrity of the WHOLE store — every run, every study, every arm.

    python scripts/verify_store.py            # check everything
    python scripts/verify_store.py --strict   # notes become failures too

``verify_run.py`` answers "is THIS run complete and internally consistent?", one run at a
time. This answers the broader question: is anything anywhere in the store
corrupt, contradictory, or quietly disagreeing with the catalogue?

One-off integrity checks decay — run once, find nothing, never run again, so the next
corruption is found by whoever trips over it. These checks live here as a standing command
instead.

Exits non-zero if any check fails.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.harness.invocation import ARM_CONTEXT   # noqa: E402
from tup.orchestration import instrument         # noqa: E402
from tup.store import Store                      # noqa: E402

FAILURES: list[str] = []
NOTES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"  [FAIL] {msg}")


def note(msg: str) -> None:
    NOTES.append(msg)


def _load(path: Path):
    """Records plus the line numbers that did not parse. Never raises on bad input."""
    recs, bad = [], []
    try:
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    bad.append(i)
    except OSError as e:
        bad.append(f"unreadable: {e}")
    return recs, bad


def _resolvable_display_ids(candidates: set, id_set: set) -> set:
    """Which of ``candidates`` are viewer DISPLAY ids naming a record that really exists.

    The viewer shows ``<vignette-slug>__<short-barrier>__<advisor>__r<n>`` where a record id is
    ``<vignette-id>__<full-family>__<advisor>__r<n>``. An audit sample written down from the
    viewer therefore holds ids in that display alphabet — this resolves them before crying
    data loss.
    """
    try:
        from tup.output.html_viewer import short_barrier, vignette_slugs
        by_slug = {v: k for k, v in vignette_slugs().items()}
    except Exception:  # noqa: BLE001 — the viewer is optional to this check
        return set()
    out = set()
    for disp in candidates:
        parts = str(disp).split("__")
        if len(parts) != 4 or parts[0] not in by_slug:
            continue
        vid = by_slug[parts[0]]
        if any(c.startswith(f"{vid}__") and c.endswith(f"__{parts[2]}__{parts[3]}")
               and short_barrier(c.split("__")[1]) == parts[1] for c in id_set):
            out.add(disp)
    return out


def check_arm(label: str, arm, *, expect_context: str | None) -> int:
    """Everything checkable about one arm from its own files. Returns the record count."""
    recs, bad = _load(arm.records_path)
    if bad:
        fail(f"{label}: {len(bad)} unparseable line(s) at {bad[:5]}")
    if not recs:
        fail(f"{label}: records.jsonl is empty")
        return 0

    ids = [r.get("conversation_id") for r in recs]
    dupes = [c for c, n in collections.Counter(ids).items() if n > 1]
    if dupes:
        fail(f"{label}: {len(dupes)} duplicate conversation_id(s), e.g. {dupes[:3]}")
    if any(i is None for i in ids):
        fail(f"{label}: {sum(1 for i in ids if i is None)} record(s) with no conversation_id")
    id_set = set(ids)

    # The arm's DIRECTORY NAME is the arm. Records must agree with where they live — the
    # property the store layout guarantees, confirmed here from the bytes.
    if expect_context is not None:
        # ABSENT is not WRONG. Records may predate the context_arm field entirely, so a
        # missing key means "this ran before the field existed", while a key holding a different
        # value means the records contradict the directory they live in. Only the second is a
        # defect; conflating them would make this check cry wolf on any older record.
        present = [(r.get("metadata") or {}) for r in recs]
        without = sum(1 for m in present if "context_arm" not in m)
        seen = {m["context_arm"] for m in present if "context_arm" in m}
        if seen - {expect_context}:
            fail(f"{label}: directory says context_arm={expect_context!r}, records say {sorted(seen)}")
        if without:
            note(f"{label}: {without}/{len(recs)} record(s) predate the context_arm field")

    man = arm.manifest()
    if man is not None:
        n_man = ((man.get("cost") or {}).get("n_conversations"))
        if isinstance(n_man, int) and n_man != len(recs):
            fail(f"{label}: manifest counts {n_man} conversations, records hold {len(recs)}")
        if man.get("arm") not in (None, arm.arm):
            fail(f"{label}: manifest says arm={man.get('arm')!r}, directory says {arm.arm!r}")
    else:
        note(f"{label}: no manifest (a crash leaves records with none)")

    # Sidecars must refer to conversations that exist in this arm.
    for sidecar, path in (("guard", arm.guard_path), ("failures", arm.failures_path)):
        if not path.exists():
            continue
        srecs, sbad = _load(path)
        if sbad:
            fail(f"{label}: {sidecar}.jsonl has {len(sbad)} unparseable line(s)")
        orphans = {r.get("conversation_id") for r in srecs} - id_set - {None}
        if orphans and sidecar == "guard":
            fail(f"{label}: {len(orphans)} guard entr(ies) name conversations not in records, "
                 f"e.g. {sorted(orphans)[:3]}")
        elif orphans:
            note(f"{label}: {len(orphans)} recorded failure(s) never backfilled "
                 f"(expected if the run is unfinished)")

    sample = arm.audit_sample()
    if sample:
        missing = set(sample) - id_set
        if missing:
            # Before crying data loss, check the other alphabet: a sample written down from the
            # viewer carries display ids (vignette slug + short barrier name), not canonical
            # conversation ids. The conversations exist; the ids are written differently.
            unresolved = missing - _resolvable_display_ids(missing, id_set)
            if unresolved:
                fail(f"{label}: audit sample names {len(unresolved)} conversation(s) that are "
                     f"not in records under any id form, e.g. {sorted(unresolved)[:3]}")
            else:
                note(f"{label}: audit sample is stored in the viewer's DISPLAY id form "
                     f"({len(missing)} entries); all resolve to real records")

    lv = arm.lock_verification()
    if lv is not None and lv.get("ok") is False:
        note(f"{label}: lock verification FAILED when written — {'; '.join(lv.get('problems') or [])}")
    return len(recs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="treat notes as failures")
    args = ap.parse_args()

    store = Store.from_env()
    print(f"store: {store.root}\n")

    total = 0
    print("RUNS")
    for run_id in store.list_runs():
        run = store.run(run_id)
        counts = []
        for arm in run.arms():
            if not arm.has_records():
                continue
            n = check_arm(f"{run_id}/{arm.arm}", arm, expect_context=ARM_CONTEXT[arm.arm])
            counts.append(f"{arm.arm}={n}")
            total += n
        if not counts:
            fail(f"{run_id}: a run directory with no records in any arm")
        # Quarantined ids must name conversations that exist.
        quar = run.quarantine()
        for arm_name, qids in quar.items():
            if not qids:
                continue
            have = run.arm(arm_name).record_ids()
            missing = set(qids) - have
            if missing:
                fail(f"{run_id}/{arm_name}: quarantine names {len(missing)} unknown conversation(s)")
        if not run.readme_path.exists():
            fail(f"{run_id}: no README.md, so index.json cannot report a status for it")
        # Instrument snapshot: self-consistent when present; absence is legacy, noted not failed.
        if run.has_instrument():
            broken = instrument.verify_integrity(run.instrument_dir)
            if broken:
                fail(f"{run_id}: instrument snapshot fails its own manifest — {broken[:3]}")
            counts.append("instrument=ok" if not broken else "instrument=BROKEN")
        else:
            note(f"{run_id}: no instrument snapshot (legacy run)")
        print(f"  {run_id:<40} {'  '.join(counts)}")

    print("\nSTUDIES")
    for sid in store.list_studies():
        study = store.study(sid)
        counts = []
        for arm in study.arms():
            if not arm.has_records():
                continue
            # A study's arms are free-form, so there is no context condition to check against.
            n = check_arm(f"{sid}/{arm.arm}", arm, expect_context=None)
            counts.append(f"{arm.arm}={n}")
            total += n
        if study.has_instrument():
            broken = instrument.verify_integrity(study.instrument_dir)
            if broken:
                fail(f"{sid}: instrument snapshot fails its own manifest — {broken[:3]}")
            counts.append("instrument=ok" if not broken else "instrument=BROKEN")
        else:
            note(f"{sid}: no instrument snapshot (legacy run)")
        print(f"  {sid:<40} {'  '.join(counts)}")

    print("\nCATALOGUE")
    if store.index_path.exists():
        on_disk = store.build_index()
        try:
            tracked = json.loads(store.index_path.read_text(encoding="utf-8"))
        except ValueError:
            tracked = None
            fail("index.json is not valid JSON")
        if tracked is not None and tracked != on_disk:
            fail("index.json disagrees with the store — regenerate with scripts/build_index.py")
        else:
            print("  index.json matches the store")
    else:
        note("no index.json (generate with scripts/build_index.py)")

    print(f"\n{'=' * 78}")
    print(f"{total:,} conversations across {len(store.list_runs())} run(s) and "
          f"{len(store.list_studies())} study(ies)")
    for n in NOTES:
        print(f"  note: {n}")
    if FAILURES or (args.strict and NOTES):
        print(f"\n*** {len(FAILURES)} FAILURE(S)"
              + (f" + {len(NOTES)} note(s) under --strict" if args.strict and NOTES else "") + " ***")
        return 1
    print("\nSTORE OK — every run and study is internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
