# Codex configuration warnings on existing workstations

Codex Base does not own employee authentication, sessions, custom agents,
MCP connections, or project hooks. The package includes a narrow diagnostic
utility at `~/.codex/base/runtime/maintenance/repair_codex_config.py`. Run it
on each workstation after `$sync-base` (Python 3.11 or newer required):

```powershell
py -3 "$env:USERPROFILE\.codex\base\runtime\maintenance\repair_codex_config.py" --home "$env:USERPROFILE"
```

The default is read-only. `--apply` removes only the ignored
`computer_use.windows.always_allowed_app_ids` table and deprecated
`features.guardianv2.thread_context` fields, including profile overrides.
It moves byte-identical duplicate role files into a dated backup. Different
definitions for one role are reported as `needs_review`; compare them and
choose the intended role before moving either file. No unknown role or hook
is deleted automatically.

If Hindsight is enabled for a selected project, first place the unmodified
template from `~/.agents/skills/llm-interop/assets/hindsight-project-hooks/`
into that project's `.codex/` directory. Review and trust the three project
hooks in `/hooks`, then start a fresh Codex session in that project and verify
that Hindsight context is actually returned. Only after this live check, run:

```powershell
$tool = "$env:USERPROFILE\.codex\base\runtime\maintenance\repair_codex_config.py"
$project = 'C:\path\to\the\selected\project'
py -3 $tool --home "$env:USERPROFILE" --project $project
py -3 $tool --home "$env:USERPROFILE" --project $project --verified-project-bridge --apply
```

This removes the three known Hindsight hook definitions from the user
`config.toml` only when the operator confirms live activation, the bridge
matches the packaged template byte-for-byte, local Hindsight scripts exist,
and no mixed user hooks are present. If the project has other hooks, merge
them as needed and resolve the global conflict manually after confirming the
merged project hooks work; the utility will retain the global definitions.
The Foundation-managed `~/.codex/hooks.json` remains the sole
user-layer hook source. Each changed file is copied into
`~/.codex-backups/config-repair-<UTC timestamp>/` before the change.
Run the diagnostic again; `warnings` should be empty or each remaining item
must have a recorded `needs_review` decision. Restart Codex to verify the UI.
An employee who cannot run Python can make the same edits manually after
backup; the release does not silently edit personal configuration.
