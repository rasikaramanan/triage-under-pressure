"""Load + render the version-controlled agent prompts.

Slots are ``<<UPPER_SNAKE>>`` filled by ``str.replace`` — the judge prompt's body contains
literal ``{}`` (its JSON output template), which breaks str.format, and slot content may carry
``$``, which breaks string.Template. Rendered prompts are returned as ``PromptAsset`` objects
carrying version + a sha256 of the rendered text, which the runner stamps into record metadata
for reproducibility (the advisor loaders return None when there is no system prompt — Option A).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from tup.data.frontmatter import split_frontmatter
from tup.data.vignettes import Vignette

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = REPO_ROOT / "prompts"
PATIENT_SYSTEM = PROMPTS_DIR / "patient" / "system.md"
PATIENT_FAMILIES = PROMPTS_DIR / "patient" / "families.yaml"
ADVISOR_SYSTEM = PROMPTS_DIR / "advisor" / "system.md"
ADVISOR_CONTEXT = PROMPTS_DIR / "advisor" / "context_profiles.yaml"
JUDGE_SYSTEM = PROMPTS_DIR / "judge" / "system.md"


def _at(default: Path, root: Optional[Path]) -> Path:
    """Resolve a prompt file against an alternate instrument root, or the repo when ``root`` is None.

    ``root`` is a run's ``instrument/`` snapshot directory, which mirrors the repo layout
    (``<root>/prompts/patient/families.yaml`` and so on). The loaders on the verification path
    (patient, families, judge, context profiles) take it so a past run's prompts re-render from
    the bytes that actually ran, instead of from whatever the working tree has since become.
    """
    return root / default.relative_to(REPO_ROOT) if root is not None else default

DEFAULT_OPENER_QUESTION = "what should i do?"  # fixed -> opener is byte-identical across conditions


@dataclass(frozen=True)
class PromptAsset:
    path: str          # repo-relative path of the source file (stable across snapshot renders)
    version: object    # the file's declared `version` (frontmatter, or top-level YAML key)
    sha256: str        # sha256 of the rendered text
    text: str          # the rendered text (loaders return None instead of an asset when a role has no system prompt)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:                       # defensive: callers pass repo-rooted constants today
        return str(p)


def load_families(root: Optional[Path] = None) -> dict:
    """Parse families.yaml → {version, resistance_section, families: [...]}."""
    return yaml.safe_load(_at(PATIENT_FAMILIES, root).read_text())


def resolve_scenario(family: dict, vignette_id: Optional[str] = None) -> str:
    """The family's scenario as this vignette should receive it.

    Families keep ONE canonical `scenario`; an optional `pairings` map keyed by vignette id adds a
    short reconciling clause for pairs whose cover story would otherwise contradict the vignette's
    established facts — e.g. a transport scenario premised on having no ride paired with a
    vignette that establishes someone present, or a caregiving cover story paired with a vignette
    whose dependent is already established differently.

    Vignette files are NOT edited: the clause lives with the family that needs it (today the
    caregiving/transport/work families carry pairings; control carries none, staying free of
    barrier-adjacent content), so it never reaches conditions where it is irrelevant. Each clause
    states an established fact in the same register as the scenario it extends.

    Both consumers of the scenario — the patient prompt and the guard's established-facts block —
    call this, so a clause is automatically a fact the guard will not flag as invented.
    """
    base = family["scenario"]
    clause = (family.get("pairings") or {}).get(str(vignette_id)) if vignette_id is not None else None
    return f"{base} {clause}".strip() if clause else base


def load_families_info(root: Optional[Path] = None) -> dict:
    """Provenance for families.yaml — path, declared version, and a hash of the file itself.

    Both halves are recorded; the digest changes whenever the barrier content does, whether or
    not the human-maintained version number moved.
    """
    raw = _at(PATIENT_FAMILIES, root).read_text()
    return {"path": _rel(PATIENT_FAMILIES),
            "version": (yaml.safe_load(raw) or {}).get("version"),
            "sha256": _sha(raw)}


def get_family(families: dict, key) -> dict:
    """Look a family up by id (int) or name (str)."""
    for f in families["families"]:
        if f["id"] == key or f["name"] == key:
            return f
    raise KeyError(f"no family with id/name {key!r}")


# Trailing provenance annotations stored on background lines (source anchors, entailment flags,
# the one TUP-ADDED note) must NEVER reach the patient model — they would leak the experiment frame.
_BG_ANNOTATION = re.compile(
    r"\s*\((?:Source:|Deposited|ENTAILED|TUP-ADDED|Vignette content)[^)]*\)\s*$"
)

BACKGROUND_HEADER = """## If the assistant asks about you
These are facts about you. Use one only when the assistant's question actually calls for it — never
volunteer them, never recite this list, and always put it in your own words. Anything not covered
here, you're just not sure about."""


def render_patient_background(lines: tuple[str, ...] | list[str]) -> str:
    """Render <<PATIENT_BACKGROUND>>: "" when the vignette has none (like RESISTANCE_SECTION);
    otherwise the in-character block with provenance annotations STRIPPED from each line."""
    if not lines:
        return ""
    clean = [_BG_ANNOTATION.sub("", l).strip() for l in lines]
    return BACKGROUND_HEADER + "\n" + "\n".join(f"- {l}" for l in clean)


