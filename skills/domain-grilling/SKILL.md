---
name: domain-grilling
description: Use when инженерной задаче не хватает критичных вводных.
---

# domain-grilling

Use for substantive construction and engineering work when a missing input can
change quantities, equipment, compliance, cost, or the delivered document.
Examples: design calculations, equipment selection, specifications, bills of
quantities, estimates, execution documents and expert-review responses.

## Native Codex flow

1. Enter native Plan Mode when the custom agent needs three or more dependent
   decisions.
2. Search project files and authoritative references before asking. Never ask
   the user for a fact already present in the supplied source.
3. Ask exactly one question at a time. The next question must depend on the
   previous answer.
4. State the recommended answer and its evidence, then ask the user to confirm
   or correct it.
5. Record accepted decisions in the plan or a project artifact before
   implementation.
6. Stop grilling when every branch that can materially change the result is
   resolved.

Use `norm-lookup` for an exact normative claim. Do not quote a standard from
memory. If an answer cannot be found and the user cannot provide it, return
`BLOCKED` and name the missing input.

## Opt-out and small tasks

Skip this native custom agent plan when inputs are demonstrably complete, the request is a
simple read-only action, or the user explicitly says `без грилинга` /
`вводные полные`. Do not install a prompt detector or global hook; HOT guidance
and skill discovery are sufficient.
