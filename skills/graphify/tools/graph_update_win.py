#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic backbone for `graphify --update` on a Windows hub with a
Cyrillic install path (for example, Codex-base / CYRILLIC-HOST).

Encodes the traps from memory `graphify_update_windows_traps.md` so the rebuild
follows instructions instead of hand-run python. The LLM extraction (SKILL.md
Step 3B subagents) still runs BETWEEN `detect` and `merge` — this script only
does the deterministic glue around it.

Traps handled
-------------
  #1 path     : `.graphify_root` holds a POSIX `/c/Users/...` path that
                Windows-Python cannot resolve -> detect_incremental finds 0
                files -> everything is flagged deleted. `detect` coerces it to
                a native `C:/Users/...` path before scanning.
  #2 encoding : cp1251 console mangles Cyrillic in print(). This module forces
                utf-8 stdout/stderr on import.
  #3 src_file : extraction subagents sometimes put the relative path into
                `source_location` and leave `source_file` null -> orphan nodes,
                300+ "missing source_file" warnings. `merge` relocates such
                paths back into `source_file`.
  #4 prune    : build_merge prunes by exact string match on `source_file`. A
                mix of absolute (legacy) and relative paths makes a relative
                prune-set miss old absolute nodes while pruning the new relative
                ones. `merge` relativizes EVERY source_file (old graph + new
                extraction + prune set) to one form before build_merge.
  #5 stamp    : SKILL.md Step 4 to_json() never stamps built_at_commit, so the
                staleness hook stays red after a by-the-book rebuild. `finalize`
                stamps built_at_commit (default: short HEAD).

Subcommands
-----------
  detect    --root <path>            -> .graphify_incremental.json + .graphify_detect.json
  merge     [--root <path>]          -> normalized + merged .graphify_extract.json
  finalize  [--commit <sha>] [--force] -> graph.json + .graphify_analysis.json

Run from the graph root (the directory that holds graphify-out/). All output
paths are relative to cwd, matching SKILL.md's other steps.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# --- trap #2: force utf-8 IO so Cyrillic survives a cp1251 console ---------
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OUT = Path("graphify-out")
ROOT_MARKER = ".codex"  # Codex-base; everything up to & incl. this becomes the relative anchor
_LINEREF = re.compile(r"^L\d+(-L?\d+)?$")  # source_location line refs we must NOT treat as a path


def _read_json(p: Path, default=None):
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return default


