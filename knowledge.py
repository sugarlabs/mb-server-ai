"""The reference documents the prompts quote, which are block cards, guide
sections and example projects. They are built from a Music Blocks checkout so
they follow upstream.

Build:  python knowledge.py <musicblocks checkout>   (writes data/knowledge.json)
Search: Knowledge().search("how do I repeat a note", limit=8)
"""

import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from project import DATA_DIR, load_specs, parse_project_text, read_tree, render_tree

# Upstream guides, in the order a person would read them. The Turtle Blocks
# guide is left out on purpose, since it describes a different program.
GUIDE_FILES = [
    "Docs/guide/README.md",
    "Docs/documentation/README.md",
    "Docs/Debugging.md",
    "Docs/troubleshooting.md",
    "Docs/FAQ/README.md",
    "REFLECTION-WIDGET-GUIDE.md",
    "AI-Debugger-widget-guide.md",
    "DEBUGGER-TOOL-GUIDE.md",
    "lego-block-widget-README.md",
]
SECTION_LIMIT = 3000
EXAMPLE_TREE_LIMIT = 1500
GITHUB = "https://github.com/sugarlabs/musicblocks/blob/master/"


@dataclass(frozen=True)
class Document:
    id: str
    kind: str
    title: str
    text: str
    source: str


def block_documents(checkout: Path) -> list[Document]:
    documents = []
    for spec in load_specs().values():
        if not spec.help and not spec.label:
            continue
        slots = [label for label in spec.arg_labels if label]
        parts = [
            f"Block: {spec.label or spec.name} (internal name {spec.name}).",
            f"Palette: {spec.palette}. {'Beginner' if spec.beginner else 'Advanced'} block.",
        ]
        if slots:
            parts.append("Slots: " + ", ".join(slots) + ".")
        if spec.clamp_count:
            parts.append("It holds other blocks inside it.")
        if spec.help:
            parts.append(spec.help)
        documents.append(
            Document(
                id=f"block:{spec.name}",
                kind="block",
                title=spec.label or spec.name,
                text=" ".join(parts),
                source=f"{GITHUB}js/blocks/",
            )
        )
    return documents


def _clean_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"<img[^>]*>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def guide_documents(checkout: Path) -> list[Document]:
    documents = []
    for relative in GUIDE_FILES:
        path = checkout / relative
        if not path.exists():
            continue
        text = _clean_markdown(path.read_text(encoding="utf-8"))
        # Split at headings, keeping the heading with its section.
        sections = re.split(r"\n(?=#{1,4} )", "\n" + text)
        for index, section in enumerate(section.strip() for section in sections):
            if len(section) < 80:
                continue
            title = re.sub(r"<[^>]+>", "", section.splitlines()[0]).lstrip("#").strip()
            for part, start in enumerate(range(0, len(section), SECTION_LIMIT)):
                documents.append(
                    Document(
                        id=f"guide:{relative}#{index}.{part}",
                        kind="guide",
                        title=title,
                        text=section[start : start + SECTION_LIMIT],
                        source=GITHUB + relative,
                    )
                )
    return documents


def example_documents(checkout: Path) -> list[Document]:
    specs = load_specs()
    documents = []
    for path in sorted((checkout / "examples").glob("*")):
        if path.suffix not in (".html", ".tb"):
            continue
        try:
            stacks = read_tree(parse_project_text(path.read_text(encoding="utf-8")), specs)
        except ValueError as error:
            print(f"skipping {path.name}: {error}", file=sys.stderr)
            continue
        title = path.stem.replace("-", " ").replace("_", " ")
        tree = render_tree(stacks, specs)
        if len(tree) > EXAMPLE_TREE_LIMIT:
            tree = tree[:EXAMPLE_TREE_LIMIT] + "\n..."
        documents.append(
            Document(
                id=f"example:{path.name}",
                kind="example",
                title=title,
                text=f"Example project: {title}\n{tree}",
                # The project file itself. Music Blocks lists a "file" URL
                # parameter but no code in it loads a project from one.
                source=f"{GITHUB}examples/{path.name}",
            )
        )
    return documents


def build(checkout: Path) -> list[Document]:
    return block_documents(checkout) + guide_documents(checkout) + example_documents(checkout)


TOKEN = re.compile(r"[a-z0-9]+")
# Question words match every guide section and drown out the words that matter.
STOPWORDS = set(
    "a an the and or of to in on for with is are was be it its this that how do does i my me "
    "you your can what when where why which make get use using want would could should will "
    "if so as at by from about into than then there their them they we our not no".split()
)


# Words children use for things the documents name differently. On 21 Oct 2026
# "how do I make it play faster?" found no tempo block, and the answer suggested
# a volume block.
SYNONYMS = {
    word: "tempo beats per minute"
    for word in ("fast", "faster", "slow", "slower", "speed", "quicker", "quick")
} | {
    word: "volume"
    for word in ("loud", "louder", "quiet", "quieter", "soft", "softer")
} | {"loop": "repeat forever", "again": "repeat", "twice": "repeat"}


def tokens(text: str) -> list[str]:
    return [token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS]


class Knowledge:
    """BM25 search over the documents. Small enough that no index library is needed."""

    def __init__(self, path: Path = DATA_DIR / "knowledge.json"):
        records = json.loads(path.read_text(encoding="utf-8"))
        self.documents = [Document(**record) for record in records]
        self.counts = [Counter(tokens(document.title + " " + document.text)) for document in self.documents]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.average_length = sum(self.lengths) / len(self.lengths)
        frequency = Counter(term for count in self.counts for term in count)
        total = len(self.documents)
        self.idf = {term: math.log(1 + (total - seen + 0.5) / (seen + 0.5)) for term, seen in frequency.items()}

    def search(self, query: str, limit: int = 8, kinds: tuple[str, ...] = ()) -> list[Document]:
        terms = set(tokens(query))
        for term in list(terms):
            terms.update(tokens(SYNONYMS.get(term, "")))
        scored = []
        for index, document in enumerate(self.documents):
            if kinds and document.kind not in kinds:
                continue
            count, length = self.counts[index], self.lengths[index]
            score = 0.0
            for term in terms:
                if term not in count:
                    continue
                frequency = count[term]
                score += self.idf[term] * frequency * 2.2 / (
                    frequency + 1.2 * (0.25 + 0.75 * length / self.average_length)
                )
            # A block named in the question ("repeat", "set instrument") is almost
            # always what the question is about.
            title_terms = set(tokens(document.title))
            if document.kind == "block" and title_terms and title_terms <= terms:
                score += 5.0
            if score > 0:
                scored.append((score, index))
        scored.sort(reverse=True)
        return [self.documents[index] for _, index in scored[:limit]]

    def block(self, name: str) -> Document | None:
        for document in self.documents:
            if document.id == f"block:{name}":
                return document
        return None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python knowledge.py <musicblocks checkout>")
    documents = build(Path(sys.argv[1]))
    output = DATA_DIR / "knowledge.json"
    output.write_text(json.dumps([document.__dict__ for document in documents], indent=1), encoding="utf-8")
    kinds = Counter(document.kind for document in documents)
    print(f"{len(documents)} documents ({dict(kinds)}) written to {output}", file=sys.stderr)
