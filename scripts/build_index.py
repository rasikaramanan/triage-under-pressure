#!/usr/bin/env python
"""Regenerate the store's index.json — the GENERATED catalogue of every run and study.

    python scripts/build_index.py

Never hand-edit results/index.json. It is derived entirely from what is on disk (each arm's records
and manifest, each run's invocation where present — otherwise the seed and start time come from
the manifests and per-record timestamps — and quarantine, each README's ``status:`` line), so the way to
change it is to change the data or the README, then re-run this.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.store import Store


def main() -> int:
    store = Store.from_env()
    path = store.write_index()
    idx = store.build_index()
    print(f"wrote {path}")
    print(f"  {idx['n_runs']} run(s), {idx['n_studies']} study(ies)")
    # Dry runs are deliberately NOT catalogued — they are $0 mock output, gitignored, and
    # regenerable. Say so, because "0 run(s)" against a store that visibly contains a run directory
    # reads as a bug rather than as a policy.
    n_dry = len(store.list_runs(dry_run=True))
    if n_dry:
        print(f"  ({n_dry} dry run(s) under {store.dry_runs_dir.name}/ — excluded from the index "
              f"by design: mock output, gitignored, regenerable with --dry-run)")
    if not idx["n_runs"] and not idx["n_studies"]:
        print(f"  note: no real runs in {store.root}. A live run writes to runs/; only --dry-run "
              f"writes to dry_runs/.")
    for r in idx["runs"]:
        n = sum((a or {}).get("records") or 0 for a in r["arms"].values())
        print(f"  - {r['id']:<38} {n:>5} conversations   {r.get('status') or ''}")
    for s in idx["studies"]:
        n = sum((a or {}).get("records") or 0 for a in s["arms"].values())
        print(f"  - {s['id']:<38} {n:>5} conversations   {s.get('status') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
