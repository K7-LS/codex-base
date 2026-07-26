# graphify reference: deterministic navigation skeleton (Codex-base)

Load this when working on the **skeleton layer** of the base graph — the deterministic,
always-fresh navigational backbone built without any LLM call. Generic projects don't use it.

## Why it exists

The base graph had three problems that made Codex skip it (see
`memory/graphify_update_windows_traps.md` and the plan in `plans/`):
- **freshness was fragile** — any structural commit staled it; only the hub rebuilt it, by
  hand, via LLM subagents (tokens). graphify's own `graphify hook install` post-commit handles
  **code only** — useless for our 90%-`.md` base.
- **extraction fragmented cross-refs** — LLM subagents turned "designer references norm-lookup"
  into an orphan concept node `norm-lookup agent (referenced by designer)` with a non-canonical
  id, instead of a real traversable edge. Navigation broke even when queried.

The skeleton fixes both: it is **0-token, deterministic, post-commit-friendly** (so it stays
fresh on every PC), and it emits **real edges between canonical nodes**.

## What it builds — `tools/skeleton_build.py`

Canonical one-node-per-entity, predictable ids (`{kind}__{slug}`, cyrillic transliterated so
ids stay `[a-z0-9_]`; original name kept on `node['name']`):

| kind | source | id example |
|------|--------|-----------|
| `agent` | `agents/*.md` (skip `_TEMPLATE`/`agents.md`) | `agent__designer` |
| `skill` | `skills/*/SKILL.md` (folder name) | `skill__co_verify` |
| `tool` | `skills/*/tools|scripts/*` | `tool__skills_graphify_tools_skeleton_build_py` |
| `memory` | `memory/*.md` (skip `MEMORY.md`; base only, not `projects/`) | `memory__id_doc_dates_rule` |
| `block` | `blocks/*/BLOCK.md` | `block__pto` |
| `chain` | `chains/*.md` | `chain__project_doc_pack` |
| `command` | `commands/*.md` | `command__harvest` |
| `rule` | `AGENTS.md` `##`/`###` sections | `rule__token_distsiplina...` |
| `mcp` | `mcp-manifest.json` → `mcp_servers` | `capability `document.word.read`` |

Edges (all `confidence=EXTRACTED`, deterministic):
- **`[[wikilinks]]`** in any entity body → `references` (resolved to a canonical id; links to
  per-PC `projects/` memory resolve to nothing and are dropped — no orphans).
- **name mentions** of agents/skills (word-bounded, len ≥ 4) → `references` to the canonical
  node. This is the defect-#5 fix: `designer.md` mentioning `norm-lookup` → edge
  `agent__designer → agent__norm_lookup`.
- **skill → its tools/scripts** → `contains`.
- **AGENTS.md section → mentioned entity** → `rule__X → agent/skill/...`.

Output: `graphify-out/skeleton.json` (node-link, **written directly with the standard library —
no `graphifyy` package dependency**, so it builds on any PC with bare python), stamped
`built_at_commit=HEAD`. Heuristic favours **recall over precision** — better an extra related
node than a missed one; the source file is always cited so you verify in the file.

## Run

```bash
PY=$(cat graphify-out/.graphify_python | tr -d '\r' | tr '\\' '/')
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" skills/graphify/tools/skeleton_build.py
# --root <path> (default cwd) · --out <file> · --commit <sha> · --no-cluster
```

Fast (no LLM), safe to run on every commit. Verify integrity: 0 orphan edges, and a spot edge
like `agent__designer → agent__norm_lookup` exists.

## Relationship to the semantic layer

The skeleton is the **trusted core**. The LLM flow (`tools/graph_update_win.py`) is **optional
enrichment** on top — `rationale`, non-obvious `semantically_similar_to`/`conceptually_related_to`
— run occasionally on the hub. When merging, canonical skeleton nodes/edges take priority.
