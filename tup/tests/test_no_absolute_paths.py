"""No source file may hard-code a path outside the repo, and no module may build a data path.

A path constant is invisible until someone else runs the code, so review alone cannot catch
it — it has to be a test.

SCOPE IS ``.py`` ONLY, DELIBERATELY. Records under ``results/`` are frozen data — captured
tracebacks and manifests record whatever paths a run actually executed under, and rewriting
them would falsify the run's own provenance. Scoping to source keeps the invariant enforceable
forever: code must never hard-code a path outside the repo, while data honestly records its
history.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"__pycache__", ".git", ".claude", "scratchpad", "results", "node_modules", ".venv"}

#: Any absolute path into a real user's home or machine.
_ABSOLUTE_HOME = re.compile(r"[\"'](/Users/|/home/|/mnt/[a-z]/|C:\\\\)")

#: A module building its own data path instead of asking the store. The store itself is exempt —
#: it is the one module whose job this is.
_SELF_BUILT_DATA_PATH = re.compile(
    r"""(REPO_ROOT|ROOT|repo_root)\s*/\s*["'](runs|results|dry_runs|studies)["']"""
)

_EXEMPT = {
    "tup/store.py",                     # the single owner of data paths
    "tup/tests/test_no_absolute_paths.py",
    "tup/tests/test_store.py",          # asserts the layout the store produces
}
#: a module whose job is naming pre-store paths opts out with this marker in its header
_EXEMPT_MARKER = "# path-rule-exempt:"


def _sources():
    for p in sorted(REPO_ROOT.rglob("*.py")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if set(p.relative_to(REPO_ROOT).parts) & SKIP_DIRS or rel in _EXEMPT:
            continue
        text = p.read_text(encoding="utf-8")
        if _EXEMPT_MARKER in "\n".join(text.splitlines()[:40]):
            continue
        yield rel, text


def test_no_source_file_hardcodes_an_absolute_machine_path():
    bad = []
    for rel, text in _sources():
        for i, line in enumerate(text.splitlines(), 1):
            if _ABSOLUTE_HOME.search(line) and "noqa: abspath" not in line:
                bad.append(f"{rel}:{i}: {line.strip()[:110]}")
    assert not bad, "absolute machine paths in source:\n  " + "\n  ".join(bad)


def test_no_module_builds_its_own_data_path():
    """The defect class the store closes: a second authority on where data lives."""
    bad = []
    for rel, text in _sources():
        for i, line in enumerate(text.splitlines(), 1):
            if _SELF_BUILT_DATA_PATH.search(line):
                bad.append(f"{rel}:{i}: {line.strip()[:110]}")
    assert not bad, ("these build a data path instead of going through tup.store:\n  "
                     + "\n  ".join(bad))


def test_the_launcher_exposes_no_redirect_or_truncate_flags():
    """The launcher must expose no flag that redirects data (``--out``, ``--cache-dir`` — one
    redirected invocation can send a run's results into a different checkout), truncates
    (``--no-resume``, ``--limit``), or contradicts arm-derived context (``--context-arm``)."""
    cli = (REPO_ROOT / "scripts" / "run_experiment.py").read_text(encoding="utf-8")
    for banned in ('"--out"', '"--cache-dir"', '"--no-resume"', '"--context-arm"', '"--limit"'):
        assert banned not in cli, f"{banned} must not exist in the launcher"


def test_the_store_cannot_truncate_or_delete():
    """A store that can overwrite a run is not a store."""
    from tup import store
    for attr in ("truncate", "delete", "reset", "rm", "clear", "wipe"):
        assert not hasattr(store.Store, attr)
        assert not hasattr(store.RunDir, attr)
        assert not hasattr(store.ArmDir, attr)
