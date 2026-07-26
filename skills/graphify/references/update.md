# graphify reference: incremental update and cluster-only

Load this only when the user passed `--update` or `--cluster-only`. A first-time full build never reads this file.

## For --update (incremental re-extraction)

Use when you've added or modified files since the last run. Only re-extracts changed files - saves tokens and time.

> ### ⚠ Windows hub / Codex-base (DANIIL-LAPTOP) — use the deterministic helper
>
> On a Windows hub with a Cyrillic install path (`C:\Users\Даниил\.codex`), the
> generic flow below silently corrupts the graph. Five traps (source:
> `memory/graphify_update_windows_traps.md` + the build_merge analysis in
> `session-reports/2026-06-23_graf-dovodka-bazy`):
>
> 1. **scan path** — `.graphify_root` stores a POSIX `/c/Users/...` path; Windows-Python
>    can't resolve it → `detect_incremental` finds **0 files** → everything is flagged
>    *deleted*. Needs a native `C:/Users/...` path.
> 2. **encoding** — cp1251 console mangles Cyrillic in `print()` (`Даниил`→`������`).
>    Always `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`.
> 3. **source_file** — extraction subagents sometimes park the path in `source_location`
>    and leave `source_file:null` → orphan nodes, 300+ "missing source_file" warnings.
> 4. **build_merge prunes new nodes too** — `graphify.build.build_merge` does
>    `build(old + new)` and **then** prunes by `source_file` on the *combined* graph, so
>    `prune_sources=[changed_file]` deletes the **freshly re-extracted** nodes of that
>    changed file, not just the stale ones. The changed file's update vanishes. (This is
>    why the generic flow's `prune = deleted + changed` is wrong for *changed* files, and
>    why a hand-run controlled rebuild was needed last time.)
> 5. **commit stamp** — the generic Step 4 `to_json()` never stamps `built_at_commit`, so
>    the `graph-staleness-check.ps1` hook stays red after a by-the-book rebuild.
>
> **Helper:** `skills/graphify/tools/graph_update_win.py` (subcommands `detect` / `merge`
> / `finalize`) encodes all five. The deterministic glue is in the script; the LLM
> extraction (Step 3B subagents) still runs between `detect` and `merge`.
>
> **Flow (run from `~/.codex`, the dir holding `graphify-out/`):**
> ```bash
> PY=$(cat graphify-out/.graphify_python | tr -d '\r' | tr '\\' '/')
> # 1. detect — native path + utf-8 (traps #1,#2). Writes incremental + detect JSON.
> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" skills/graphify/tools/graph_update_win.py detect
> #    (reads .graphify_root and coerces /c/->C:/; pass --root C:/Users/.../.codex to override)
> ```
> 2. **Extraction (Step 3 of SKILL.md):** read `.graphify_detect.json` (`files` = changed
>    subset). If `code_only` was printed `True`, run only AST (Part A). Otherwise dispatch
>    Step 3B subagents (`subagent_type="general-purpose"`, **model — ask the user**, last
>    time selected model) over the changed files → chunks → Part C merge into `.graphify_extract.json`.
> ```bash
> # 3. merge — manual controlled merge: prune ONLY old, layer new on top (traps #3,#4).
> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" skills/graphify/tools/graph_update_win.py merge
> # 4. finalize — build/cluster/report + to_json(built_at_commit=HEAD) (trap #5).
> #    Default refuses on net node loss; re-run with --force only if the loss is verified.
> PYTHONIOENCODING=utf-8 PYTHONUTF8=1 "$PY" skills/graphify/tools/graph_update_win.py finalize
> ```
> 5. Then **Step 5** (label communities — reads `.graphify_analysis.json`), **Step 6**
>    (HTML viz), **Step 9** (manifest already saved by `merge`; do the cleanup + report).
>
> **Commit order matters (trap #5).** `built_at_commit` must equal a commit that already
> contains the structural edits, or the hook re-reds immediately. `graphify-out/` is **not**
> a structural path, so commit it separately and last:
> ```bash
> git add agents skills memory blocks chains AGENTS.md mcp-manifest.json  # structural edits
> git commit -m "..."                                                     # structural commit
> HEAD=$(git rev-parse --short HEAD)                                      # capture AFTER it
> #   → run detect/extract/merge, then: finalize --commit "$HEAD"
> git add graphify-out && git commit -m "graphify: rebuild graph"         # non-structural, won't re-stale
> ```
>
> The generic flow below is the upstream POSIX / single-source-format path — keep it for
> other projects, but on the Codex-base Windows hub prefer the helper above.

### Generic flow (POSIX / single-format projects)

```bash
$(cat graphify-out/.graphify_python) -c "
import sys, json
from graphify.detect import detect_incremental, save_manifest
from pathlib import Path

result = detect_incremental(Path('INPUT_PATH'))
new_total = result.get('new_total', 0)
print(json.dumps(result, indent=2, ensure_ascii=False))
Path('graphify-out/.graphify_incremental.json').write_text(json.dumps(result, ensure_ascii=False), encoding=\"utf-8\")
deleted = list(result.get('deleted_files', []))
if new_total == 0 and not deleted:
    print('No files changed since last run. Nothing to update.')
    raise SystemExit(0)
if deleted:
    print(f'{len(deleted)} deleted file(s) to prune.')
if new_total > 0:
    print(f'{new_total} new/changed file(s) to re-extract.')
"
```

Then populate `.graphify_detect.json` so Steps 3A–6 (which read it unconditionally) see the right state for an incremental run. `files` carries the changed subset (drives Step 3A AST + Step 3B0 cache check on only what changed); `all_files` carries the full corpus for any step that needs corpus-wide context:

```bash
$(cat graphify-out/.graphify_python) -c "
import json
from pathlib import Path
r = json.loads(Path('graphify-out/.graphify_incremental.json').read_text(encoding=\"utf-8\"))
Path('graphify-out/.graphify_detect.json').write_text(json.dumps({
    'files': r.get('new_files', {}),
    'all_files': r.get('files', {}),
    'total_files': r.get('new_total', 0),
    'total_words': r.get('total_words', 0),
    'skipped_sensitive': r.get('skipped_sensitive', []),
    'needs_graph': True,
}, ensure_ascii=False), encoding=\"utf-8\")
"
```

If new files exist, first check whether all changed files are code files:

```bash
$(cat graphify-out/.graphify_python) -c "
import json
from pathlib import Path

result = json.loads(open('graphify-out/.graphify_incremental.json', encoding='utf-8').core.files.read()) if Path('graphify-out/.graphify_incremental.json').exists() else {}
code_exts = {'.py','.ts','.js','.go','.rs','.java','.cpp','.c','.rb','.swift','.kt','.cs','.scala','.php','.cc','.cxx','.hpp','.h','.kts','.lua','.toc','.f','.F','.f90','.F90','.f95','.F95','.f03','.F03','.f08','.F08'}
new_files = result.get('new_files', {})
all_changed = [f for files in new_files.values() for f in files]
code_only = all(Path(f).suffix.lower() in code_exts for f in all_changed)
print('code_only:', code_only)
"
```

If `code_only` is True: print `[graphify update] Code-only changes detected - skipping semantic extraction (no LLM needed)`, run only Step 3A (AST) on the changed files, skip Step 3B entirely (no subagents), then go straight to merge and Steps 4–8.

If `code_only` is False (any changed file is a doc/paper/image): run the full Steps 3A–3C pipeline as normal.


If no new files exist (only deletions), create an empty extraction so the merge step can prune:

```bash
if [ ! -f graphify-out/.graphify_extract.json ]; then
    echo '[graphify update] Only deletions -- creating empty extraction for merge.'
    $(cat graphify-out/.graphify_python) -c "
import json
from pathlib import Path
Path('graphify-out/.graphify_extract.json').write_text(json.dumps({'nodes':[],'edges':[],'hyperedges':[],'input_tokens':0,'output_tokens':0}), encoding='utf-8')
"
fi
```


Then:

```bash
$(cat graphify-out/.graphify_python) -c "
import json
from pathlib import Path
from graphify.build import build_merge
from graphify.detect import save_manifest

# Load new extraction and incremental state
new_extraction = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding=\"utf-8\"))
incremental = json.loads(Path('graphify-out/.graphify_incremental.json').read_text(encoding=\"utf-8\"))
deleted = list(incremental.get('deleted_files', []))
# Also prune old nodes for re-extracted (changed) files before inserting fresh AST.
# Without this, build_merge's dedup pass tries to reconcile old and new versions of
# the same file's nodes and can collapse same-named symbols across files (#1178).
changed = [f for files in incremental.get('new_files', {}).values() for f in files]
prune = list(dict.fromkeys(deleted + changed)) or None

# Use build_merge() — reads graph.json directly without NetworkX round-trip
# so edge direction (calls, implements, imports) is always preserved (#801).
G = build_merge(
    [new_extraction],
    graph_path='graphify-out/graph.json',
    prune_sources=prune,
)
print(f'[graphify update] Merged: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges')

# Write merged result back to .graphify_extract.json so Step 4 sees the full graph
merged_out = {
    'nodes': [{'id': n, **d} for n, d in G.nodes(data=True)],
    'edges': [
        # Explicit source/target last so they win over any stale attrs in d.
        {**{k: val for k, val in d.items() if k not in ('_src', '_tgt', 'source', 'target')},
         'source': d.get('_src', u), 'target': d.get('_tgt', v)}
        for u, v, d in G.edges(data=True)
    ],
    # G.graph["hyperedges"] holds hyperedges from both existing graph.json
    # and new_extraction (build_merge combines them). Falling back to
    # new_extraction only would silently drop prior-run hyperedges (#801).
    'hyperedges': list(G.graph.get('hyperedges', [])),
    'input_tokens': new_extraction.get('input_tokens', 0),
    'output_tokens': new_extraction.get('output_tokens', 0),
}
Path('graphify-out/.graphify_extract.json').write_text(json.dumps(merged_out, ensure_ascii=False), encoding=\"utf-8\")
print(f'[graphify update] Merged extraction written ({len(merged_out[\"nodes\"])} nodes, {len(merged_out[\"edges\"])} edges)')

# Save manifest so next --update diffs against today's state, not the
# prior run's baseline (prevents ghost-node reports on subsequent updates).
save_manifest(incremental['files'])
print('[graphify update] Manifest saved.')
"
```

Then run Steps 4–8 on the merged graph as normal.

After Step 4, show the graph diff:

```bash
$(cat graphify-out/.graphify_python) -c "
import json
from graphify.analyze import graph_diff
from graphify.build import build_from_json
from networkx.readwrite import json_graph
import networkx as nx
from pathlib import Path

# Load old graph (before update) from backup written before merge
old_data = json.loads(Path('graphify-out/.graphify_old.json').read_text(encoding=\"utf-8\")) if Path('graphify-out/.graphify_old.json').exists() else None
new_extract = json.loads(Path('graphify-out/.graphify_extract.json').read_text(encoding=\"utf-8\"))
G_new = build_from_json(new_extract)

if old_data:
    G_old = json_graph.node_link_graph(old_data, edges='links')
    diff = graph_diff(G_old, G_new)
    print(diff['summary'])
    if diff['new_nodes']:
        print('New nodes:', ', '.join(n['label'] for n in diff['new_nodes'][:5]))
    if diff['new_edges']:
        print('New edges:', len(diff['new_edges']))
"
```

Before the merge step, save the old graph: `cp graphify-out/graph.json graphify-out/.graphify_old.json`
Clean up after: `rm -f graphify-out/.graphify_old.json`

---

## For --cluster-only

Skip Steps 1–3. Re-run clustering on the existing graph:

```bash
graphify cluster-only .
```

Then run Steps 5–9 as normal (label communities, generate viz, benchmark, clean up, report).
