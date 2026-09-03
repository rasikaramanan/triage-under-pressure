"""requirements.txt must agree with what the code actually imports, in BOTH directions: a
dependency imported without a line there fails this test, and a line there that nothing imports
fails it too.

Deliberately NOT checked: installed versions. The floors in requirements.txt are provenance for
the reported run, and asserting them would make the suite fail on a legitimately newer env.
(The LOCK's pins are checked, though -- see the requirements.lock coherence test below: the
lock file, not the environment, must stay consistent with the declared floors.)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED = ("tup", "scripts")

# Import name -> the distribution name that provides it, where they differ.
DISTRIBUTION_OF = {
    "dotenv": "python-dotenv",
    "yaml": "pyyaml",
}

# Declared for a purpose other than being imported. Keep this list short and justified.
NOT_IMPORTED_BY_DESIGN = {
}


def _local_module_names() -> set[str]:
    """Modules importable as siblings because a script inserted its own directory on sys.path.

    Derived from the tree rather than listed, so a new script under scripts/ does not have to be
    registered here to avoid being mistaken for a third-party package.
    """
    names = {p.stem for root in SCANNED for p in (REPO_ROOT / root).rglob("*.py")}
    names |= {p.name for root in SCANNED for p in (REPO_ROOT / root).rglob("*")
              if p.is_dir() and (p / "__init__.py").exists()}
    return names | set(SCANNED)


def _guarded_import_nodes(tree: ast.AST) -> set[int]:
    """ids of import nodes sitting inside a try block -- i.e. optional by construction."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for stmt in node.body:
            for inner in ast.walk(stmt):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    guarded.add(id(inner))
    return guarded


def _imported_top_level_modules() -> dict[str, set[str]]:
    """{module_name: {files that import it}} for every hard (non-optional) third-party import."""
    stdlib = set(sys.stdlib_module_names)
    local = _local_module_names()
    found: dict[str, set[str]] = {}

    for root in SCANNED:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded = _guarded_import_nodes(tree)
            for node in ast.walk(tree):
                if id(node) in guarded:
                    continue
                if isinstance(node, ast.Import):
                    mods = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # A relative import (level > 0) is first-party by definition.
                    mods = [(node.module or "").split(".")[0]] if node.level == 0 else []
                else:
                    continue
                for mod in mods:
                    if not mod or mod in stdlib or mod in local:
                        continue
                    found.setdefault(mod, set()).add(str(path.relative_to(REPO_ROOT)))
    return found


def _declared_requirements() -> set[str]:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for sep in (">=", "==", "~=", "!=", "<=", ">", "<", "["):
            line = line.split(sep, 1)[0]
        names.add(line.strip().lower())
    return names


def test_every_import_is_declared():
    """No module may import a third-party package requirements.txt does not name."""
    declared = _declared_requirements()
    missing = {}
    for module, files in sorted(_imported_top_level_modules().items()):
        dist = DISTRIBUTION_OF.get(module, module).lower()
        if dist not in declared:
            missing[dist] = sorted(files)[:3]
    assert not missing, (
        "imported but not declared in requirements.txt: "
        + "; ".join(f"{d} (e.g. {', '.join(f)})" for d, f in missing.items())
        + "\nAdd it to requirements.txt, or -- if it is genuinely optional -- move the import "
          "inside a try/except with a documented fallback."
    )


def test_every_requirement_is_imported():
    """No line may sit in requirements.txt that nothing imports."""
    imported = {DISTRIBUTION_OF.get(m, m).lower() for m in _imported_top_level_modules()}
    unused = _declared_requirements() - imported - set(NOT_IMPORTED_BY_DESIGN)
    assert not unused, (
        f"declared in requirements.txt but never imported: {sorted(unused)}\n"
        "Remove the line, or record why it is needed in NOT_IMPORTED_BY_DESIGN in this file."
    )


def _declared_with_floors() -> dict[str, str | None]:
    """{normalized name: declared floor or None} for every active line in requirements.txt."""
    out: dict[str, str | None] = {}
    for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        floor = line.split(">=", 1)[1].strip() if ">=" in line else None
        name = line
        for sep in (">=", "==", "~=", "!=", "<=", ">", "<", "["):
            name = name.split(sep, 1)[0]
        out[name.strip().lower().replace("_", "-")] = floor
    return out


def _lock_pins() -> dict[str, str]:
    """{normalized name: pinned version} from requirements.lock.

    The lock lives at the repo root in the released tree; the fallback location is where the
    source tree that produces a release stages it, and never exists in the released tree itself.
    Its absence anywhere is a FAILURE, not
    a skip: the reproduce docs promise byte-exact tier-1 reproduction under this file, so a tree
    without it has broken that promise silently.
    """
    for candidate in (REPO_ROOT / "requirements.lock",
                      REPO_ROOT / "export" / "overlay" / "requirements.lock"):
        if candidate.is_file():
            pins: dict[str, str] = {}
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or "==" not in line:
                    continue
                name, ver = line.split("==", 1)
                pins[name.strip().lower().replace("_", "-")] = ver.strip()
            return pins
    raise AssertionError(
        "requirements.lock not found at the repo root or export/overlay/ -- REPRODUCE.md "
        "promises byte-exact reproduction under it, so the file must exist."
    )


def _ver(v: str) -> tuple[int, ...]:
    """Dotted-numeric compare key -- deliberately NOT `packaging` (importing it here would make
    the bidirectional import check above demand it in requirements.txt). Each dot component
    contributes its leading digits; a component with none (e.g. 'post0') contributes 0, which is
    exact enough for floor checks over plain X.Y[.Z] versions."""
    import re
    parts = []
    for comp in v.split("."):
        m = re.match(r"\d+", comp)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def test_lock_pins_every_declared_requirement_at_or_above_its_floor():
    """requirements.txt and requirements.lock must not drift apart.

    The lock is the env-of-record resolution of the declared set: every declared package must
    appear in it, pinned at a version satisfying the declared floor. A new direct dependency, or
    a floor raised past the lock's pin, fails here instead of leaving the lock silently stale.
    """
    pins = _lock_pins()
    problems = []
    for name, floor in sorted(_declared_with_floors().items()):
        if name not in pins:
            problems.append(f"{name}: declared in requirements.txt but absent from requirements.lock "
                            f"-- re-resolve the lock")
        elif floor is not None and _ver(pins[name]) < _ver(floor):
            problems.append(f"{name}: locked at {pins[name]}, below the declared floor >={floor} "
                            f"-- re-resolve the lock (or lower the floor deliberately)")
    assert not problems, "requirements.txt vs requirements.lock drift:\n  " + "\n  ".join(problems)
