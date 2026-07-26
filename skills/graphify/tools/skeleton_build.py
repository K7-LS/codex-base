#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic always-fresh navigation skeleton for Codex-base. **0 LLM tokens.**

Builds the navigational backbone of the base from structural signals only — no model
call — so it can run on a post-commit hook on every PC and stay always-fresh. This is
the trusted core of the graph; the LLM semantic layer (graph_update_win.py) is optional
enrichment on top.

Canonical entity nodes (one per base entity, predictable id):
  agent/skill/memory/block/chain/command/rule(AGENTS.md section)/mcp/tool
Edges from explicit signals:
  [[wikilinks]] · name mentions of agents/skills · skill→tools containment ·
  AGENTS.md section → mentioned entity

This fixes the LLM-extraction fragmentation (cross-refs became orphan
"X (referenced by Y)" concept nodes with non-canonical ids): here a mention of
"norm-lookup" inside designer.md becomes a real edge agent__designer → agent__norm_lookup.

Run from the base root (~/.codex). Writes graphify-out/skeleton.json (node-link),
stamped with built_at_commit=HEAD. Always utf-8.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

OUT = Path("graphify-out")

# cyrillic→latin so canonical ids stay [a-z0-9_] (graphify id rule); the original
# name is preserved on node['name'] and used for mention-matching.
_CYR = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
    'э':'e','ю':'yu','я':'ya',
}


def translit(s: str) -> str:
    return "".join(_CYR.get(ch, ch) for ch in s.lower())


def slug(name: str) -> str:
    s = translit(name)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "x"


def node_id(kind: str, name: str) -> str:
    return f"{kind}__{slug(name)}"


# --- frontmatter ----------------------------------------------------------
# yaml-free, block-scalar-aware parser. We do NOT depend on pyyaml: it is absent on
# many consumer PCs (the skeleton runs everywhere via post-commit). Agents use
# `description: |` (literal) and skills use `description: >` (folded) — both must work.
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_BLOCK_MARKERS = {"|", "|-", "|+", ">", ">-", ">+", ""}


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    lines = m.group(1).split("\n")
    d, i = {}, 0
    while i < len(lines):
        km = _KEY_RE.match(lines[i])
        if not km:
            i += 1
            continue
        key, rest = km.group(1), km.group(2).strip()
        if rest in _BLOCK_MARKERS:
            # block scalar: gather following lines until the next top-level key
            block, j = [], i + 1
            while j < len(lines):
                l = lines[j]
                if l.strip() == "":
                    block.append("")
                    j += 1
                    continue
                if not l.startswith((" ", "\t")) and _KEY_RE.match(l):
                    break  # next top-level key
                block.append(l)
                j += 1
            d[key] = " ".join(s.strip() for s in block if s.strip())
            i = j
        else:
            d[key] = rest.strip().strip("\"'")
            i += 1
    return d


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return p.read_text(encoding="utf-8", errors="replace")


