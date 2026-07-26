---
name: id-tom-priemka
description: Use when PDF-том ИД нужно постранично принять перед сдачей.
---

# id-tom-priemka

Use after an execution-documentation volume is assembled and before delivery.
The output is a review report; do not edit or remove pages without a separate
explicit instruction.

## Procedure

1. Build a physical page map from the assembly log with
   `tools/build_map.py`. Position numbers in an inventory are not page numbers.
2. Add the expected section, document type and forbidden obsolete content for
   each physical range.
3. Render every page through capability `pdf.render` or an approved local
   deterministic renderer. For scanned pages, inspect the rendered image.
4. Review every page for integrity, orientation, clipping, stamps, signatures,
   section match, numbering, dates, foreign content and obsolete equipment.
5. Verify every CRITICAL or MAJOR candidate independently before confirming it.
6. Prove coverage with an explicit checked-page set:
   `checked_pages == 1..page_count`. Missing pages make the verdict
   `NOT PASSED`.
7. Produce a findings table with page, severity, category, evidence and
   responsible party. Keep rejected false alarms in a separate section.

For a large volume, estimate batch count and expected context cost first.
Parallel custom agents require the user's approval; inherit the active model
and reasoning unless the user explicitly chooses otherwise. The base never
sets a model.

## Guardrails

- Compare page title and stamp visually; do not trust scrambled vector text.
- Treat a finding as a candidate, not an instruction to alter the volume.
- Factory manuals may legitimately cover several models; verify before
  flagging.
- A filesystem timestamp is not evidence that content is current.
- Route the final PDF file-integrity review to `pdf-reviewer` and the
  content/source comparison to `auditor`.
