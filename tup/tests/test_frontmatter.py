"""split_frontmatter — fence-line anchoring + the edge cases the loaders depend on."""
from __future__ import annotations

from tup.data.frontmatter import split_frontmatter


def test_normal_split():
    fm, body = split_frontmatter("---\nk: v\n---\nbody text\n")
    assert fm == {"k": "v"}
    assert body == "body text\n"


def test_no_frontmatter():
    assert split_frontmatter("plain body") == ({}, "plain body")


def test_body_horizontal_rule_is_preserved():
    fm, body = split_frontmatter("---\nk: v\n---\nbefore\n---\nafter\n")
    assert fm == {"k": "v"}
    assert "before" in body and "after" in body and "---" in body  # body '---' survives (fence-line exactness)


def test_triple_dash_inside_yaml_scalar_does_not_corrupt():
    raw = '---\nsource: "pp. 26---29"\nk: v\n---\nbody\n'
    fm, body = split_frontmatter(raw)
    assert fm == {"source": "pp. 26---29", "k": "v"}  # the in-scalar '---' is not a fence
    assert body == "body\n"


def test_empty_frontmatter_block():
    fm, body = split_frontmatter("---\n---\nbody\n")
    assert fm == {} and body == "body\n"


def test_no_closing_fence_is_all_body():
    raw = "---\nlooks like frontmatter\nbut never closes"
    assert split_frontmatter(raw) == ({}, raw)
