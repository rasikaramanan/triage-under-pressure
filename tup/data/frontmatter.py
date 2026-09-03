"""YAML-frontmatter splitter shared by the vignette + prompt loaders.

TUP prompt/provenance files are ``---\\n<yaml>\\n---\\n<body>``. We split on the fence *lines*
(a line that is exactly ``---``), NOT on the bare substring ``---`` — otherwise a ``---`` inside a
YAML scalar (e.g. a page range ``"pp. 26---29"``) or a ``---`` rule inside the body would corrupt the
parse. Only the first exact ``---`` line after the opening fence closes the frontmatter, so any later
``---`` (e.g. a markdown horizontal rule in the body) is preserved verbatim.
"""
from __future__ import annotations

import yaml


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body). No/!malformed frontmatter -> ({}, raw)."""
    if not (raw.startswith("---\n") or raw.startswith("---\r\n")):
        return {}, raw
    lines = raw.splitlines(keepends=True)  # lines[0] is the opening fence
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":  # first exact fence line closes the frontmatter
            fm = yaml.safe_load("".join(lines[1:i])) or {}
            body = "".join(lines[i + 1 :]).lstrip("\n")
            return fm, body
    return {}, raw  # no closing fence -> treat the whole thing as body
