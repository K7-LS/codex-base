# Device role and one-way publication

Codex-base has two local roles:

- `consumer` is the default. It can inspect and install verified stable
  releases, but never publishes local changes.
- `hub` is an explicit developer role used only to prepare a candidate and
  publish it after all release gates.

The role is local device state and is not part of a release. A missing or
invalid role is always treated as `consumer`.

Suggested local marker:

```json
{"role":"hub"}
```

at `~/.codex/base/local/device-role.json`. Foundation preserves the `local/`
directory and never distributes it.

## Hard boundaries

- Consumers only perform release discovery, verification, plan, install,
  doctor and rollback.
- No consumer command uploads diffs, lessons, reports, prompts, device data or
  usage data.
- A hub publication is an explicit maintainer action. It is never triggered by
  SessionEnd or another lifecycle hook.
- The SessionStart hook may perform one anonymous GitHub `GET` version check
  per 24 hours. It never installs an update.
- Stable publication requires offline evidence, matched A/B approval, canary
  approval and a final owner decision.
