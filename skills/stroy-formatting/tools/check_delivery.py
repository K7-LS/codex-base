#!/usr/bin/env python3
"""Check final files for internal markers and optionally Word paragraph borders."""

import argparse
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


MARKER = re.compile(
    r"\b(?:не\s+для\s+выдачи|только\s+для\s+внутреннего\s+пользования|"
    r"(?:служебн\w+|рабоч\w+|внутренн\w+)\s+(?:заметк\w*|пометк\w*|комментари\w*)\s*:|"
    r"(?:TODO|FIXME)\s*:)",
    re.IGNORECASE,
)
PARTS = {
    ".docx": r"word/(?:document|header\d+|footer\d+|comments\d*|endnotes|footnotes)\.xml",
    ".xlsx": r"xl/(?:worksheets/sheet\d+|sharedStrings|comments/(?:comment|comments)\d+|"
             r"comments\d+|threadedComments/threadedComment\d+|drawings/drawing\d+)\.xml",
    ".pptx": r"ppt/(?:slides/slide\d+|notesSlides/notesSlide\d+|comments/comment\d+)\.xml",
}
MAIN_PART = {
    ".docx": r"word/document\.xml",
    ".xlsx": r"xl/worksheets/sheet\d+\.xml",
    ".pptx": r"ppt/slides/slide\d+\.xml",
}
TEXT = {".txt", ".md", ".csv", ".tsv"}
EXCEL_HEADER_SECTION = re.compile(r"(?<!&)&[LCR]")
EXCEL_HEADER_FORMAT = re.compile(r'(?<!&)&(?:K[\da-fA-F]{6}|"[^"]*"|\d{1,3}|[A-Za-z])')
WORD_NAMESPACES = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}",
    "{http://purl.oclc.org/ooxml/wordprocessingml/main}",
}
WORD_STORIES = re.compile(r"word/(?:document|header\d+|footer\d+|endnotes|footnotes)\.xml")


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def text_groups(root: ET.Element, suffix: str):
    groups = {"p", "text", "si", "is"} if suffix == ".xlsx" else {"p", "text"}
    headers = {"oddHeader", "evenHeader", "firstHeader", "oddFooter", "evenFooter", "firstFooter"}
    for node in root.iter():
        name = local_name(node)
        if name in groups:
            runs = [run.text or "" for run in node.iter() if local_name(run) == "t"]
            yield "".join(runs) if runs else node.text or ""
            deleted = [run.text or "" for run in node.iter() if local_name(run) == "delText"]
            if deleted:
                yield "".join(deleted)
        elif suffix == ".xlsx" and name == "c" and node.get("t") == "str":
            yield next((child.text or "" for child in node if local_name(child) == "v"), "")
        elif suffix == ".xlsx" and name in headers:
            for section in EXCEL_HEADER_SECTION.split(node.text or ""):
                yield EXCEL_HEADER_FORMAT.sub("", section)


def word_has_colored_border(root: ET.Element, styles: ET.Element) -> bool:
    namespace, delimiter, _ = root.tag.rpartition("}")
    w = namespace + delimiter
    if w not in WORD_NAMESPACES or styles.tag not in ("styles", w + "styles"):
        raise ValueError("unrecognized Word namespace")
    paragraphs = {
        style.get(w + "styleId"): style for style in styles.findall(w + "style")
        if style.get(w + "type") == "paragraph"
    }
    default = next(
        (name for name, style in paragraphs.items() if style.get(w + "default") in ("1", "true")),
        None,
    )
    fallback = styles.find(f"{w}docDefaults/{w}pPrDefault/{w}pPr/{w}pBdr")
    for paragraph in root.iter(w + "p"):
        borders = [paragraph.find(f"{w}pPr/{w}pBdr")]
        applied = paragraph.find(f"{w}pPr/{w}pStyle")
        name = default if applied is None else applied.get(w + "val")
        seen = set()
        while name in paragraphs and name not in seen:
            seen.add(name)
            style = paragraphs[name]
            borders.append(style.find(f"{w}pPr/{w}pBdr"))
            parent = style.find(w + "basedOn")
            name = None if parent is None else parent.get(w + "val")
        borders.append(fallback)
        edges = {
            edge.tag: edge
            for border in reversed(borders) if border is not None
            for edge in border
        }
        if any(
            edge.get(w + "val") not in ("nil", "none")
            and (
                edge.get(w + "themeColor") is not None
                or edge.get(w + "color", "auto").lower() not in ("auto", "000000")
            )
            for edge in edges.values()
        ):
            return True
    return False


def scan(path: Path, suffix: str, plain: bool = False) -> list[dict[str, str]]:
    if suffix in TEXT:
        return [
            {"location": f"line {number}", "code": "INTERNAL_NOTE"}
            for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
            if MARKER.search(line)
        ]
    with ZipFile(path) as package:
        names = sorted(name for name in package.namelist() if re.fullmatch(PARTS[suffix], name))
        if not any(re.fullmatch(MAIN_PART[suffix], name) for name in names):
            raise ValueError("main document part missing")
        styles = ET.Element("styles")
        if plain and "word/styles.xml" in package.namelist():
            styles = ET.fromstring(package.read("word/styles.xml"))
        findings = []
        for name in names:
            root = ET.fromstring(package.read(name))
            if any(MARKER.search(group) for group in text_groups(root, suffix)):
                findings.append({"location": name, "code": "INTERNAL_NOTE"})
            if plain and WORD_STORIES.fullmatch(name) and word_has_colored_border(root, styles):
                findings.append({"location": name, "code": "NON_NEUTRAL_PARAGRAPH_BORDER"})
        return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--plain", action="store_true", help="also check neutral DOCX paragraph borders")
    args = parser.parse_args()
    path = args.path
    suffix = path.suffix.lower()
    if args.plain and suffix != ".docx":
        parser.error("--plain requires a DOCX file")
    if suffix not in TEXT and suffix not in PARTS:
        print(json.dumps({"status": "NOT_CHECKED", "findings": [{"code": "UNSUPPORTED_FORMAT"}]}))
        return 3
    try:
        findings = scan(path, suffix, plain=args.plain)
    except (OSError, BadZipFile, ValueError, ET.ParseError):
        findings = [{"code": "UNREADABLE_DOCUMENT"}]
    print(json.dumps({"status": "BLOCKED" if findings else "PASS", "findings": findings}))
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