def rel(p: Path, root: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


# --- entity collection ----------------------------------------------------
SKIP_AGENTS = {"_TEMPLATE.md", "agents.md", "README.md"}


def collect(root: Path):
    """Return (nodes_by_id, name_index). name_index maps a lowercased entity name
    -> node id, for mention resolution. Longer names first when scanning."""
    nodes = {}
    name_index = {}

    def add(kind, name, src, file_type="document", **attrs):
        nid = node_id(kind, name)
        if nid not in nodes:
            nodes[nid] = {
                "id": nid, "label": f"{name} ({kind})", "kind": kind, "name": name,
                "file_type": file_type, "source_file": src, "source_location": None,
                **attrs,
            }
            name_index[name.lower()] = nid
        return nid

    # agents
    ad = root / "agents"
    if ad.is_dir():
        for f in sorted(ad.glob("*.md")):
            if f.name in SKIP_AGENTS:
                continue
            fm = parse_frontmatter(read(f))
            nm = (fm.get("name") or f.stem) if isinstance(fm.get("name"), str) else f.stem
            add("agent", nm, rel(f, root), description=_clip(fm.get("description")))

    # skills (folder name is the skill name)
    sd = root / "skills"
    if sd.is_dir():
        for sk in sorted(p for p in sd.iterdir() if p.is_dir()):
            skill_md = sk / "SKILL.md"
            if not skill_md.exists():
                continue
            fm = parse_frontmatter(read(skill_md))
            nm = sk.name
            sid = add("skill", nm, rel(skill_md, root), description=_clip(fm.get("description")))
            # tools/scripts as tool nodes + contains edge later
            for sub in ("tools", "scripts"):
                td = sk / sub
                if td.is_dir():
                    for tf in sorted(td.rglob("*")):
                        if tf.is_file() and tf.suffix in (".py", ".ps1", ".lsp", ".js", ".sh"):
                            tid = add("tool", rel(tf, root), rel(tf, root), file_type="code")
                            nodes[tid]["_parent_skill"] = sid

    # memory (base only, not projects/)
    md = root / "memory"
    if md.is_dir():
        for f in sorted(md.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            fm = parse_frontmatter(read(f))
            add("memory", f.stem, rel(f, root), description=_clip(fm.get("description")))

    # blocks
    bd = root / "blocks"
    if bd.is_dir():
        for b in sorted(p for p in bd.iterdir() if p.is_dir()):
            bm = b / "BLOCK.md"
            if bm.exists():
                add("block", b.name, rel(bm, root))

    # chains
    cd = root / "chains"
    if cd.is_dir():
        for f in sorted(cd.glob("*.md")):
            if f.name == "README.md":
                continue
            add("chain", f.stem, rel(f, root))

    # commands
    cmd = root / "commands"
    if cmd.is_dir():
        for f in sorted(cmd.glob("*.md")):
            if f.name == "README.md":
                continue
            add("command", f.stem, rel(f, root))

    # AGENTS.md sections → rule nodes
    Codex = root / "AGENTS.md"
    if Codex.exists():
        txt = read(Codex)
        for m in re.finditer(r"^##+\s+(.+?)\s*$", txt, re.MULTILINE):
            title = m.group(1).strip()
            add("rule", title, "AGENTS.md", _section=title)

    # mcp servers
    man = root / "mcp-manifest.json"
    if man.exists():
        try:
            mj = json.loads(read(man))
            servers = mj.get("mcp_servers") or mj.get("servers") or mj.get("mcpServers") or {}
            names = servers.keys() if isinstance(servers, dict) else \
                [s.get("name") for s in servers if isinstance(s, dict)]
            for nm in names:
                if nm:
                    add("mcp", str(nm), "mcp-manifest.json")
        except Exception as e:
            print(f"[skeleton] mcp-manifest parse skipped: {e}", file=sys.stderr)

    return nodes, name_index


def _clip(v, n=2000):
    # description is the PRIMARY search signal for graph_query — keep it (near-)full,
    # not a 300-char teaser (the trigger phrases often sit in the 2nd paragraph).
    if not isinstance(v, str):
        return None
    v = " ".join(v.split())
    return v[:n]


# --- edges ----------------------------------------------------------------
def build_edges(root: Path, nodes: dict, name_index: dict):
    edges = []
    seen = set()

    def emit(src, tgt, relation, source_file):
        if not src or not tgt or src == tgt:
            return
        key = (src, tgt, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append({
            "source": src, "target": tgt, "relation": relation,
            "confidence": "EXTRACTED", "confidence_score": 1.0,
            "source_file": source_file, "source_location": None, "weight": 1.0,
        })

    # mention matcher: alternation of entity names, longest first, word-bounded.
    # Use names with length>=4 to cut noise; keep hyphenated/cyrillic intact.
    matchable = sorted([n for n in name_index if len(n) >= 4], key=len, reverse=True)
    if matchable:
        pat = re.compile(r"(?<![\w-])(" + "|".join(re.escape(m) for m in matchable) +
                         r")(?![\w-])", re.IGNORECASE)
    else:
        pat = None

    wiki = re.compile(r"\[\[([^\]|#]+)")

    # iterate file-backed entities (skip rule/mcp/tool which have no own body to scan,
    # except AGENTS.md sections handled separately)
    for nid, n in nodes.items():
        if n["kind"] in ("tool", "mcp"):
            continue
        sf = n["source_file"]
        if n["kind"] == "rule":
            continue  # handled in the AGENTS.md pass below
        p = root / sf
        if not p.exists():
            continue
        body = read(p)

        # wikilinks
        for w in wiki.findall(body):
            tgt = name_index.get(w.strip().lower())
            emit(nid, tgt, "references", sf)

        # name mentions
        if pat:
            for mm in pat.finditer(body):
                tgt = name_index.get(mm.group(1).lower())
                emit(nid, tgt, "references", sf)

        # skill → its tools
        if n["kind"] == "skill":
            for tid, tn in nodes.items():
                if tn.get("_parent_skill") == nid:
                    emit(nid, tid, "contains", sf)

    # AGENTS.md sections: scan each section's text for mentions → rule__section -> entity
    Codex = root / "AGENTS.md"
    if Codex.exists() and pat:
        txt = read(Codex)
        parts = re.split(r"(^##+\s+.+?\s*$)", txt, flags=re.MULTILINE)
        # parts: [pre, head1, body1, head2, body2, ...]
        for i in range(1, len(parts) - 1, 2):
            head = parts[i]
            sect_body = parts[i + 1] if i + 1 < len(parts) else ""
            title = re.sub(r"^##+\s+", "", head).strip()
            rid = node_id("rule", title)
            if rid not in nodes:
                continue
            for mm in pat.finditer(sect_body):
                tgt = name_index.get(mm.group(1).lower())
                emit(rid, tgt, "references", "AGENTS.md")

    return edges


# --- main -----------------------------------------------------------------
def short_head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip() or None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic Codex-base navigation skeleton (0 LLM).")
    ap.add_argument("--root", default=".", help="base root (default cwd)")
    ap.add_argument("--out", default=str(OUT / "skeleton.json"), help="output node-link json")
    ap.add_argument("--commit", default=None, help="built_at_commit (default short HEAD)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    nodes, name_index = collect(root)
    edges = build_edges(root, nodes, name_index)

    # strip internal helper keys
    for n in nodes.values():
        n.pop("_parent_skill", None)
        n.pop("_section", None)

    from collections import Counter
    kinds = Counter(n["kind"] for n in nodes.values())
    rels = Counter(e["relation"] for e in edges)
    print(f"[skeleton] nodes: {len(nodes)} {dict(kinds)}")
    print(f"[skeleton] edges: {len(edges)} {dict(rels)}")

    # node-link JSON written DIRECTLY (no graphify package dependency) so the skeleton
    # builds on ANY PC with bare python — a consumer's SessionStart hook needs no
    # `graphifyy` install. graph_query.py reads nodes + links; communities aren't used.
    commit = args.commit or short_head()
    node_list = list(nodes.values())
    graph_obj = {
        "directed": True, "multigraph": False, "graph": {},
        "nodes": node_list,
        "links": edges,
        "hyperedges": [],
        "built_at_commit": commit,
        "layer": "skeleton",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(graph_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[skeleton] wrote {args.out}: {len(node_list)} nodes, {len(edges)} edges, "
          f"built_at_commit={commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
