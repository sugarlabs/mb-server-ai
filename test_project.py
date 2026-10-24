"""Tests for project.py against the example projects in a Music Blocks checkout.

Set MUSICBLOCKS to the checkout, default ../musicblocks from this file.
"""

import json
import os
from pathlib import Path

import pytest

from project import (
    ProjectError,
    build_project,
    check_tree,
    compress_melodies,
    expand_melodies,
    load_specs,
    parse_project_text,
    read_tree,
    render_tree,
)

CHECKOUT = Path(os.environ.get("MUSICBLOCKS", Path(__file__).parents[1] / "musicblocks"))
EXAMPLES = sorted(
    path for path in (CHECKOUT / "examples").glob("*") if path.suffix in (".html", ".tb")
)
SPECS = load_specs()


def _buildable(stacks: list) -> list:
    """Drop stacks the builder cannot take: unknown blocks and loose values."""

    def ok(stack: list) -> bool:
        def walk(nodes):
            for node in nodes:
                if node.get("unknown") or node["block"].startswith("("):
                    return False
                if not all(walk(clamp) for clamp in node.get("clamps", [])):
                    return False
            return True

        return walk(stack)

    return [stack for stack in stacks if stack and ok(stack)]


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.name for path in EXAMPLES])
def test_examples_round_trip(path: Path) -> None:
    blocks = parse_project_text(path.read_text(encoding="utf-8"))
    stacks = _buildable(read_tree(blocks, SPECS))
    if not stacks:
        pytest.skip("no buildable stacks")
    rebuilt = build_project(stacks, SPECS)
    assert read_tree(rebuilt, SPECS) == stacks
    assert render_tree(stacks, SPECS)


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.name for path in EXAMPLES])
def test_examples_survive_melody_shorthand(path: Path) -> None:
    stacks = read_tree(parse_project_text(path.read_text(encoding="utf-8")), SPECS)
    back = [expand_melodies(compress_melodies(stack)) for stack in stacks]
    # Hot-Cross-Buns writes "fa#" where the others write "fa♯". Music Blocks
    # reads both, and the shorthand always gives the second.
    def same(tree):
        return json.dumps(tree, ensure_ascii=False).replace("#", "♯")

    assert same(back) == same(stacks)


def test_melody_expands_to_notes() -> None:
    stacks = [expand_melodies([{"block": "melody", "notes": "E5 1/16, D#5 1/16, rest 1/8, sol4 1/4, Bb3 3/8"}])]
    assert render_tree(stacks, SPECS).splitlines() == [
        "note value (1 / 16)", "  pitch name E, octave 5",
        "note value (1 / 16)", "  pitch name D♯, octave 5",
        "note value (1 / 8)", "  silence",
        "note value (1 / 4)", "  pitch name sol, octave 4",
        "note value (3 / 8)", "  pitch name B♭, octave 3",
    ]
    assert build_project([[{"block": "start", "clamps": stacks}]], SPECS)


def test_expand_tidies_common_shape_slips() -> None:
    note = {"block": "melody", "notes": "C4 1/4"}
    # A clamp as one statement, and a clamp as a flat list of statements.
    one = expand_melodies({"block": "start", "clamps": note})
    flat = expand_melodies([{"block": "start", "clamps": [note, note]}])
    assert len(one[0]["clamps"]) == 1 and one[0]["clamps"][0][0]["block"] == "newnote"
    assert len(flat[0]["clamps"]) == 1 and len(flat[0]["clamps"][0]) == 2
    assert build_project([one, flat], SPECS)


@pytest.mark.parametrize("notes", ["E5", "H4 1/4", "E5 quarter", "do 1/4"])
def test_melody_rejects_bad_notes(notes: str) -> None:
    with pytest.raises(ProjectError):
        expand_melodies([{"block": "melody", "notes": notes}])


def test_check_finds_common_mistakes() -> None:
    stacks = [
        [{"block": "action", "args": [{"block": "text", "value": "chorus"}], "clamps": [[]]}],
        [{"block": "newnote", "args": [{"block": "divide", "args": [1, 4]}], "clamps": [[]]}],
    ]
    problems = check_tree(stacks, SPECS)
    assert any("no start block" in problem for problem in problems)
    assert any("never runs" in problem for problem in problems)
    assert any("silent" in problem for problem in problems)
    assert any('"chorus" is defined but never used' in problem for problem in problems)


def test_build_rejects_unknown_block() -> None:
    with pytest.raises(ProjectError):
        build_project([[{"block": "start", "clamps": [[{"block": "notablock"}]]}]], SPECS)


def test_build_adds_hidden_after_note() -> None:
    stacks = [[{
        "block": "start",
        "clamps": [[{
            "block": "newnote",
            "args": [{"block": "divide", "args": [1, 4]}],
            "clamps": [[{"block": "pitch", "args": [{"block": "solfege", "value": "do"}, 4]}]],
        }]],
    }]]
    blocks = build_project(stacks, SPECS)
    names = [entry[1] if isinstance(entry[1], str) else entry[1][0] for entry in blocks]
    assert "hidden" in names
    assert check_tree(read_tree(blocks, SPECS), SPECS) == []
