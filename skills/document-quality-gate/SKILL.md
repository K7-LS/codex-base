---
name: document-quality-gate
description: Use when checking prepared text or DOCX, XLSX, PPTX or PDF before delivery.
---

# Document quality gate

Run this gate on the final bytes, after factual and domain review.

1. For DOCX/XLSX/PPTX use pinned OfficeCLI for addressed reads and edits. Do
   not let OfficeCLI install plugins, MCP, skills, or update itself.
2. Export Office files through the K7 signed COM PDF exporter. HTML and range
   screenshots are diagnostics only. Accept appearance from Office/PDF renders.
3. Run `scripts/quality_gate.py <file> --receipt quality-receipt.json`, pass
   every final render with `--render <path>`, the form verdict with
   `--file-review-verdict approved --file-reviewer <role>`, and the source
   verdict with `--audit-verdict approved --auditor auditor`.
4. `BLOCKED` means an objective defect and forbids delivery.
   `REVIEW_REQUIRED` means a style heuristic must be fixed or approved with
   `--review-verdict approved --reviewer <name>`. Required government/customer
   forms may be approved without redesign.
5. Office/PDF files cannot receive PASS without render evidence and an approved
   profile file reviewer. No artifact receives PASS without source audit.
6. A receipt is valid only for its `result_sha256`. Any byte change invalidates
   it. The profile file reviewer checks form; `auditor` checks source fidelity.

The gate does not invent facts, prove visual quality without renders, or treat
an OfficeCLI range screenshot/HTML render as final acceptance.
