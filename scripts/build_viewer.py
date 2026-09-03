"""Build the self-contained HTML run explorer.

    python scripts/build_viewer.py                     # every non-archived run in the store -> analysis/viewer/
    python scripts/build_viewer.py --results-root /tmp/somewhere

Always writes a self-contained HTML file (open by double-click; embeds all run data inline) into the
store's ``analysis/viewer/`` — the viewer is a REBUILDABLE ARTIFACT, so it lives under
``analysis/`` with the stats and never at the repo root, where a generated file reads as source.

If a run is detected to be ACTIVELY WRITING (any arm's records.jsonl modified in the last few
minutes), it then AUTOMATICALLY starts a tiny local server and opens it — so the dropdown reflects
the store live and a browser refresh shows the latest, with no rebuild. No flag needed; pass
--no-serve to suppress (e.g. in scripts).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path when run directly

from tup.output.html_viewer import build, build_payload, detect_live_run, serve
from tup.store import ENV_ROOT, Store


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the TUP HTML run explorer.")
    ap.add_argument("--results-root", default=None,
                    help=f"results store root (default: ${ENV_ROOT}, else <repo>/results). There is "
                         f"deliberately no --out: the store owns where the viewer is written.")
    ap.add_argument("--runs", default=None,
                    help="comma-separated run/study ids to embed (default: everything except the "
                         "validation smokes and superseded/invalid runs). Pass ids to build a "
                         "small, focused viewer.")
    ap.add_argument("--include-smokes", action="store_true",
                    help="also embed the validation smokes (large)")
    ap.add_argument("--include-archived", action="store_true",
                    help="also embed runs the store marks SUPERSEDED or INVALID. Excluded by "
                         "default: they are exactly the runs a reader must not quote, and a "
                         "superseded run can dominate the page.")
    ap.add_argument("--no-serve", action="store_true",
                    help="never auto-serve, even if a live run is detected (just write the static file)")
    ap.add_argument("--serve", action="store_true",
                    help="serve unconditionally (not just when a live run is detected). Required for "
                         "the human audit: verdict recording needs the local server's POST endpoint — "
                         "the static file can only queue verdicts in the browser.")
    args = ap.parse_args()

    store = Store(args.results_root) if args.results_root else Store.from_env()
    run_ids = [x.strip() for x in args.runs.split(",") if x.strip()] if args.runs else None
    if run_ids:
        known = set(store.list_runs()) | set(store.list_studies())
        unknown = [r for r in run_ids if r not in known]
        if unknown:
            print(f"error: unknown id(s) {unknown}; the store holds {sorted(known)}", file=sys.stderr)
            return 2
    sel = {"run_ids": run_ids, "include_smokes": args.include_smokes,
           "include_archived": args.include_archived}
    skipped: list = []
    payload = build_payload(store, **sel, skipped=skipped)
    runs = payload["runs"]
    if not runs:
        print(f"warning: the store at {store.root} holds no records — the viewer's dropdown will be "
              f"empty. Set {ENV_ROOT} or pass --results-root if the data is elsewhere.", file=sys.stderr)
    out = build(store, **sel)
    total = sum(r["n"] for r in runs.values())
    mb = out.stat().st_size / 1048576
    print(f"built {out}  ({len(runs)} arm(s), {total} conversation(s), {mb:.1f} MB)")
    for name, r in sorted(runs.items()):
        print(f"  - {name}: {r['n']} conversations")
    # never truncate silently: say what was left out and how to get it back
    for run_id, why in skipped:
        flag = "--include-smokes" if why == "validation smoke" else "--include-archived"
        print(f"  · skipped {run_id} ({why}) — add it with {flag} or --runs {run_id}")

    # Auto-serve when a run is in flight (a snapshot would go stale) — but ONLY when someone is
    # actually watching. Any arm written in the last few minutes looks "live", and running this
    # straight after a run must not block forever on a server nobody asked for. A pipe, a CI step
    # or a script gets the file and exits.
    interactive = sys.stdout.isatty()
    if args.serve and not args.no_serve:
        print("\n● serving (--serve) — the human-audit verdict recorder is available on this server")
        serve(store, **sel)
        return 0
    live = None if args.no_serve else (detect_live_run(store) if interactive else None)
    if live is None and not args.no_serve and not interactive and detect_live_run(store):
        print("note: a run looks live, but stdout is not a terminal — wrote the static file and "
              "exited instead of serving. Run this in a terminal (or use --serve) to watch it live.")
    if live:
        name, age = live
        print(f"\n● live run detected ({name}, last write {age:.0f}s ago) — starting local server")
        serve(store, **sel)
    else:
        print("open it by double-click (or: open " + str(out) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
