#!/usr/bin/env python3
"""Deterministic pre-delivery quality receipt for text and office artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


OFFICE = {".docx", ".xlsx", ".pptx"}
TEXT = {".txt", ".md", ".csv"}
ROBOTIC = (
    "в рамках данного",
    "следует отметить",
    "важно отметить",
    "таким образом",
    "данный документ",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def xml_text(payload: bytes) -> str:
    root = ET.fromstring(payload)
    return " ".join((node.text or "").strip() for node in root.iter() if node.text)


def style_checks(text: str) -> list[str]:
    lowered = text.casefold()
    warnings = [
        f"ROBOTIC_PHRASE:{phrase}"
        for phrase in ROBOTIC
        if lowered.count(phrase) >= 1
    ]
    starts: dict[str, int] = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        words = re.findall(r"[\wЁёА-Яа-я-]+", sentence.casefold())[:4]
        if len(words) >= 3:
            key = " ".join(words)
            starts[key] = starts.get(key, 0) + 1
    warnings.extend(
        f"REPEATED_SENTENCE_OPENING:{key}"
        for key, count in sorted(starts.items())
        if count >= 2
    )
    return sorted(set(warnings))


def inspect_office(path: Path) -> tuple[str, list[str], list[str], dict[str, str]]:
    defects: list[str] = []
    warnings: list[str] = []
    checks: dict[str, str] = {"package_structure": "PASS"}
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if path.suffix.lower() == ".docx":
                required = "word/document.xml"
                if required not in names:
                    defects.append("DOCX_DOCUMENT_XML_MISSING")
                    return "", defects, warnings, checks
                text = xml_text(archive.read(required))
                if "word/styles.xml" not in names:
                    warnings.append("DOCX_STYLES_MISSING")
                if "word/header1.xml" not in names and "word/footer1.xml" not in names:
                    warnings.append("DOCX_HEADERS_FOOTERS_NOT_DECLARED")
            elif path.suffix.lower() == ".xlsx":
                sheets = sorted(
                    name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
                )
                if not sheets:
                    defects.append("XLSX_WORKSHEETS_MISSING")
                    return "", defects, warnings, checks
                text = " ".join(xml_text(archive.read(name)) for name in sheets)
                workbook = archive.read("xl/workbook.xml") if "xl/workbook.xml" in names else b""
                if b"_xlnm.Print_Area" not in workbook:
                    warnings.append("XLSX_PRINT_AREA_NOT_DECLARED")
                sheet_payload = b"\n".join(archive.read(name) for name in sheets)
                if b"wrapText=\"1\"" not in b"\n".join(
                    archive.read(name) for name in names if name == "xl/styles.xml"
                ):
                    warnings.append("XLSX_WRAP_TEXT_NOT_EVIDENCED")
                if b"<pageSetup" not in sheet_payload:
                    warnings.append("XLSX_PAGE_SETUP_NOT_DECLARED")
            else:
                slides = sorted(
                    name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
                )
                if not slides:
                    defects.append("PPTX_SLIDES_MISSING")
                    return "", defects, warnings, checks
                text = " ".join(xml_text(archive.read(name)) for name in slides)
                warnings.append("PPTX_OVERFLOW_REQUIRES_RENDER_REVIEW")
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError):
        return "", ["INVALID_OFFICE_PACKAGE"], warnings, {"package_structure": "FAIL"}
    return text, defects, sorted(set(warnings)), checks


def inspect_pdf(path: Path) -> tuple[str, list[str], list[str], dict[str, str]]:
    payload = path.read_bytes()
    defects: list[str] = []
    warnings: list[str] = []
    if not payload.startswith(b"%PDF-"):
        defects.append("INVALID_PDF_HEADER")
    pages = len(re.findall(rb"/Type\s*/Page\b", payload))
    if pages == 0:
        defects.append("PDF_PAGES_MISSING")
    if b"/MediaBox" not in payload:
        warnings.append("PDF_PAGE_SIZE_NOT_EVIDENCED")
    if b"/Font" not in payload:
        warnings.append("PDF_FONTS_NOT_EVIDENCED")
    return "", defects, warnings, {"pdf_page_count": str(pages)}


def inspect(path: Path) -> tuple[str, list[str], list[str], dict[str, str]]:
    suffix = path.suffix.lower()
    if path.stat().st_size == 0:
        return "", ["EMPTY_CONTENT"], [], {"content": "FAIL"}
    if suffix in TEXT:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return "", ["INVALID_UTF8_TEXT"], [], {"content": "FAIL"}
        return text, [], [], {"content": "PASS"}
    if suffix in OFFICE:
        return inspect_office(path)
    if suffix == ".pdf":
        return inspect_pdf(path)
    return "", ["UNSUPPORTED_FORMAT"], [], {"content": "FAIL"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--render", action="append", default=[], type=Path)
    parser.add_argument("--exception", action="append", default=[])
    parser.add_argument("--review-verdict", choices=("approved", "rejected"))
    parser.add_argument("--reviewer")
    parser.add_argument("--file-review-verdict", choices=("approved", "rejected"))
    parser.add_argument("--file-reviewer")
    parser.add_argument("--audit-verdict", choices=("approved", "rejected"))
    parser.add_argument("--auditor")
    args = parser.parse_args(argv)
    if not args.source.is_file():
        parser.error("source must be an existing file")
    if bool(args.review_verdict) != bool(args.reviewer):
        parser.error("review verdict and reviewer must be supplied together")
    if bool(args.file_review_verdict) != bool(args.file_reviewer):
        parser.error("file review verdict and reviewer must be supplied together")
    if bool(args.audit_verdict) != bool(args.auditor):
        parser.error("audit verdict and auditor must be supplied together")

    text, defects, warnings, checks = inspect(args.source)
    warnings = sorted(set(warnings + style_checks(text)))
    renders = []
    for render in args.render:
        if not render.is_file() or render.stat().st_size == 0:
            defects.append(f"INVALID_RENDER:{render}")
            continue
        renders.append({"path": str(render.resolve()), "sha256": digest(render)})
    checks["visual_acceptance"] = "EVIDENCE_ATTACHED" if renders else "NOT_RUN"
    requires_visual = args.source.suffix.lower() in OFFICE | {".pdf"}
    checks["file_reviewer"] = args.file_review_verdict or "NOT_RUN"
    checks["source_audit"] = args.audit_verdict or "NOT_RUN"
    review = None
    if args.review_verdict:
        review = {"verdict": args.review_verdict, "reviewer": args.reviewer}
    file_review = (
        {"verdict": args.file_review_verdict, "reviewer": args.file_reviewer}
        if args.file_review_verdict
        else None
    )
    source_audit = (
        {"verdict": args.audit_verdict, "auditor": args.auditor}
        if args.audit_verdict
        else None
    )
    if defects:
        verdict, code = "BLOCKED", 2
    elif (
        (review and review["verdict"] == "rejected")
        or (file_review and file_review["verdict"] == "rejected")
        or (source_audit and source_audit["verdict"] == "rejected")
    ):
        verdict, code = "BLOCKED", 2
    elif (requires_visual and not renders) or (
        requires_visual and (not file_review or file_review["verdict"] != "approved")
    ) or not source_audit:
        verdict, code = "REVIEW_REQUIRED", 3
    elif warnings and (not review or review["verdict"] != "approved"):
        verdict, code = "REVIEW_REQUIRED", 3
    else:
        verdict, code = "PASS", 0
    receipt = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "result_path": str(args.source.resolve()),
        "result_sha256": digest(args.source),
        "checks": dict(sorted(checks.items())),
        "objective_defects": sorted(set(defects)),
        "style_warnings": warnings,
        "renders": renders,
        "exceptions": sorted(set(args.exception)),
        "review": review,
        "file_review": file_review,
        "source_audit": source_audit,
        "verdict": verdict,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.receipt.with_suffix(args.receipt.suffix + ".tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.receipt)
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