def _write_json(p: Path, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# trap #1: native-path coercion for the scan root
# --------------------------------------------------------------------------
def native_root(raw: str) -> str:
    """`/c/Users/X/.codex` (Git-Bash POSIX) -> `C:/Users/X/.codex` (native).

    Leaves already-native paths untouched. Forward slashes are fine for the
    Windows Python pathlib; we only need a resolvable drive prefix.
    """
    raw = (raw or "").strip().replace("\\", "/")
    m = re.match(r"^/([A-Za-z])/(.*)$", raw)
    if m:
        return f"{m.group(1).upper()}:/{m.group(2)}"
    return raw


def resolve_root(cli_root: str | None) -> str:
    if cli_root:
        return native_root(cli_root)
    saved = OUT / ".graphify_root"
    if saved.exists():
        return native_root(saved.read_text(encoding="utf-8"))
    # last resort: cwd
    return native_root(str(Path.cwd()))


# --------------------------------------------------------------------------
# traps #3, #4: source_file normalization
# --------------------------------------------------------------------------
def relativize(path: str, marker: str = ROOT_MARKER) -> str:
    """Strip everything up to & including the root marker; forward slashes.

    `C:/Users/X/.agents/skills/g/SKILL.md` -> `skills/g/SKILL.md`
    `/c/Users/X/.codex/base/agents/a.md`       -> `agents/a.md`
    `skills/g/SKILL.md` (already relative)  -> unchanged
    """
    if not path:
        return path
    s = str(path).replace("\\", "/")
    needle = f"/{marker}/"
    i = s.find(needle)
    if i != -1:
        s = s[i + len(needle):]
    elif s.startswith(f"{marker}/"):
        s = s[len(marker) + 1:]
    # drop any residual leading drive/anchor or ./
    s = re.sub(r"^[A-Za-z]:/", "", s)
    s = s.lstrip("/")
    if s.startswith("./"):
        s = s[2:]
    return s


def _norm_record(rec: dict, marker: str, stats: dict) -> None:
    """In-place normalize one node/edge/hyperedge record."""
    sf = rec.get("source_file")
    loc = rec.get("source_location")
    # trap #3: path mistakenly parked in source_location, source_file empty
    if (not sf) and loc and not _LINEREF.match(str(loc).strip()):
        # source_location holds something path-like -> recover it
        rec["source_file"] = loc
        rec["source_location"] = None
        sf = rec["source_file"]
        stats["recovered"] += 1
    # trap #4: relativize whatever we ended up with
    if sf:
        new = relativize(sf, marker)
        if new != sf:
            rec["source_file"] = new
            stats["relativized"] += 1


def normalize_extraction(data: dict, marker: str = ROOT_MARKER) -> dict:
    """Normalize source_file across nodes/edges/hyperedges. Returns stats."""
    stats = {"recovered": 0, "relativized": 0}
    for key in ("nodes", "edges", "links", "hyperedges"):
        for rec in data.get(key, []) or []:
            if isinstance(rec, dict):
                _norm_record(rec, marker, stats)
    return stats


# --------------------------------------------------------------------------
# git HEAD (trap #5)
# --------------------------------------------------------------------------
def short_head() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


# ==========================================================================
# detect
# ==========================================================================
def cmd_detect(args) -> int:
    from graphify.detect import detect_incremental
    root = resolve_root(args.root)
    print(f"[detect] scan root (native): {root}")
    result = detect_incremental(Path(root))
    OUT.mkdir(parents=True, exist_ok=True)
    _write_json(OUT / ".graphify_incremental.json", result)

    new_total = result.get("new_total", 0)
    deleted = list(result.get("deleted_files", []))
    if new_total == 0 and not deleted:
        print("[detect] No files changed since last run. Nothing to update.")
        # still write a detect.json so downstream is consistent
    if deleted:
        print(f"[detect] {len(deleted)} deleted file(s) to prune.")
    if new_total > 0:
        print(f"[detect] {new_total} new/changed file(s) to re-extract.")

    # populate .graphify_detect.json exactly as update.md expects
    _write_json(OUT / ".graphify_detect.json", {
        "files": result.get("new_files", {}),
        "all_files": result.get("files", {}),
        "total_files": result.get("new_total", 0),
        "total_words": result.get("total_words", 0),
        "skipped_sensitive": result.get("skipped_sensitive", []),
        "needs_graph": True,
        "scan_root": root,
    })

    # convenience: classify code-only so the orchestrator can skip subagents
    code_exts = {".py", ".ts", ".js", ".go", ".rs", ".java", ".cpp", ".c", ".rb",
                 ".swift", ".kt", ".cs", ".scala", ".php", ".cc", ".cxx", ".hpp",
                 ".h", ".kts", ".lua"}
    changed = [f for files in result.get("new_files", {}).values() for f in files]
    code_only = bool(changed) and all(Path(f).suffix.lower() in code_exts for f in changed)
    print(f"[detect] code_only: {code_only}")
    return 0


# ==========================================================================
# merge  (manual controlled merge — NOT build_merge)
# ==========================================================================
# Why not graphify.build.build_merge: it does build(old + new) and THEN prunes
# by source_file on the *combined* graph, so prune_sources=[changed_file] removes
# the freshly re-extracted nodes too — the changed file's update vanishes. The
# manual flow prunes ONLY the old graph, then layers new on top (new wins on id
# collision). This is the controlled rebuild prescribed in
# memory/graphify_update_windows_traps.md.
def cmd_merge(args) -> int:
    from graphify.detect import save_manifest
    marker = args.marker

    extract_p = OUT / ".graphify_extract.json"
    incr_p = OUT / ".graphify_incremental.json"
    graph_p = OUT / "graph.json"

    new_extraction = _read_json(extract_p, {"nodes": [], "edges": [], "hyperedges": [],
                                            "input_tokens": 0, "output_tokens": 0})
    incremental = _read_json(incr_p, {})

    # trap #3/#4: normalize the freshly-extracted nodes/edges first
    s_new = normalize_extraction(new_extraction, marker)
    print(f"[merge] new extraction: recovered {s_new['recovered']} source_file from "
          f"source_location, relativized {s_new['relativized']}")

    # load + normalize the existing graph (trap #4: one form for prune matching)
    old_graph = _read_json(graph_p, {"nodes": [], "links": [], "hyperedges": []})
    s_old = normalize_extraction(old_graph, marker)
    old_nodes = list(old_graph.get("nodes", []))
    old_edges = list(old_graph.get("links", old_graph.get("edges", [])))
    old_hyper = list(old_graph.get("hyperedges", []))
    print(f"[merge] existing graph: {len(old_nodes)} nodes, {len(old_edges)} edges "
          f"(normalized: recovered {s_old['recovered']}, relativized {s_old['relativized']})")

    # prune set: deleted ∪ changed, relativized to the same anchor
    deleted = list(incremental.get("deleted_files", []))
    changed = [f for files in incremental.get("new_files", {}).values() for f in files]
    prune = {relativize(p, marker) for p in (deleted + changed) if p}
    print(f"[merge] prune set: {len(prune)} source(s) (deleted+changed, relative)")

    # keep old nodes whose source_file is NOT pruned
    kept_old = [n for n in old_nodes if n.get("source_file") not in prune]
    pruned_n = len(old_nodes) - len(kept_old)
    print(f"[merge] pruned {pruned_n} stale node(s) from old graph")

    # combine: new first (wins on id collision), then surviving old; dedup by id
    seen, combined = set(), []
    for n in list(new_extraction.get("nodes", [])) + kept_old:
        nid = n.get("id")
        if nid and nid not in seen:
            seen.add(nid)
            combined.append(n)
    node_ids = seen

    # edges: keep old edges not pruned and with both endpoints alive; add new edges
    # whose endpoints survive; dedup by (source, target, relation)
    def _alive(e):
        return e.get("source") in node_ids and e.get("target") in node_ids
    kept_old_edges = [e for e in old_edges
                      if e.get("source_file") not in prune and _alive(e)]
    new_edges = [e for e in new_extraction.get("edges", []) if _alive(e)]
    eseen, combined_edges = set(), []
    for e in new_edges + kept_old_edges:
        key = (e.get("source"), e.get("target"), e.get("relation"))
        if key not in eseen:
            eseen.add(key)
            combined_edges.append(e)

    # hyperedges: keep those whose member nodes all survive; dedup by id
    all_hyper = list(new_extraction.get("hyperedges", [])) + old_hyper
    hseen, combined_hyper = set(), []
    for h in all_hyper:
        hid = h.get("id")
        members = h.get("nodes", [])
        if members and all(m in node_ids for m in members) and hid not in hseen:
            hseen.add(hid)
            combined_hyper.append(h)

    merged = {
        "nodes": combined,
        "edges": combined_edges,
        "hyperedges": combined_hyper,
        "input_tokens": new_extraction.get("input_tokens", 0),
        "output_tokens": new_extraction.get("output_tokens", 0),
    }
    _write_json(extract_p, merged)
    print(f"[merge] merged extraction written ({len(combined)} nodes, "
          f"{len(combined_edges)} edges, {len(combined_hyper)} hyperedges)")

    # save manifest so the NEXT --update diffs against today's state
    if incremental.get("files"):
        save_manifest(incremental["files"])
        print("[merge] manifest saved.")
    return 0


# ==========================================================================
# finalize  (replaces SKILL.md Step 4 for the windows/Codex-base path)
# ==========================================================================
def cmd_finalize(args) -> int:
    from graphify.build import build_from_json
    from graphify.cluster import cluster, score_all
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.report import generate
    from graphify.export import to_json

    extraction = _read_json(OUT / ".graphify_extract.json")
    detection = _read_json(OUT / ".graphify_detect.json", {})
    if not extraction:
        print("[finalize] ERROR: .graphify_extract.json missing — run merge first.")
        return 1

    G = build_from_json(extraction, directed=bool(args.directed))
    if G.number_of_nodes() == 0:
        print("[finalize] ERROR: graph is empty — extraction produced no nodes.")
        return 1
    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: "Community " + str(cid) for cid in communities}
    questions = suggest_questions(G, communities, labels)
    tokens = {"input": extraction.get("input_tokens", 0),
              "output": extraction.get("output_tokens", 0)}

    report = generate(G, communities, cohesion, labels, gods, surprises,
                      detection, tokens, ".", suggested_questions=questions)
    (OUT / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")

    commit = args.commit or short_head()
    # trap #5: stamp built_at_commit so the staleness hook can reset.
    ok = to_json(G, communities, str(OUT / "graph.json"),
                 force=bool(args.force), built_at_commit=commit)
    if not ok:
        # net-loss guard tripped — make the override explicit, never silent.
        print("[finalize] to_json REFUSED: net node loss vs existing graph.")
        print("[finalize] Inspect the diff. If the loss is expected, re-run "
              "`finalize --force`.")
        return 2

    _write_json(OUT / ".graphify_analysis.json", {
        "communities": {str(k): v for k, v in communities.items()},
        "cohesion": {str(k): v for k, v in cohesion.items()},
        "gods": gods,
        "surprises": surprises,
        "questions": questions,
    })
    print(f"[finalize] graph.json written: {G.number_of_nodes()} nodes, "
          f"{G.number_of_edges()} edges, {len(communities)} communities, "
          f"built_at_commit={commit}")
    print("[finalize] Next: SKILL.md Step 5 (label communities) reads "
          ".graphify_analysis.json; then Step 6 viz + Step 9 manifest/cleanup.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Windows/Codex-base graphify --update backbone")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detect", help="native-path detect_incremental (traps #1,#2)")
    d.add_argument("--root", default=None, help="scan root; default reads .graphify_root and coerces /c/->C:/")
    d.set_defaults(func=cmd_detect)

    m = sub.add_parser("merge", help="normalize source_file + build_merge (traps #2,#3,#4)")
    m.add_argument("--marker", default=ROOT_MARKER, help="relative anchor dir name (default .codex)")
    m.set_defaults(func=cmd_merge)

    f = sub.add_parser("finalize", help="build/cluster/to_json with commit stamp (trap #5)")
    f.add_argument("--commit", default=None, help="built_at_commit to stamp; default short HEAD")
    f.add_argument("--force", action="store_true", help="override net-loss guard in to_json")
    f.add_argument("--directed", action="store_true", help="build a directed graph")
    f.set_defaults(func=cmd_finalize)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
