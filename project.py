"""Read, explain, check and build Music Blocks projects.

A saved project is a list of [id, name or [name, props], x, y, connections].
The meaning of each connection slot comes from the block's dockTypes, which
extract_blocks.cjs reads from Music Blocks itself:

    slot 0           the parent, or the block above
    argument slots   value blocks plugged into the block
    clamp slots      the first block inside each clamp ("in" docks)
    last slot        the block below, for blocks that sit in a stack

A tree here is a list of stacks. A stack is a list of statements, and each
statement is {"block", "args", "clamps"} with value blocks as {"block", "value"}
or plain numbers and strings.
"""

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Blocks that only shape the layout. The reader skips them and the builder adds
# "hidden" back after every note, as Music Blocks itself saves it.
LAYOUT_BLOCKS = {"vspace", "hidden"}
# Case blocks stack inside a switch through their own caseout and casein docks.
FLOW_TOP_DOCKS = {"out", "unavailable", "caseout", "vspaceout"}
NEXT_DOCKS = {"in", "unavailable", "vspacein", "casein"}
CLAMP_DOCKS = {"in", "casein"}
STACK_STARTERS = {"start", "action", "drum"}

# Value blocks and the kind of literal they hold, used when building.
LITERAL_BLOCKS = {"number": (int, float), "text": (str,)}


@dataclass(frozen=True)
class BlockSpec:
    name: str
    label: str
    palette: str
    base: str
    dock_types: tuple[str, ...]
    arg_labels: tuple[str, ...]
    clamp_labels: tuple[str, ...]
    help: str
    beginner: bool
    flow_type: str | None

    @property
    def is_flow(self) -> bool:
        return bool(self.dock_types) and self.dock_types[0] in FLOW_TOP_DOCKS

    @property
    def has_next(self) -> bool:
        return self.is_flow and len(self.dock_types) > 1 and self.dock_types[-1] in NEXT_DOCKS

    @property
    def clamp_count(self) -> int:
        # An argument clamp (do with arguments, make block) grows by arguments.
        if self.flow_type == "arg":
            return 0
        inner = self.dock_types[1:-1] if self.has_next else self.dock_types[1:]
        return sum(1 for dock in inner if dock in CLAMP_DOCKS)

    @property
    def arg_count(self) -> int:
        return len(self.dock_types) - 1 - self.clamp_count - (1 if self.has_next else 0)

    def arg_slots(self, given: int) -> int:
        """Slots to save for the given number of arguments. Argument clamps save
        exactly the arguments they hold, other blocks always save every slot."""
        if self.flow_type == "arg":
            return given
        return max(given, self.arg_count)


def load_specs(path: Path = DATA_DIR / "blocks.json") -> dict[str, BlockSpec]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {
        record["name"]: BlockSpec(
            name=record["name"],
            label=record["label"],
            palette=record["palette"],
            base=record["base"],
            dock_types=tuple(record["dockTypes"]),
            arg_labels=tuple(record["argLabels"]),
            clamp_labels=tuple(record["clampLabels"]),
            help=record["help"],
            beginner=record["beginner"],
            flow_type=record["flowType"],
        )
        for record in records
    }


class ProjectError(ValueError):
    """A project file or a generated tree that cannot be read or built."""


def parse_project_text(text: str) -> list[list]:
    """Return the raw block list from a .tb, .json or exported .html project."""
    stripped = text.lstrip()
    if stripped.startswith("<"):
        match = re.search(r'<div class="code"[^>]*>(.*?)</div>', text, re.S)
        if not match:
            raise ProjectError("This HTML file has no Music Blocks project code in it.")
        stripped = html.unescape(match.group(1))
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise ProjectError(f"The project is not valid JSON: {error}") from error
    if not isinstance(data, list):
        raise ProjectError("A Music Blocks project is a list of blocks.")
    # Real blocks have five fields. Shorter entries hold turtle state, not blocks.
    return [entry for entry in data if isinstance(entry, list) and len(entry) == 5]


def _name_and_props(entry: list) -> tuple[str, dict]:
    raw = entry[1]
    if isinstance(raw, list):
        return str(raw[0]), raw[1] if len(raw) > 1 and isinstance(raw[1], dict) else {}
    return str(raw), {}


