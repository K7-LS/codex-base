---
name: stroy-formatting
description: Use when строительный документ нужно оформить по образцу.
---

# stroy-formatting

Use when a final DOCX needs a known construction/report style. Do not use for
XLSX, DWG, working Markdown or a document whose source template must be
preserved unchanged.

## Choose the style

If the user already named a style, use it. Otherwise ask one short question
with these choices:

- `gost-report-full` — formal report without a frame;
- `gost-report-light` — simplified internal report;
- `gost-report-with-border` — only for an explicitly landscape educational
  document; the bundled legacy frame is not accepted for portrait output;
- `plain-clean` — neutral readable office document.

Templates are bundled under:

```text
~/.agents/skills/stroy-formatting/assets/templates/
```

Copy the selected template to the user's requested output directory, populate
it through capability `document.word.write`, then run `word-checker`. If PDF is
requested, convert only after DOCX review and run `pdf-reviewer`.

Never fetch a template from another device, publish a template change from a
consumer, or save the deliverable inside the base. Missing capabilities return
`BLOCKED` with the exact dependency.
