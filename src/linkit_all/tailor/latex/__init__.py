"""Split a single-file LaTeX CV into numbered text segments and edit only their text.

Segments are runs of text nodes between structural breaks (\\item, \\\\, `&`, sections,
environments, math, unknown commands, blank lines). Edits are written back as character-span
replacements in the original source, so everything else stays byte-identical, and every
edit is re-checked: the non-text skeleton of the result must equal the original's
(CLAUDE.md §5.4: text nodes only, never commands, macros or layout).
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexCommentNode,
    LatexEnvironmentNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexMathNode,
    LatexSpecialsNode,
    LatexWalker,
    get_default_latex_context_db,
)
from pylatexenc.macrospec import MacroSpec

from linkit_all.tailor.docx.segments import PatchError
from linkit_all.tailor.patches import Patch


class LatexError(ValueError):
    pass


# Text styling: no break, the argument is part of the surrounding sentence.
_INLINE = frozenset(
    [
        "textbf",
        "textit",
        "emph",
        "textsc",
        "textsf",
        "texttt",
        "textrm",
        "textnormal",
        "textup",
        "textsl",
        "textmd",
        "underline",
        "uline",
        "mbox",
        "hbox",
    ]
)
# Own paragraph: break before and after, text argument is a segment.
_HEADINGS = frozenset(
    ["part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph"]
)
_ESCAPES = "&%$#_{}"
_SKIP_ENVS = frozenset(
    [
        "verbatim",
        "verbatim*",
        "lstlisting",
        "minted",
        "comment",
        "tikzpicture",
        "filecontents",
        "math",
        "displaymath",
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "multline",
        "multline*",
        "eqnarray",
        "eqnarray*",
    ]
)
_PARA = re.compile(r"\n[ \t\r]*\n\s*")
_MULTI_FILE = re.compile(r"\\(?:input|include|includeonly|subfile|import|subimport)\b")
_NEWCOMMAND = re.compile(
    r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d)\])?\s*(\[[^\]]*\])?"
    r"|\\def\\([A-Za-z@]+)((?:#\d)*)"
)
_ESCAPE_OUT = {c: "\\" + c for c in _ESCAPES}


@dataclass(frozen=True)
class Atom:
    """One plain-text character and the source span it comes from."""

    start: int
    end: int
    ch: str
    editable: bool = True


@dataclass
class Segment:
    id: int
    atoms: list[Atom] = field(repr=False)

    @property
    def text(self) -> str:
        return "".join(a.ch for a in self.atoms)


def check_source(source: str) -> None:
    code = re.sub(r"(?<!\\)%.*", "", source)
    if _MULTI_FILE.search(code):
        raise LatexError(
            "Multi-file LaTeX projects (\\input, \\include) are not supported: "
            "upload one self-contained .tex file"
        )


def _user_macros(source: str) -> list[MacroSpec]:
    specs = []
    for m in _NEWCOMMAND.finditer(source):
        if m.group(1):
            n = int(m.group(2) or 0)
            argspec = ("[" + "{" * (n - 1)) if m.group(3) and n else "{" * n
            specs.append(MacroSpec(m.group(1), argspec))
        else:
            specs.append(MacroSpec(m.group(4), "{" * m.group(5).count("#")))
    return specs


def _parse(source: str) -> list[Any]:
    db = get_default_latex_context_db()
    # href is unknown to pylatexenc; commands the CV defines itself take text arguments.
    db.add_context_category(
        "linkit", macros=[MacroSpec("href", "{{"), *_user_macros(source)], prepend=True
    )
    nodes, _, _ = LatexWalker(source, latex_context=db).get_latex_nodes()
    return list(nodes)


class _Walk:
    def __init__(self, user: set[str]) -> None:
        self.user = user
        self.segments: list[list[Atom]] = []
        self.cur: list[Atom] = []

    def brk(self) -> None:
        if self.cur:
            self.segments.append(self.cur)
            self.cur = []

    def text(self, start: int, s: str, editable: bool = True) -> None:
        self.cur += [
            Atom(start + i, start + i + 1, " " if c.isspace() else c, editable)
            for i, c in enumerate(s)
        ]

    def chars(self, pos: int, s: str) -> None:
        at = 0
        for m in _PARA.finditer(s):
            self.text(pos + at, s[at : m.start()])
            self.brk()
            at = m.end()
        self.text(pos + at, s[at:])

    def args(self, n: Any) -> list[Any]:
        argd = n.nodeargd
        found = argd.argnlist if argd is not None else []
        return [a for a in found if isinstance(a, LatexGroupNode) and a.delimiters[0] == "{"]

    def walk(self, nodes: list[Any]) -> None:
        orphan_end = -1  # end of an unknown command: braces right after it are its arguments
        for n in nodes:
            if n is None:
                continue
            if isinstance(n, LatexGroupNode) and n.pos == orphan_end:
                orphan_end = n.pos + n.len
                continue
            orphan_end = -1
            if isinstance(n, LatexCharsNode):
                self.chars(n.pos, n.chars)
            elif isinstance(n, LatexSpecialsNode):
                s = n.specials_chars
                if s == "&":
                    self.brk()
                elif s == "~":  # a fixed space: readable, not editable
                    self.cur.append(Atom(n.pos, n.pos + 1, " ", editable=False))
                else:
                    self.text(n.pos, s)
            elif isinstance(n, LatexGroupNode):
                self.walk(n.nodelist)
            elif isinstance(n, LatexMathNode):
                self.brk()
            elif isinstance(n, LatexEnvironmentNode):
                self.brk()
                if n.environmentname not in _SKIP_ENVS:
                    self.walk(n.nodelist)
                self.brk()
            elif isinstance(n, LatexMacroNode):
                orphan_end = self.macro(n)
            elif not isinstance(n, LatexCommentNode):
                self.brk()

    def macro(self, n: LatexMacroNode) -> int:
        """Handle a command; returns the end offset when its arguments may follow unparsed."""
        name = n.macroname
        if name in _ESCAPES:
            self.cur.append(Atom(n.pos, n.pos + n.len, name))
        elif name in _INLINE:
            for a in self.args(n):
                self.walk(a.nodelist)
        elif name == "href":
            for a in self.args(n)[1:]:
                self.walk(a.nodelist)
        elif name in _HEADINGS or name in self.user:
            for a in self.args(n):
                self.brk()
                self.walk(a.nodelist)
                self.brk()
        else:
            self.brk()  # \item, \\, \hfill, \vspace, \includegraphics, \url ...: not text
            return int(n.pos + n.len)
        return -1


def load_segments(source: str) -> list[Segment]:
    """Non-empty text segments of the document body, numbered from 0 in source order."""
    check_source(source)
    nodes = _parse(source)
    body = next(
        (
            n.nodelist
            for n in nodes
            if isinstance(n, LatexEnvironmentNode) and n.environmentname == "document"
        ),
        nodes,
    )
    w = _Walk({s.macroname for s in _user_macros(source)})
    w.walk(body)
    w.brk()
    segments: list[Segment] = []
    for atoms in w.segments:
        kept: list[Atom] = []
        for a in atoms:  # collapse whitespace runs like TeX does, trim the ends
            if a.ch == " " and a.editable and (not kept or kept[-1].ch == " "):
                continue
            kept.append(a)
        while kept and kept[-1].ch == " " and kept[-1].editable:
            kept.pop()
        if kept:
            segments.append(Segment(len(segments), kept))
    return segments


def _escape(text: str) -> str:
    bad = sorted({c for c in text if c in "\\^~"})
    if bad:
        raise PatchError(
            f"new text contains {' '.join(bad)}, which LinKit does not write into LaTeX"
        )
    return "".join(_ESCAPE_OUT.get(c, c) for c in text)


def _words(text: str) -> list[str]:
    return re.findall(r"\s+|\w+|[^\w\s]", text)


def _edits(seg: Segment, new: str) -> list[tuple[int, int, str]]:
    """Word-level diff of the segment's text against `new`, as source-span replacements.

    A changed run of words is written into the first character's span and the rest of the run
    is deleted, so surrounding markup (\textbf{...}) stays where it was."""
    atoms = seg.atoms
    a, b = _words(seg.text), _words(new)
    cut_a = [0]
    for w in a:
        cut_a.append(cut_a[-1] + len(w))
    cut_b = [0]
    for w in b:
        cut_b.append(cut_b[-1] + len(w))
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        c1, c2 = cut_a[i1], cut_a[i2]
        rep = _escape(new[cut_b[j1] : cut_b[j2]])
        if c1 == c2:  # pure insertion: after the previous character, keeping its formatting
            pos = atoms[c1 - 1].end if c1 else atoms[0].start
            out.append((pos, pos, rep))
            continue
        for k in range(c1, c2):
            if not atoms[k].editable:
                raise PatchError("edit crosses a fixed space (~)")
            out.append((atoms[k].start, atoms[k].end, rep if k == c1 else ""))
    return out


def _skeleton(source: str, segments: list[Segment]) -> str:
    """The source without any editable text and without whitespace: commands and layout."""
    spans = sorted((a.start, a.end) for s in segments for a in s.atoms)
    parts, at = [], 0
    for start, end in spans:
        parts.append(source[at:start])
        at = end
    parts.append(source[at:])
    return re.sub(r"\s+", "", "".join(parts))


def apply_patches(source: str, segments: list[Segment], patches: list[Patch]) -> str:
    """Return `source` with the patches applied to the text nodes of `segments`.

    Raises PatchError (changing nothing) when a patch does not fit its segment or an edit
    would alter anything but text. Patches on one segment apply in order, like the plan."""
    by_id = {s.id: s for s in segments}
    texts: dict[int, str] = {}
    for p in patches:
        seg = by_id.get(p.segment_id)
        if seg is None:
            raise PatchError("unknown segment")
        text = texts.get(seg.id, seg.text)
        if not p.old_text or text.count(p.old_text) != 1:
            raise PatchError("old_text must appear exactly once in the segment")
        texts[seg.id] = text.replace(p.old_text, p.new_text, 1)
    edits = [e for sid, new in texts.items() for e in _edits(by_id[sid], new)]
    out = source
    for start, end, rep in sorted(edits, reverse=True):
        out = out[:start] + rep + out[end:]
    if _skeleton(out, load_segments(out)) != _skeleton(source, segments):
        raise PatchError("edit would change LaTeX commands, not just text")
    return out
