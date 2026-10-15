"""Split a DOCX into numbered paragraph segments and edit their text in place.

Edits keep formatting: new text goes into the first run of the edited span, the
rest of the span is emptied (CLAUDE.md §5.4). Covers body, tables, text boxes,
headers and footers.
"""

import re
from dataclasses import dataclass

from docx.document import Document
from docx.opc.part import XmlPart
from docx.oxml.ns import qn
from lxml import etree

W_P, W_R, W_T = qn("w:p"), qn("w:r"), qn("w:t")
_READ_ONLY = {qn("w:tab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n"}
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
# ponytail: footnotes/endnotes load as opaque parts in python-docx; add when a real CV needs them.
_PARTS = re.compile(r"^/word/(document|header\d*|footer\d*)\.xml$")


class PatchError(ValueError):
    pass


@dataclass
class Segment:
    id: int
    part: str
    # [paragraph] or [paragraph, mc:Fallback copy] for text boxes stored twice.
    paragraphs: list[etree._Element]

    @property
    def text(self) -> str:
        return "".join(t for _, t, _ in _pieces(self.paragraphs[0]))


def _pieces(p: etree._Element) -> list[tuple[etree._Element, str, bool]]:
    """(element, text, editable) for this paragraph's own text, excluding nested text boxes."""
    out = []
    for el in p.iter(W_T, *_READ_ONLY):
        parent = el.getparent()
        if parent is None or parent.tag != W_R or next(el.iterancestors(W_P), None) is not p:
            continue  # tab-stop definitions, or text of a nested text box paragraph
        if el.tag == W_T:
            out.append((el, el.text or "", True))
        else:
            out.append((el, _READ_ONLY[el.tag], False))
    return out


def _in_fallback(p: etree._Element) -> bool:
    return any(a.tag == f"{_MC}Fallback" for a in p.iterancestors())


def load_segments(doc: Document) -> list[Segment]:
    segments: list[Segment] = []
    for part in doc.part.package.iter_parts():
        if not (isinstance(part, XmlPart) and _PARTS.match(str(part.partname))):
            continue
        root = part.element
        copies: dict[etree._Element, etree._Element] = {}
        for ac in root.iter(f"{_MC}AlternateContent"):
            choice = [p for c in ac.iterchildren(f"{_MC}Choice") for p in c.iter(W_P)]
            fallback = [p for f in ac.iterchildren(f"{_MC}Fallback") for p in f.iter(W_P)]
            if len(choice) == len(fallback):
                for c, f in zip(choice, fallback, strict=True):
                    if _text(c) == _text(f):
                        copies[c] = f
        for p in root.iter(W_P):
            if _in_fallback(p):
                continue
            paras = [p, copies[p]] if p in copies else [p]
            segments.append(Segment(len(segments), str(part.partname), paras))
    return segments


def _text(p: etree._Element) -> str:
    return "".join(t for _, t, _ in _pieces(p))


def _edits(p: etree._Element, old: str, new: str) -> list[tuple[etree._Element, str]]:
    pieces = _pieces(p)
    text = "".join(t for _, t, _ in pieces)
    if not old or text.count(old) != 1:
        raise PatchError("old_text must appear exactly once in the segment")
    a = text.index(old)
    b = a + len(old)
    edits: list[tuple[etree._Element, str]] = []
    pos = 0
    for el, t, editable in pieces:
        start, end = pos, pos + len(t)
        pos = end
        if end <= a or start >= b:
            continue
        if not editable:
            raise PatchError("edit crosses a tab or line break")
        after = t[b - start :] if end > b else ""
        if not edits:
            edits.append((el, t[: max(a - start, 0)] + new + after))
        else:
            edits.append((el, after))
    return edits


def apply_patch(segment: Segment, old: str, new: str) -> None:
    """Replace `old` with `new` in the segment. Raises PatchError without changing anything."""
    planned = [e for p in segment.paragraphs for e in _edits(p, old, new)]
    for el, text in planned:
        el.text = text
        el.set(_XML_SPACE, "preserve")
