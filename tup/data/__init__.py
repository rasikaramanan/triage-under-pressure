"""Data layer: load vignettes + render version-controlled agent prompts."""
from tup.data.prompts import (
    PromptAsset,
    build_opener,
    get_family,
    load_advisor_info,
    load_advisor_system,
    load_families,
    load_judge_prompt,
    render_allowed,
    render_judge,
    render_patient_system,
)
from tup.data.vignettes import Vignette, load_vignette, load_vignettes

__all__ = [
    "Vignette",
    "load_vignette",
    "load_vignettes",
    "PromptAsset",
    "load_families",
    "get_family",
    "render_patient_system",
    "render_allowed",
    "load_advisor_system",
    "load_advisor_info",
    "load_judge_prompt",
    "render_judge",
    "build_opener",
]
