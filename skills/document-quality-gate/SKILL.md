---
name: document-quality-gate
description: Use when checking prepared text or DOCX, XLSX, PPTX or PDF before delivery.
---

# Document quality gate

Run this gate on the final bytes, after factual and domain review.

Choose form review by the actual deliverable format and the reviewer's scope.
For plain text, including chat and Markdown, the main agent checks structure
and language; use a separate form reviewer when the task requires one. Keep
the requested output format. Run the script for file deliverables; check chat
directly. Independent source review remains required by the base rules.

1. Use an available, verified tool suited to the actual format for addressed
   reads and edits. Use pinned OfficeCLI when appropriate; do not let it install
   plugins, MCP, skills, or update itself. Respect a project's required route;
   report an unmet requirement instead of silently substituting a tool.
2. For Office/PDF deliverables, check appearance from actual Office/PDF output
   tied to the final file.
   For spreadsheets verify formulas and recalculated values as well as print
   layout. An existing render is valid only while its source bytes still match;
   distinguish reusing it from a fresh export. A supported Office renderer or a
   verified K7 exporter may provide the render; presence or a signed name alone
   does not prove the operation works. Automation may close only its own Office
   instance, never processes inferred to belong to it merely because they are
   new or have no visible window. HTML and range screenshots are diagnostics.
3. Run `scripts/quality_gate.py <file> --receipt quality-receipt.json`, pass
   the source verdict with `--audit-verdict approved --auditor auditor`.
   For Office/PDF, also pass every final render with `--render <path>` and
   the form verdict with `--file-review-verdict approved --file-reviewer <role>`.
4. `BLOCKED` means an objective defect or a rejected required review; resolve
   the cause before claiming the artifact is ready. `REVIEW_REQUIRED` can mean
   missing source audit, format review or render evidence, or a style warning.
   Complete missing checks; a style approval cannot replace them. For reviewed
   style warnings use `--review-verdict approved --reviewer <name>`.
   Required government/customer forms may be approved without redesign.
5. Office/PDF files cannot receive PASS without render evidence and an approved
   profile file reviewer. No artifact receives PASS without source audit.
6. A receipt is valid only for its `result_sha256`. Any byte change invalidates
   it. The profile file reviewer checks form; `auditor` checks source fidelity.

The gate does not invent facts, prove visual quality without renders, or treat
an OfficeCLI range screenshot/HTML render as final acceptance.
