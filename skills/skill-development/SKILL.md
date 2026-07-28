---
name: skill-development
description: Use when создаётся или изменяется повторно используемый навык.
---

# Skill development

Build reusable skills as small discovery interfaces, not as permanent copies
of the current conversation. Current-generation models benefit from compact
principles and details loaded only when the task needs them.

## Shape

- Frontmatter says **when** to load the skill.
- `SKILL.md` gives the shortest useful **how** and the non-obvious choices.
- `tools/` holds deterministic scripts and templates.
- `references/` holds detailed material loaded only when needed.
- One high-fidelity reference is usually better than several narrow examples.

Prefer 3–5 focused, composable skills to a monolith. Give each rule, script, or
reference one canonical home; other skills point to that home instead of
copying it.

## Workflow

1. Search the existing catalog or project graph before creating another asset.
2. Define the behavior or decision the skill must improve.
3. For behavior-shaping changes, capture a failing scenario or deterministic
   contract before editing.
4. Make the smallest change that resolves the observed gap. Put repeatable
   transformations in code.
5. Verify discovery metadata, referenced paths, and the target scenario.

## When to evolve a skill

Update a skill when work reveals material reusable learning: a repeated user
correction, a stable project invariant, a missing decision boundary, or a
deterministic operation worth encoding. Ordinary session details stay in the
task or project state; they do not trigger ritual skill maintenance.

Keep strict language for genuinely high-impact boundaries such as privacy,
credentials, provider policy, destructive actions, and irreversible release
steps. Use principles and model judgment for ordinary implementation choices.

## Review

- The description contains triggers, not a summary of the procedure.
- The main file stays concise and project-specific.
- Detailed guidance loads progressively.
- Examples do not fence the solution space.
- Tests or scenarios demonstrate that the material change helps.
