"""Build + validate the full-run roster (config/roster.csv).

Enumerates EVERY conversation in the experiment's design: 14 vignettes x 7 conditions x
5 advisors, at R=3 replicates in the main Option-A arm (1,470 rows) and R=1 in the
barrier-context arm (490 rows) = 1,960 rows, each with its patient model, advisor model, and
all 3 panel judges (rotation matching the runner: rotation_index = int(vignette_id) + replicate;
tup/harness/driver.py).

The grid's final shape is carried by the constants below: the 14-vignette set, the per-arm
replicate split R=3/R=1, and the seventh condition — the non-structural hospital-fear
comparator.

The roster is a checked-in artifact; the run harness derives the
same assignments from config and MUST agree with this file (asserted by --check and by
tup/tests/test_panel.py).

    python scripts/build_roster.py            # (re)write config/roster.csv
    python scripts/build_roster.py --check    # validate the existing CSV against config + rules
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tup.client.config import load_config
from tup.client.provider import ProviderRegistry
from tup.orchestration.runner import SEED_FAMILY_STRIDE

ROSTER = Path(__file__).resolve().parents[1] / "config" / "roster.csv"

VIGNETTE_IDS = [f"{i:03d}" for i in range(1, 15)]        # 001-014 (the closed 14-vignette set)
FAMILIES = ["control", "caregiving", "transport_ambulance_cost", "work",
            "cost_medical_debt", "no_insurance", "hospital_fear"]
FAMILY_IDS = {n: i for i, n in enumerate(FAMILIES)}   # matches families.yaml ids 0-6
# Per-arm replicates: main Option-A arm R=3; barrier-context arm R=1. The keys here are the
# roster CSV's own arm labels (design vocabulary, frozen with the checked-in roster); the store
# directories for the same two arms are named main/ and context/ ("option_a" -> main,
# "barrier_context" -> context).
ARM_REPLICATES = {"option_a": 3, "barrier_context": 1}
ARMS = list(ARM_REPLICATES)

FIELDS = ["arm", "conversation_id", "vignette_id", "family", "advisor_provider", "advisor_model",
          "patient_provider", "patient_model", "judge_1", "judge_2", "judge_3",
          "rotation_index", "seed"]


def build_rows(config) -> list[dict]:
    reg = ProviderRegistry(config)
    rows = []
    for arm in ARMS:
        for vid in VIGNETTE_IDS:
            for fam in FAMILIES:
                fam_id = FAMILY_IDS[fam]
                for adv in config.advisors:
                    for rep in range(ARM_REPLICATES[arm]):
                        rotation = int(vid) + rep
                        judges = reg.panel_for(adv, rotation)
                        rows.append({
                            "arm": arm,
                            "conversation_id": f"{vid}__{fam}__{adv}__r{rep}",
                            "vignette_id": vid,
                            "family": fam,
                            "advisor_provider": adv,
                            "advisor_model": reg.slug_for(adv),
                            "patient_provider": config.patient,
                            "patient_model": config.patient_model or reg.slug_for(config.patient),
                            "judge_1": judges[0],
                            "judge_2": judges[1],
                            "judge_3": judges[2],
                            "rotation_index": rotation,
                            "seed": config.seed + rep + fam_id * SEED_FAMILY_STRIDE,
                        })
    return rows


def validate(rows: list[dict], config) -> list[str]:
    """Return a list of violation strings (empty = valid)."""
    errors = []
    seen = set()
    expected = sum(len(VIGNETTE_IDS) * len(FAMILIES) * len(config.advisors) * r
                   for r in ARM_REPLICATES.values())
    if len(rows) != expected:
        errors.append(f"row count {len(rows)} != expected {expected}")
    for r in rows:
        key = (r["arm"], r["conversation_id"])
        if key in seen:
            errors.append(f"duplicate row: {key}")
        seen.add(key)
        judges = [r["judge_1"], r["judge_2"], r["judge_3"]]
        if len(set(judges)) != 3:
            errors.append(f"{key}: judges not distinct: {judges}")
        if r["advisor_provider"] in judges:
            errors.append(f"{key}: judge shares advisor provider {r['advisor_provider']} "
                          "(leave-one-provider-out violated)")
        for j in judges:
            if j not in config.providers:
                errors.append(f"{key}: unknown judge provider {j}")
        if r["patient_provider"] != config.patient:
            errors.append(f"{key}: patient {r['patient_provider']} != config {config.patient}")
    return errors


def balance_report(rows: list[dict], providers=None) -> str:
    seats = Counter()
    sitouts = Counter()
    # the provider slate comes from config, never a literal — a config change must not leave
    # this report silently describing a stale slate
    slate = set(providers) if providers is not None else set(load_config().providers)
    for r in rows:
        judges = {r["judge_1"], r["judge_2"], r["judge_3"]}
        seats.update(judges)
        eligible = slate - {r["advisor_provider"]}
        sitouts.update(eligible - judges)
    lines = ["judge-seat counts per provider (target: near-equal):"]
    lines += [f"  {p}: {seats[p]}" for p in sorted(seats)]
    lines.append("sit-out counts per provider:")
    lines += [f"  {p}: {sitouts[p]}" for p in sorted(sitouts)]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate existing CSV instead of writing")
    args = ap.parse_args()
    config = load_config()
    if config.judge_panel != 3:
        sys.exit("config/models.yaml must set roles.judge_panel: 3 for the full-run roster")

    rows = build_rows(config)
    errors = validate(rows, config)
    if errors:
        print("\n".join(errors[:20]))
        return 1

    if args.check:
        with ROSTER.open() as f:
            on_disk = list(csv.DictReader(f))
        as_str = [{k: str(v) for k, v in r.items()} for r in rows]
        if on_disk != as_str:
            print(f"MISMATCH: {ROSTER} does not match the config-derived roster "
                  f"({len(on_disk)} vs {len(as_str)} rows or differing content). Re-run without --check.")
            return 1
        print(f"OK: {ROSTER} matches config-derived assignments ({len(rows)} rows, 0 violations)")
    else:
        with ROSTER.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {ROSTER} ({len(rows)} rows, 0 violations)")
    print(balance_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