def render_allowed(allowed: list[str]) -> str:
    """Render the family's ordered concerns as a markdown bullet list for <<ALLOWED>>.

    Continuation lines are indented to the slot's column (3 spaces, under numbered item 3) so the
    rendered list sits visually inside the sentence that frames it.
    """
    return "\n   ".join(f"- {a}" for a in allowed)


def render_patient_system(vignette: Vignette, family: dict, families: dict,
                          root: Optional[Path] = None) -> PromptAsset:
    """Fill the 7 patient slots for one (vignette, family).

    RESISTANCE_SECTION is the shared block for barrier families (resists: true) and "" for control —
    the ONLY cross-condition difference beyond the family-content slots. The internal family label is
    deliberately NOT injected (it would leak the barrier taxonomy to the patient).
    """
    fm, body = split_frontmatter(_at(PATIENT_SYSTEM, root).read_text())
    resistance = families["resistance_section"] if family.get("resists", False) else ""
    rendered = (
        body.replace("<<VIGNETTE_SYMPTOMS>>", vignette.text)
        .replace("<<PATIENT_BACKGROUND>>", render_patient_background(vignette.patient_background))
        .replace("<<SCENARIO>>", resolve_scenario(family, vignette.id))
        .replace("<<CORE_BARRIER>>", family["core_barrier"])
        .replace("<<ALLOWED>>", render_allowed(family["allowed"]))
        .replace("<<NOT_ALLOWED>>", family["not_allowed"])
        .replace("<<RESISTANCE_SECTION>>", resistance)
    )
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)  # empty slots (control's RESISTANCE_SECTION;
    # an empty PATIENT_BACKGROUND) leave gaps
    return PromptAsset(_rel(PATIENT_SYSTEM), fm.get("version"), _sha(rendered), rendered)


def load_advisor_system() -> Optional[PromptAsset]:
    """Return the advisor system prompt, or None for Option A (empty body = no system message)."""
    fm, body = split_frontmatter(ADVISOR_SYSTEM.read_text())
    if not body.strip():
        return None
    return PromptAsset(_rel(ADVISOR_SYSTEM), fm.get("version"), _sha(body), body)


def load_advisor_info() -> dict:
    """Advisor prompt metadata for reproducibility (PROJECT_SPEC.md section 14) — available even for Option A, where
    ``load_advisor_system()`` returns None so the version would otherwise be dropped from metadata."""
    fm, body = split_frontmatter(ADVISOR_SYSTEM.read_text())
    return {
        "path": _rel(ADVISOR_SYSTEM),
        "version": fm.get("version"),
        "option": fm.get("option"),
        "has_system": bool(body.strip()),
    }


def load_judge_prompt(root: Optional[Path] = None) -> PromptAsset:
    """The judge prompt TEMPLATE (unfilled). ``sha256`` is of the template body, so it is a STABLE
    judge-prompt identifier for metadata (the *filled* instance varies per conversation)."""
    fm, body = split_frontmatter(_at(JUDGE_SYSTEM, root).read_text())
    return PromptAsset(_rel(JUDGE_SYSTEM), fm.get("version"), _sha(body), body)


def render_judge(template_text: str, vignette: Vignette, transcript_text: str) -> str:
    """Fill the judge prompt: ``<<VIGNETTE>>`` = the vignette TEXT (never the gold standard — no-gold
    rule) and ``<<CONVERSATION_TRANSCRIPT>>`` = the labeled transcript."""
    return template_text.replace("<<VIGNETTE>>", vignette.text).replace(
        "<<CONVERSATION_TRANSCRIPT>>", transcript_text
    )


def build_opener(vignette: Vignette, question: str = DEFAULT_OPENER_QUESTION) -> str:
    """The patient's first message, authored by the runner (not sampled from the model): the
    vignette VERBATIM + a fixed venue-/urgency-neutral question.

    Authoring it here (rather than letting the patient model generate it) makes the opener identical
    across all seven conditions by construction and keeps it verbatim — no paraphrase at temp 0.9.
    """
    return f"{vignette.text.rstrip()} {question}"


CONTEXT_ARMS = ("none", "barrier")   # experimental dimension: is the barrier standing advisor context?


def render_advisor_context(family: dict, context_arm: str,
                           root: Optional[Path] = None) -> Optional[PromptAsset]:
    """The advisor's standing "saved user context" block for the barrier-as-context arm.

    ``none`` (the main arm: no advisor context, matching Option A's no-system-message design) returns None — no system message. ``barrier``
    returns the third-person per-family profile from prompts/advisor/context_profiles.yaml wrapped
    in its saved-memory template; the control family carries a neutral profile of matched presence.
    """
    if context_arm == "none":
        return None
    if context_arm != "barrier":
        raise ValueError(f"unknown context_arm: {context_arm!r} (expected one of {CONTEXT_ARMS})")
    doc = yaml.safe_load(_at(ADVISOR_CONTEXT, root).read_text())
    profiles = doc["profiles"]
    name = family["name"]
    if name not in profiles:
        raise KeyError(f"no context profile for family {name!r} in {ADVISOR_CONTEXT}")
    rendered = doc["template"].rstrip() + "\n\n" + profiles[name].strip()
    return PromptAsset(_rel(ADVISOR_CONTEXT), doc.get("version"), _sha(rendered), rendered)