class _Reader:
    def __init__(self, blocks: list[list], specs: dict[str, BlockSpec]):
        self.by_id = {entry[0]: entry for entry in blocks}
        self.specs = specs
        self.seen: set = set()

    def name(self, block_id) -> str:
        return _name_and_props(self.by_id[block_id])[0]

    def value(self, block_id):
        if block_id is None or block_id not in self.by_id:
            return None
        self.seen.add(block_id)
        name, props = _name_and_props(self.by_id[block_id])
        connections = self.by_id[block_id][4]
        spec = self.specs.get(name)
        node: dict = {"block": name}
        if "value" in props:
            node["value"] = props["value"]
        arg_ids = connections[1:]
        if spec is not None and spec.clamp_count:
            arg_ids = arg_ids[: len(arg_ids) - spec.clamp_count]
        args = [self.value(arg) for arg in arg_ids]
        if args:
            node["args"] = args
        if name == "number" and "value" in props:
            return props["value"]
        return node

    def stack(self, block_id) -> list[dict]:
        statements = []
        while block_id is not None and block_id in self.by_id and block_id not in self.seen:
            self.seen.add(block_id)
            name, props = _name_and_props(self.by_id[block_id])
            connections = self.by_id[block_id][4]
            spec = self.specs.get(name)
            if spec is None or not spec.is_flow:
                # An unknown block is kept and the stack ends there, since
                # its slots, and so the block below it, are unknown.
                statements.append({"block": name, "unknown": True})
                break
            next_id = connections[-1] if spec.has_next else None
            if name in LAYOUT_BLOCKS:
                block_id = next_id
                continue
            # Blocks with a variable number of arguments save more slots than
            # their dockTypes list, so arguments are counted from the end.
            clamp_end = len(connections) - (1 if spec.has_next else 0)
            clamp_start = clamp_end - spec.clamp_count
            statement: dict = {"block": name}
            if "value" in props:
                statement["value"] = props["value"]
            args = [self.value(arg) for arg in connections[1:clamp_start]]
            if args:
                statement["args"] = args
            clamps = [self.stack(child) for child in connections[clamp_start:clamp_end]]
            if clamps:
                statement["clamps"] = clamps
            statements.append(statement)
            block_id = next_id
        return statements


def read_tree(blocks: list[list], specs: dict[str, BlockSpec]) -> list[list[dict]]:
    """Turn a raw block list into stacks of statements, starters first."""
    reader = _Reader(blocks, specs)
    tops = [entry[0] for entry in blocks if entry[4] and entry[4][0] is None]
    tops.sort(key=lambda block_id: reader.name(block_id) not in STACK_STARTERS)
    stacks = []
    for top in tops:
        if top in reader.seen:
            continue
        spec = specs.get(reader.name(top))
        if spec is not None and not spec.is_flow:
            stacks.append([{"block": "(loose value)", "args": [reader.value(top)]}])
        else:
            stacks.append(reader.stack(top))
    return stacks


def _expression(node, specs: dict[str, BlockSpec]) -> str:
    if node is None:
        return "(empty)"
    if not isinstance(node, dict):
        return json.dumps(node) if isinstance(node, str) else str(node)
    spec = specs.get(node["block"])
    label = spec.label if spec is not None and spec.label else node["block"]
    if "value" in node and not node.get("args"):
        name, value = node["block"], node["value"]
        # Pickers (solfege, drum name, ...) are their value. Named boxes and
        # actions need the label. Sensors save their last reading, which is noise.
        if name in ("text", "solfege", "boolean") or name.endswith("name"):
            return json.dumps(value) if name == "text" else str(value)
        if name.startswith("named"):
            return f"{label} {value}"
        return label
    args = [_expression(arg, specs) for arg in node.get("args", [])]
    if len(args) == 2 and len(label) <= 2:
        return f"({args[0]} {label} {args[1]})"
    return f"{label}({', '.join(args)})"


