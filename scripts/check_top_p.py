#!/usr/bin/env python3
"""TUP — effective top_p verification (the sampling-provenance gate).

Prints the recorded effective-top_p provenance for every model in config/models.yaml, RE-FETCHES the
live OpenRouter API for the observable facts the determination rests on (each model still listed, top_p
still accepted/declined the same way on every endpoint, same upstream providers), and EXITS NON-ZERO if
anything drifted — so it can gate any run.

We OMIT top_p (locked decision), and OpenRouter injects its documented default top_p=1.0 for an omitted
param on models that accept it; a model that does not accept top_p falls back to its upstream's fixed
default. See tup/client/top_p.py for the full determination + per-model basis + sources.

  MUST be run immediately before initiating ANY live run. Do not start a run if this
  exits non-zero; record the verified values + the verification timestamp in the run metadata.

Usage:
    python scripts/check_top_p.py            # live fetch + verify (needs OPENROUTER_TUP_API_KEY)
    python scripts/check_top_p.py --offline  # table + config<->provenance consistency only, no network

Reads OPENROUTER_TUP_API_KEY (and optional OPENROUTER_BASE_URL) from .env via tup.client.config.
Exit code 0 only when the live API is consistent with the recorded provenance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path when run directly

from tup.client.config import load_config
from tup.client.top_p import EFFECTIVE_TOP_P, LAST_VERIFIED, fetch_live_facts, verify_top_p


def _print_table(slugs: list[str]) -> None:
    print(f"Effective top_p provenance (top_p OMITTED by design; last_verified {LAST_VERIFIED})\n")
    for slug in slugs:
        rec = EFFECTIVE_TOP_P.get(slug)
        if rec is None:
            print(f"  {slug}\n      ** NO PROVENANCE ENTRY — add it to tup/client/top_p.py **\n")
            continue
        basis_kind = "OpenRouter-injected" if rec["accepts_top_p"] else "upstream default (top_p not accepted)"
        print(f"  {slug}")
        print(f"      effective top_p : {rec['top_p']}   ({basis_kind})")
        print(f"      upstream        : {', '.join(rec['provider'])}")
        print(f"      source          : {rec['source_url']}")
        print(f"      last_verified   : {rec['last_verified']}")
        print(f"      basis           : {rec['basis']}")
        if rec.get("native_default_note"):
            print(f"      ⚠ divergence    : {rec['native_default_note']}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify effective top_p provenance against the live API.")
    ap.add_argument("--offline", action="store_true",
                    help="skip the live fetch; only check config<->provenance consistency")
    args = ap.parse_args()

    cfg = load_config()
    slugs = set(cfg.providers.values())
    if getattr(cfg, "patient_model", None):
        slugs.add(cfg.patient_model)   # per-role override slug is live-used
    if getattr(cfg, "guard_model", None):
        # Fetched here because verify_top_p() checks it: omitting the guard slug would make the
        # verifier read the missing fact as "NOT FOUND on the live model list" — a spurious
        # hard-fail. A gate that cries wolf gets overridden, so this standalone script and the
        # in-launcher preflight must fetch the same slug set.
        slugs.add(cfg.guard_model)
    slugs = sorted(slugs)
    _print_table(slugs)

    if args.offline:
        ok, drift = verify_top_p(live=False, config=cfg)
    else:
        try:
            facts = fetch_live_facts(slugs)
        except Exception as e:  # noqa: BLE001 — surface any fetch failure as a hard gate failure
            print(f"FAIL: could not fetch live OpenRouter facts: {e}", file=sys.stderr)
            return 2
        ok, drift = verify_top_p(live=True, live_facts=facts, config=cfg)

    print("-" * 88)
    if ok:
        print("top_p verification: OK — live API consistent with recorded provenance ✓"
              if not args.offline else "top_p provenance: OK — config and table consistent ✓ (offline; no live fetch)")
        return 0
    print(f"top_p verification: DRIFT DETECTED ({len(drift)} item(s)) — do NOT start a run:")
    for d in drift:
        print(f"  - {d}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
