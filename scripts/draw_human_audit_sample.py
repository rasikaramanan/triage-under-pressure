"""Freeze the blind human judge-agreement audit sample.

    python scripts/draw_human_audit_sample.py                # run of record, main arm, n=50

Draws the deterministic stratified sample (degraded 20 / init0 10 / held-firm 20, seed from
config/models.yaml) and writes ``<store>/analysis/human_audit/<run-id>/sample.json``. Refuses to
overwrite an existing frozen draw. The rater then completes the audit from the viewer
(``python scripts/build_viewer.py --serve``, "Human audit" button); the released draw is
``results/analysis/human_audit/2026-08-06__full_experiment/sample.json``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.client.config import load_config
from tup.output.human_audit import QUOTAS, freeze_sample, sample_path
from tup.output.persist import load_records
from tup.store import Store

RUN_OF_RECORD = "2026-08-06__full_experiment"


def main() -> int:
    ap = argparse.ArgumentParser(description="Freeze the human-audit sample (blind agreement audit).")
    ap.add_argument("--run-id", default=RUN_OF_RECORD)
    ap.add_argument("--arm", default="main",
                    help="arm to sample (the released audit sampled main only — the reported estimand)")
    args = ap.parse_args()

    store = Store.from_env()
    arm = store.run(args.run_id).arm(args.arm)
    if not arm.has_records():
        print(f"error: {args.run_id}/{args.arm} has no records", file=sys.stderr)
        return 2
    seed = load_config().seed
    try:
        path = freeze_sample(store, args.run_id, args.arm, load_records(arm.records_path), seed=seed)
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        print(f"(the frozen draw lives at {sample_path(store, args.run_id)})", file=sys.stderr)
        return 2
    import json
    doc = json.loads(path.read_text(encoding="utf-8"))
    print(f"froze {doc['n']} conversations -> {path}")
    print(f"  quotas {QUOTAS} · seed {seed} · population {doc['population']}")
    by = {}
    for e in doc["sample"]:
        by[e["stratum"]] = by.get(e["stratum"], 0) + 1
    print(f"  drawn per stratum: {by}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