def render_tree(stacks: list[list[dict]], specs: dict[str, BlockSpec]) -> str:
    """An indented text view of the project, one block per line."""
    lines: list[str] = []

    def statement(node: dict, depth: int) -> None:
        spec = specs.get(node["block"])
        label = spec.label if spec is not None and spec.label else node["block"]
        if node.get("unknown"):
            label += " (not a known block)"
        args = node.get("args", [])
        arg_labels = spec.arg_labels if spec is not None else ()
        parts = []
        for index, arg in enumerate(args):
            name = arg_labels[index] if index < len(arg_labels) and arg_labels[index] else ""
            text = _expression(arg, specs)
            parts.append(f"{name} {text}".strip())
        if "value" in node:
            parts.insert(0, str(node["value"]))
        lines.append("  " * depth + " ".join([label, ", ".join(parts)]).rstrip())
        clamp_labels = spec.clamp_labels if spec is not None else ()
        for index, clamp in enumerate(node.get("clamps", [])):
            name = clamp_labels[index] if index < len(clamp_labels) and clamp_labels[index] else ""
            if name:
                lines.append("  " * (depth + 1) + f"[{name}]")
            for child in clamp:
                statement(child, depth + 1)

    for number, stack in enumerate(stacks, start=1):
        if number > 1:
            lines.append("")
        for node in stack:
            statement(node, 0)
    return "\n".join(lines)


def _walk(stack: list[dict]):
    for node in stack:
        yield node
        for clamp in node.get("clamps", []):
            yield from _walk(clamp)


# A run of notes written as one "melody" statement, such as
# {"block": "melody", "notes": "E5 1/16, D#5 1/16, rest 1/8"}. Each note as a
# block tree is about 150 characters of JSON, so on 21 Oct 2026 "play Fur
# Elise" ran past the model's output limit and the answer was cut off.
SOLFEGE = ("do", "re", "mi", "fa", "sol", "la", "ti")
NOTE = re.compile(r"^(?:(?P<letter>[A-G])|(?P<solfege>do|re|mi|fa|sol|la|ti))(?P<accidental>[#b♯♭]?)(?P<octave>-?\d+)$")
DURATION = re.compile(r"^(\d+)/(\d+)$")


def _melody_notes(text: str) -> list[dict]:
    notes = []
    for item in str(text).split(","):
        parts = item.split()
        if not parts:
            continue
        if len(parts) != 2 or not DURATION.match(parts[1]):
            raise ProjectError(f'A melody note is a pitch and a duration, like "E5 1/16" or "rest 1/8", got "{item.strip()}".')
        numerator, denominator = (int(number) for number in DURATION.match(parts[1]).groups())
        if parts[0] == "rest":
            sound = {"block": "rest2"}
        else:
            match = NOTE.match(parts[0])
            if not match:
                raise ProjectError(f'"{parts[0]}" is not a pitch. Write a note name and octave like "E5", "F#4" or "sol4".')
            accidental = {"#": "♯", "b": "♭"}.get(match["accidental"], match["accidental"])
            if match["letter"]:
                name = {"block": "notename", "value": match["letter"] + accidental}
            else:
                name = {"block": "solfege", "value": match["solfege"] + accidental}
            sound = {"block": "pitch", "args": [name, int(match["octave"])]}
        notes.append({"block": "newnote", "args": [{"block": "divide", "args": [numerator, denominator]}], "clamps": [[sound]]})
    if not notes:
        raise ProjectError("A melody needs at least one note.")
    return notes


def _statement_list(value: object) -> list:
    """Statements as a list, fixing the shapes models get wrong: one statement
    where a list belongs, or a clamp written as a flat list of statements."""
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise ProjectError(f"Expected a list of statements, got {json.dumps(value)[:80]}.")
    return value


def _clamp_lists(clamps: object) -> list:
    if isinstance(clamps, dict):
        return [[clamps]]
    if isinstance(clamps, list) and clamps and all(isinstance(item, dict) for item in clamps):
        return [clamps]
    if not isinstance(clamps, list):
        raise ProjectError(f"Clamps must be a list of statement lists, got {json.dumps(clamps)[:80]}.")
    return [_statement_list(clamp) for clamp in clamps]


def expand_melodies(statements: list | dict) -> list:
    """Replace melody statements, at any depth, with the note blocks they stand
    for, and tidy the shape of the tree on the way."""
    expanded = []
    for statement in _statement_list(statements):
        if isinstance(statement, dict) and statement.get("block") == "melody":
            expanded.extend(_melody_notes(statement.get("notes", "")))
            continue
        if isinstance(statement, dict) and statement.get("clamps"):
            statement = {**statement, "clamps": [expand_melodies(clamp) for clamp in _clamp_lists(statement["clamps"])]}
        expanded.append(statement)
    return expanded


