"""Making and changing Music Blocks projects, for the debugger's "Fix it for
me" and "Make a new project", and the reference text every prompt is grounded in.

The model writes a block tree as JSON and project.py turns it into Music
Blocks' save format, so the model never writes that format itself.
"""

import json
import sys

from bedrock import Model, ModelError
from knowledge import Document, Knowledge
from project import (
    LAYOUT_BLOCKS,
    BlockSpec,
    ProjectError,
    block_names,
    build_project,
    check_tree,
    compress_melodies,
    expand_melodies,
    load_specs,
    parse_project_text,
    read_tree,
    render_tree,
)

MAX_TEXT = 2000
# The JSON tree of a project the debugger may rewrite, about 300 blocks.
MAX_EDIT = 40000
# Blocks that open the AI widgets inside Music Blocks. Their stacks are how the
# child opened the widget, not part of the music, so they are left out of
# descriptions and kept as they are by edits.
WIDGET_BLOCKS = {"aidebugger", "reflection"}


def split_widget_stacks(stacks: list[list[dict]]) -> tuple[list[list[dict]], list[list[dict]]]:
    """The project's own stacks, and the stacks that open AI widgets."""
    own = [stack for stack in stacks if not (stack and stack[0]["block"] in WIDGET_BLOCKS)]
    return own, [stack for stack in stacks if stack and stack[0]["block"] in WIDGET_BLOCKS]


SYSTEM = """You are the Music Blocks assistant from Sugar Labs. The people asking are often
children aged 8 to 14 and their teachers.

- Answer only about Music Blocks, music and programming. If a question is about something
  else, or is unsafe, kindly bring it back to making music.
- Use simple words, short sentences and numbered steps.
- Name blocks exactly as Music Blocks shows them and say which palette they are in.
- Only describe blocks and features found in the reference below. If the reference does not
  cover something, say you are not sure and suggest the Music Blocks guide.
- Never ask for names, ages, schools or any personal information."""


def _reference(documents: list[Document]) -> str:
    return "\n\n".join(
        f"[{index}] {document.title} ({document.kind})\n{document.text}"
        for index, document in enumerate(documents, start=1)
    )


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    return text.strip()[:limit]


def _block_signature(spec: BlockSpec) -> str:
    slots = []
    for index in range(spec.arg_count):
        dock = spec.dock_types[1 + index]
        label = spec.arg_labels[index] if index < len(spec.arg_labels) and spec.arg_labels[index] else ""
        slots.append(f"{label}:{dock}".lstrip(":"))
    kind = "statement" if spec.is_flow else "value"
    clamps = f", clamps={spec.clamp_count}" if spec.clamp_count else ""
    return f"{spec.name} ({spec.label or spec.name}; {kind}; args=[{', '.join(slots)}]{clamps})"


TREE_FORMAT = """Reply with JSON only: {"title": "...", "stacks": [stack, ...]}.

A stack is a list of statements. The first stack starts with a "start" block whose clamp
holds the program. Other stacks are "action" blocks that the program calls with "do".

A statement is {"block": name, "args": [value, ...], "clamps": [[statement, ...], ...]}.
"args" and "clamps" are left out when empty. Use only statement blocks as statements.

A value is a plain number, a plain string for text, {"block": name, "value": v} for pickers
such as solfege, notename and drumname, or {"block": name, "args": [value, ...]} for
operators such as divide and plus.

Example, a quarter note sol in octave 4 and a kick drum, repeated twice:
{"title": "Two beats", "stacks": [[{"block": "start", "clamps": [[
  {"block": "repeat", "args": [2], "clamps": [[
    {"block": "newnote", "args": [{"block": "divide", "args": [1, 4]}], "clamps": [[
      {"block": "pitch", "args": [{"block": "solfege", "value": "sol"}, 4]}]]},
    {"block": "newnote", "args": [{"block": "divide", "args": [1, 4]}], "clamps": [[
      {"block": "playdrum", "args": [{"block": "drumname", "value": "kick drum"}]}]]}
  ]]}
]]}]]}

Example of an action:
[{"block": "action", "args": ["chorus"], "clamps": [[ ...statements... ]]}]
called from the start stack with {"block": "do", "args": ["chorus"]}.

Write a run of single notes as one melody statement, anywhere a statement can go:
{"block": "melody", "notes": "E5 1/16, D#5 1/16, E5 1/16, rest 1/8, sol4 1/4"}
Each note is a pitch and a duration. A pitch is a note name with an optional # or b and an
octave (C4, F#4, Bb3), or solfege and an octave (do4, sol4, fa#4). "rest" is a silence.
Use melody for every tune and keep other blocks for drums, chords and effects. Melody is only a
shorthand: Music Blocks shows it as note blocks, and has no melody block, so to the child always
call it notes or note blocks."""


