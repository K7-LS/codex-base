#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-call navigation query over the Codex-base graph. No manual vocab ritual.

The bare `graphify query` CLI matches case-folded substring + IDF with no stemming,
synonyms, or cross-language (references/query.md) — so a Russian question against the
graph collapses to 0 hits unless you hand-run the extract→pick≤12→join expansion. That
friction is why the graph gets skipped in favour of grep.

This wrapper removes the ritual: it scores nodes directly against name/label/description.
The skeleton nodes carry the **Russian frontmatter description** (живые фразы / triggers),
so a Russian query matches natively — no translit, no token-picking. Output is the entry
file(s) + their 1-hop connections; truth stays in the source file (cite source_file).

Usage:
  graph_query.py "<question>" [--graph <file>] [--top N] [--depth 1] [--kind agent,skill] [--json]
Default graph: graphify-out/skeleton.json (trusted, always-fresh), else graph.json.

Run from base root (~/.codex). Always utf-8.
"""
import argparse
import io
import json
import os
import re
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
_CYR = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i',
    'й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t',
    'у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ъ':'','ы':'y','ь':'',
    'э':'e','ю':'yu','я':'ya',
}


def translit(s):
    return "".join(_CYR.get(ch, ch) for ch in s.lower())


def tokens(s):
    # keep internal hyphens/digits so domain codes survive (КС-2, КС-3, П1, В1, ТОРГ-12).
    out = []
    for t in re.split(r"[^\w-]+", s.lower(), flags=re.UNICODE):
        t = t.strip("-")
        if t and (len(t) >= 3 or any(c.isdigit() for c in t)):
            out.append(t)
    return out


def load_graph(path):
    g = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = g.get("nodes", [])
    links = g.get("links", g.get("edges", []))
    return nodes, links


def haystacks(n):
    """Return (name_h, label_h, body_h) lowercased, with transliterated variants appended."""
    name = str(n.get("name") or "")
    label = str(n.get("label") or "")
    body = " ".join(str(n.get(k) or "") for k in ("description", "rationale"))
    def mk(x):
        x = x.lower()
        return x + " " + translit(x)
    return mk(name), mk(label), mk(body)


def score_node(n, qtokens, qphrase):
    name_h, label_h, body_h = haystacks(n)
    sc = 0
    for t in qtokens:
        tt = translit(t)
        if t in name_h or tt in name_h:
            sc += 3
        elif t in label_h or tt in label_h:
            sc += 2
        elif t in body_h or tt in body_h:
            sc += 1
    # phrase bonus: full query (or its translit) as a substring of description
    if qphrase and (qphrase in body_h or translit(qphrase) in body_h):
        sc += 3
    return sc


def main(argv=None):
    ap = argparse.ArgumentParser(description="One-call navigation query over Codex-base graph.")
    ap.add_argument("question", help="natural-language question (RU or EN)")
    ap.add_argument("--graph", default=None, help="graph json (default skeleton.json, else graph.json)")
    ap.add_argument("--top", type=int, default=6, help="number of entry nodes (default 6)")
    ap.add_argument("--depth", type=int, default=1, help="neighbor hops to show (0 or 1)")
    ap.add_argument("--kind", default=None, help="filter to kinds, comma-sep (agent,skill,memory,rule,...)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    path = args.graph
    if not path:
        path = OUT / "skeleton.json"
        if not path.exists():
            path = OUT / "graph.json"
    if not Path(path).exists():
        print(f"[query] no graph at {path}. Build it first (skeleton_build.py).", file=sys.stderr)
        return 1

    nodes, links = load_graph(path)
    by_id = {n["id"]: n for n in nodes}
    kinds = set(args.kind.split(",")) if args.kind else None

    qtokens = tokens(args.question)
    qphrase = " ".join(args.question.lower().split())
    scored = []
    for n in nodes:
        if kinds and n.get("kind") not in kinds:
            continue
        sc = score_node(n, qtokens, qphrase)
        if sc > 0:
            scored.append((sc, n))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("name") or x[1].get("label"))))
    top = scored[: args.top]

    # 1-hop neighbors
    def neighbors(nid):
        out = []
        for e in links:
            if e.get("source") == nid and e.get("target") in by_id:
                out.append((e["target"], e.get("relation")))
            elif e.get("target") == nid and e.get("source") in by_id:
                out.append((e["source"], e.get("relation")))
        # de-dup, keep order
        seen, res = set(), []
        for t, r in out:
            if t not in seen:
                seen.add(t)
                res.append((t, r))
        return res

    def disp(n):
        return n.get("name") or n.get("label") or n.get("id")

    if args.json:
        result = []
        for sc, n in top:
            entry = {"id": n["id"], "kind": n.get("kind"), "name": disp(n),
                     "source_file": n.get("source_file"), "score": sc}
            if args.depth >= 1:
                entry["connections"] = [
                    {"id": t, "name": disp(by_id[t]), "relation": r}
                    for t, r in neighbors(n["id"])[:12]
                ]
            result.append(entry)
        print(json.dumps({"question": args.question, "graph": str(path), "matches": result},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"Query: {args.question}")
    print(f"Graph: {path}  ({len(nodes)} nodes)")
    if not top:
        print("No matches. The graph has no relevant vocabulary for this question — "
              "fall back to grep / ask.")
        return 0
    print("Entry points (read the source file to verify — graph is the map, file is truth):")
    for sc, n in top:
        print(f"  [{sc:>2}] {n.get('kind','?')}: {disp(n)}  —  {n.get('source_file')}")
        if args.depth >= 1:
            nb = neighbors(n["id"])
            if nb:
                shown = ", ".join(f"{disp(by_id[t])}" for t, r in nb[:10])
                more = f" (+{len(nb)-10})" if len(nb) > 10 else ""
                print(f"        connected: {shown}{more}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