def _melody_note(node: dict) -> str | None:
    """A plain note as melody text, or None for anything else."""
    clamps = node.get("clamps", [])
    if node.get("block") != "newnote" or len(node.get("args", [])) != 1 or len(clamps) != 1 or len(clamps[0]) != 1:
        return None
    duration, sound = node["args"][0], clamps[0][0]
    if not isinstance(duration, dict) or duration.get("block") != "divide":
        return None
    numbers = duration.get("args", [])
    if len(numbers) != 2 or not all(isinstance(number, int) and not isinstance(number, bool) for number in numbers):
        return None
    length = f"{numbers[0]}/{numbers[1]}"
    if sound.get("block") == "rest2" and not sound.get("args"):
        return f"rest {length}"
    args = sound.get("args", [])
    if sound.get("block") != "pitch" or len(args) != 2 or not isinstance(args[1], int) or not isinstance(args[0], dict):
        return None
    name = args[0]
    value = str(name.get("value", ""))
    if name.get("block") not in ("notename", "solfege"):
        return None
    pitch = value.replace("♯", "#").replace("♭", "b") + str(args[1])
    return f"{pitch} {length}" if NOTE.match(pitch) else None


def compress_melodies(statements: list[dict]) -> list[dict]:
    """Write runs of two or more plain notes as melody statements, at any depth."""
    compressed, run = [], []

    def flush() -> None:
        if len(run) > 1:
            compressed.append({"block": "melody", "notes": ", ".join(text for text, _node in run)})
        else:
            compressed.extend(node for _text, node in run)
        run.clear()

    for node in statements:
        text = _melody_note(node)
        if text is not None:
            run.append((text, node))
            continue
        flush()
        if node.get("clamps"):
            node = {**node, "clamps": [compress_melodies(clamp) for clamp in node["clamps"]]}
        compressed.append(node)
    flush()
    return compressed


def block_names(stacks: list[list[dict]]) -> set[str]:
    """Every statement block in the project, including the ones inside clamps."""
    return {node["block"] for stack in stacks for node in _walk(stack)}


def _action_name(node: dict) -> str | None:
    args = node.get("args") or []
    first = args[0] if args else None
    if isinstance(first, dict) and "value" in first:
        return str(first["value"])
    return None


# Blocks that make a note sound, or rest2, which makes a silent note on purpose.
PITCH_BLOCKS = {
    "rest2",
    "pitch", "playdrum", "playnoise", "steppitch", "hertz", "pitchnumber", "nthmodalpitch",
    "scaledegree2", "customNote", "playeffect", "drum", "sixtyfourthNote", "thirtysecondNote",
}


def check_tree(stacks: list[list[dict]], specs: dict[str, BlockSpec]) -> list[str]:
    """Common mistakes, as short sentences for a child or a teacher."""
    problems: list[str] = []
    starters = [stack[0]["block"] for stack in stacks if stack]
    if "start" not in starters:
        problems.append("There is no start block, so nothing plays when you press run.")

    defined = {_action_name(stack[0]) for stack in stacks if stack and stack[0]["block"] == "action"}
    called = set()
    for stack in stacks:
        if stack and stack[0]["block"] not in STACK_STARTERS:
            first = specs.get(stack[0]["block"])
            label = first.label if first is not None and first.label else stack[0]["block"]
            problems.append(
                f'A stack starting with "{label}" is not inside a start or action block, so it never runs.'
            )
        for node in _walk(stack):
            if node.get("unknown"):
                problems.append(f'"{node["block"]}" is not a block in this version of Music Blocks.')
            if node["block"] in ("do", "doArg", "calc", "calcArg"):
                name = _action_name(node)
                if name is not None:
                    called.add(name)
            if node["block"] == "newnote":
                inside = {child["block"] for clamp in node.get("clamps", []) for child in _walk(clamp)}
                if not inside & PITCH_BLOCKS:
                    problems.append("A note block has no pitch or drum inside it, so it is silent.")
            for arg in node.get("args", []):
                if arg is None:
                    spec = specs.get(node["block"])
                    label = spec.label if spec is not None and spec.label else node["block"]
                    problems.append(f'The "{label}" block has an empty slot.')
    for name in sorted(called - defined):
        problems.append(f'An action named "{name}" is used but never defined.')
    for name in sorted(n for n in defined - called if n is not None):
        problems.append(f'The action "{name}" is defined but never used.')
    return problems


