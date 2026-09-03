"""Load TUP vignettes (the Patient Agent's symptom-only openers) + their metadata.

A vignette lives in two files (see ``vignettes/VIGNETTE_SPEC.md``):
  - ``vignettes/NNN_slug.md``            — the first-person symptom text, VERBATIM (no frontmatter);
                                            this is the opener AND the judge's clinical scenario.
  - ``vignettes/provenance/NNN_slug.md`` — YAML frontmatter (condition, source, flags, status) + the
                                            external gold-standard dossier. The per-vignette dossier
                                            is never injected into any agent; the judge receives
                                            only the fixed constant gold stated in its rubric.
Provenance frontmatter may carry ``patient_background`` — the patient's source-anchored
answer bank. It is injected only into the patient's prompt (the advisor and judge prompts never
carry it); the patient may of course tell the advisor these facts when asked — that is what an
answer bank is for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tup.data.frontmatter import split_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]
VIGNETTES_DIR = REPO_ROOT / "vignettes"
_NAME_RE = re.compile(r"^(\d{3})_(.+)\.md$")


@dataclass(frozen=True)
class Vignette:
    id: str            # "001"
    slug: str          # "asthma"
    condition: str     # "Acute asthma exacerbation"
    text: str          # the first-person symptom opener, verbatim
    source_key: str    # references.bib key, e.g. "chatgpthealth2026triage"
    psychiatric: bool
    self_harm: bool
    review_status: str  # e.g. "locked"
    patient_background: tuple[str, ...] = ()   # source-anchored background facts (the answer bank)


def _vdir(root: Path | None) -> Path:
    """The vignettes directory — the repo's, or an instrument snapshot's (mirrors the repo layout)."""
    return root / "vignettes" if root is not None else VIGNETTES_DIR


def _load_one(md_path: Path, vdir: Path = VIGNETTES_DIR) -> Vignette:
    m = _NAME_RE.match(md_path.name)
    if not m:
        raise ValueError(f"not a vignette filename: {md_path.name}")
    vid, slug = m.group(1), m.group(2)
    prov = vdir / "provenance" / md_path.name
    fm, _ = split_frontmatter(prov.read_text()) if prov.exists() else ({}, "")
    return Vignette(
        id=vid,
        slug=slug,
        condition=str(fm.get("condition", "")),
        text=md_path.read_text().strip(),
        source_key=str(fm.get("source_key", "")),
        psychiatric=bool(fm.get("psychiatric", False)),
        self_harm=bool(fm.get("self_harm", False)),
        review_status=str(fm.get("review_status", "")),
        patient_background=tuple(fm.get("patient_background") or ()),
    )


def load_vignettes(
    cohort: str | None = None,
    require_locked: bool = True,
    exclude_mh: bool = True,
    root: Path | None = None,
) -> list[Vignette]:
    """Load all vignettes matching the filters, sorted by id.

    Defaults match the reported experiment: every locked vignette across both cohorts (the
    locked 14), no mental-health vignettes. ``cohort`` narrows to one cohort ("pilot" = 001-006,
    "expansion" = 007-014) and is deliberately NOT defaulted — a defaulted cohort once silently
    ran a subset of the grid. ``root`` reads from a run's instrument snapshot instead of
    the repo, so a past run's vignettes stay loadable after the repo's move on.
    """
    vdir = _vdir(root)
    out: list[Vignette] = []
    for md in sorted(vdir.glob("[0-9][0-9][0-9]_*.md")):
        prov = vdir / "provenance" / md.name
        fm, _ = split_frontmatter(prov.read_text()) if prov.exists() else ({}, "")
        if cohort and str(fm.get("cohort", "")) != cohort:
            continue
        v = _load_one(md, vdir)
        if require_locked and v.review_status != "locked":
            continue
        if exclude_mh and (v.psychiatric or v.self_harm):
            continue
        out.append(v)
    return out


def load_vignette(vignette_id: str, root: Path | None = None) -> Vignette:
    """Load a single vignette by id (e.g. "001"), ignoring cohort/status filters."""
    vdir = _vdir(root)
    matches = list(vdir.glob(f"{vignette_id}_*.md"))
    if not matches:
        raise FileNotFoundError(f"no vignette file for id {vignette_id!r} in {vdir}")
    return _load_one(matches[0], vdir)
