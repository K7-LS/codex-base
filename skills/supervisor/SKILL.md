---
name: supervisor
description: Use when явно нужен надзор за автономным Codex.
---

# supervisor

Use only when the user explicitly asks Codex to supervise background,
autonomous, or long-running work.

## Native controls

1. Define the objective, allowed workspace, mutation boundary, stop conditions,
   validation commands and escalation conditions.
2. Use Codex custom agent/automation monitoring already available in the current
   surface. Do not launch an external agent SDK or copy credentials.
3. Keep the active sandbox and approval policy. Never use a bypass flag.
4. Classify proposed local shell actions with `tools/rules.py` when useful.
   The classifier is advisory; on the pinned client, a user-level PreToolUse
   hook is not a complete enforcement boundary.
5. Use the operating-system sandbox, Codex permissions and managed
   requirements for hard isolation. Return `BLOCKED` if the requested
   guarantee cannot be enforced.
6. Report progress locally. Do not send Telegram messages, telemetry, prompts,
   reports or device identifiers.

Any hook or automation installation is a separate configuration change:
show the exact file, exact content and effect, then obtain explicit approval.
The released base itself enables only the once-per-day version-check hook.