class _Builder:
    def __init__(self, specs: dict[str, BlockSpec]):
        self.specs = specs
        self.blocks: list[list] = []

    def add(self, name: str, props: dict | None, x: int, y: int, slots: int) -> int:
        block_id = len(self.blocks)
        self.blocks.append([block_id, [name, props] if props is not None else name, x, y, [None] * slots])
        return block_id

    def spec(self, name: str) -> BlockSpec:
        spec = self.specs.get(name)
        if spec is None:
            raise ProjectError(f'"{name}" is not a Music Blocks block.')
        return spec

    def value(self, node, parent: int, x: int, y: int) -> int:
        if isinstance(node, bool):
            node = {"block": "boolean", "value": node}
        elif isinstance(node, (int, float)):
            node = {"block": "number", "value": node}
        elif isinstance(node, str):
            node = {"block": "text", "value": node}
        if not isinstance(node, dict) or "block" not in node:
            raise ProjectError(f"Cannot build a value from {node!r}.")
        spec = self.spec(node["block"])
        if spec.is_flow:
            raise ProjectError(f'"{node["block"]}" is a stack block and cannot go in a slot.')
        args = node.get("args", [])
        props = {"value": node["value"]} if "value" in node else None
        block_id = self.add(node["block"], props, x, y, 1 + spec.arg_slots(len(args)))
        self.blocks[block_id][4][0] = parent
        for index, arg in enumerate(args):
            if arg is None:
                continue
            child = self.value(arg, block_id, x + 80, y + 32 * index)
            self.blocks[block_id][4][1 + index] = child
        return block_id

    def stack(self, statements: list[dict], parent: int | None, x: int, y: int) -> int | None:
        """Build statements in order and return the id of the first one."""
        first = None
        previous = parent
        previous_is_parent = True
        for statement in statements:
            if not isinstance(statement, dict) or "block" not in statement:
                raise ProjectError(f"Each statement needs a block name, got {statement!r}.")
            name = statement["block"]
            spec = self.spec(name)
            if not spec.is_flow:
                raise ProjectError(f'"{name}" is a value block and cannot be a statement.')
            args = statement.get("args", [])
            clamps = statement.get("clamps", [])
            if len(clamps) > spec.clamp_count:
                raise ProjectError(f'"{name}" has {spec.clamp_count} clamp(s), got {len(clamps)}.')
            arg_slots = spec.arg_slots(len(args))
            slots = 1 + arg_slots + spec.clamp_count + (1 if spec.has_next else 0)
            props = {"value": statement["value"]} if "value" in statement else None
            if name in STACK_STARTERS and props is None:
                props = {"collapsed": False}
            block_id = self.add(name, props, x, y, slots)
            if first is None:
                first = block_id
            if previous is not None and not previous_is_parent:
                self.blocks[previous][4][-1] = block_id
            self.blocks[block_id][4][0] = previous
            for index, arg in enumerate(args):
                if arg is None:
                    continue
                child = self.value(arg, block_id, x + 100, y + 32 * index)
                self.blocks[block_id][4][1 + index] = child
            for index, clamp in enumerate(clamps):
                child = self.stack(clamp, block_id, x + 20, y + 42)
                self.blocks[block_id][4][1 + arg_slots + index] = child
            y += 42 * (1 + sum(len(clamp) for clamp in clamps))
            previous, previous_is_parent = block_id, False
            if name == "newnote":
                hidden = self.add("hidden", None, x, y, 2)
                self.blocks[block_id][4][-1] = hidden
                self.blocks[hidden][4][0] = block_id
                previous = hidden
        return first


def build_project(stacks: list[list[dict]], specs: dict[str, BlockSpec]) -> list[list]:
    """Turn stacks of statements into a project Music Blocks can load."""
    if not isinstance(stacks, list) or not stacks:
        raise ProjectError("A project needs at least one stack of blocks.")
    builder = _Builder(specs)
    for index, stack in enumerate(stacks):
        if not isinstance(stack, list) or not stack:
            raise ProjectError("Each stack must be a non-empty list of statements.")
        builder.stack(stack, None, 100 + 300 * index, 100)
    return builder.blocks