class Assistant:
    def __init__(self, model: Model | None = None):
        self.specs = load_specs()
        self.knowledge = Knowledge()
        self._model = model

    @property
    def model(self) -> Model:
        # Created on first use, so the server starts and its tests run without a key.
        if self._model is None:
            self._model = Model()
        return self._model

    def block_reference(self, stacks: list[list[dict]], limit: int = 10) -> str:
        """Reference text for the blocks a project uses."""
        names = " ".join(sorted(block_names(stacks)))
        return _reference(self.knowledge.search(names, limit=limit, kinds=("block",)))

    def reference(self, question: str, limit: int = 4) -> str:
        return _reference(self.knowledge.search(_clip(question), limit=limit))

    def make(self, description: str, keep: list[list[dict]] | None = None) -> dict:
        """keep holds stacks to carry over unchanged, such as the AI widget the
        child made the project from."""
        description = _clip(description)
        catalog = "\n".join(
            _block_signature(spec)
            for spec in self.specs.values()
            if spec.beginner and spec.name not in LAYOUT_BLOCKS
        )
        documents = self.knowledge.search(description, limit=6, kinds=("example",))
        system = (
            SYSTEM
            + "\n\nYou write Music Blocks programs as JSON trees.\n\n"
            + TREE_FORMAT
            + "\n\nBlocks you may use (name, label, kind, argument slots):\n"
            + catalog
            + "\n\nSimilar example projects, as block trees:\n"
            + _reference(documents)
        )
        messages = [{"role": "user", "text": f"Make a Music Blocks project: {description}"}]
        reply, project = self._build(system, messages, extra=keep)
        stacks = split_widget_stacks(read_tree(project, self.specs))[0]
        return {
            "title": str(reply.get("title") or "My project"),
            "project": project,
            "tree": render_tree(stacks, self.specs),
            "problems": check_tree(stacks, self.specs),
        }

    def edit(self, project_text: str, request: str) -> dict:
        """Change a project as the child asks, for the AI debugger's "Fix it
        for me". Returns a whole new project to load in place of the old one."""
        stacks, widgets = split_widget_stacks(read_tree(parse_project_text(project_text), self.specs))
        names = block_names(stacks)
        unknown = sorted(name for name in names if name not in self.specs)
        if unknown:
            raise ProjectError(f"It uses blocks I cannot change yet: {', '.join(unknown)}.")
        # Runs of notes go as melody lines, so a long song fits, and the model
        # can keep them short in its answer.
        current = json.dumps([compress_melodies(stack) for stack in stacks])
        if len(current) > MAX_EDIT:
            raise ProjectError("It is too big for me to change automatically.")
        catalog = "\n".join(
            _block_signature(spec)
            for spec in self.specs.values()
            if (spec.beginner or spec.name in names) and spec.name not in LAYOUT_BLOCKS
        )
        system = (
            SYSTEM
            + "\n\nYou change Music Blocks programs given as JSON trees. Keep everything the child "
            "made and change only what their request needs.\n\n"
            # "changes" comes first in the format, since a model asked for it
            # after the stacks left it out 2 times in 3 (22 Oct 2026).
            + TREE_FORMAT.replace(
                '{"title": "...", "stacks": [stack, ...]}', '{"changes": "...", "stacks": [stack, ...]}'
            )
            + '\n\n"changes" is a short Markdown list, for the child, of what you changed and why, '
            "naming the blocks.\n\nBlocks you may use (name, label, kind, argument slots):\n"
            + catalog
            + "\n\nReference:\n"
            + self.block_reference(stacks)
        )
        request = _clip(request) or "Fix the problems in my project."
        messages = [{"role": "user", "text": f"My project as a JSON tree:\n{current}\n\nWhat I want: {request}"}]
        reply, project = self._build(system, messages, extra=widgets)
        new_stacks = split_widget_stacks(read_tree(project, self.specs))[0]
        return {
            "project": project,
            "changes": str(reply.get("changes") or "I changed your project."),
            "tree": render_tree(new_stacks, self.specs),
            "problems": check_tree(new_stacks, self.specs),
        }

    def _build(
        self, system: str, messages: list[dict], extra: list[list[dict]] | None = None
    ) -> tuple[dict, list[list]]:
        """Ask for a block tree and build it, the model's reply and the project.
        Stacks in extra are added unchanged, such as the AI widgets' own stacks."""
        last_error = ""
        for _ in range(2):
            reply = self.model.generate_json(system, messages)
            try:
                if not isinstance(reply, dict):
                    raise ProjectError("The reply must be a JSON object with title and stacks.")
                stacks = reply.get("stacks")
                if isinstance(stacks, list):
                    # Empty stacks, and stray text such as "changes" written
                    # into the list, are dropped rather than failing the build
                    # (21 Oct 2026).
                    stacks = [
                        expand_melodies(stack) for stack in stacks if stack and isinstance(stack, (list, dict))
                    ] + (extra or [])
                return reply, build_project(stacks, self.specs)
            except ProjectError as error:
                # One retry with the exact error, which fixes most slips.
                last_error = str(error)
                print(f"could not build: {error} reply: {json.dumps(reply)[:600]}", file=sys.stderr)
                messages = messages + [
                    {"role": "model", "text": json.dumps(reply)},
                    {"role": "user", "text": f"That cannot be built: {error} Fix it and reply with the whole JSON."},
                ]
        raise ModelError(f"Could not build a project from the model's answer: {last_error}")
