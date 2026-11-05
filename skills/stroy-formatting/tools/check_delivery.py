#!/usr/bin/env python3
"""Read final files for explicit internal markers. Never prints marked text."""

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


def scan(path: Path, suffix: str) -> list[dict[str, str]]:
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
        return [
            {"location": name, "code": "INTERNAL_NOTE"}
            for name in names
            if any(MARKER.search(group) for group in text_groups(ET.fromstring(package.read(name)), suffix))
        ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    path = parser.parse_args().path
    suffix = path.suffix.lower()
    if suffix not in TEXT and suffix not in PARTS:
        print(json.dumps({"status": "NOT_CHECKED", "findings": [{"code": "UNSUPPORTED_FORMAT"}]}))
        return 3
    try:
        findings = scan(path, suffix)
    except (OSError, BadZipFile, ValueError, ET.ParseError):
        findings = [{"code": "UNREADABLE_DOCUMENT"}]
    print(json.dumps({"status": "BLOCKED" if findings else "PASS", "findings": findings}))
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
