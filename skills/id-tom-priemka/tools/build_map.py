# -*- coding: utf-8 -*-
"""Генератор эталонной карты тома ИД (страница → раздел) из лога сборки assemble_pdf.
Лог содержит строки с числом страниц блока в скобках "(N)" и метками в "[...]";
секции помечены "=== ИМЯ ===". Накопление offset даёт диапазоны страниц.

Использование:
    python build_map.py "<путь к assemble_log.txt>"
Вывод (stdout, utf-8) — карту "start-end: метка", готовую вставить в args.map workflow.
Карту далее ДОПОЛНИТЬ вручную: что конкретно ожидается (актуальное оборуд., номера актов),
и отдельно собрать список ЗАПРЕЩЁННОГО (старое/удалённое) из FACTS/свода замен объекта.
"""
import sys, re, io

def build(log_text):
    out = []
    page = 0  # 0 = ещё не начато; страницы 1-based
    for ln in log_text.splitlines():
        s = ln.strip()
        if s.startswith("==="):
            out.append(("SEC", s.strip("= ").strip(), page + 1))
            continue
        m = re.search(r"\((\d+)\)", s)
        if not m:
            continue
        n = int(m.group(1))
        b = re.search(r"\[([^\]]+)\]", s)
        if b:
            label = b.group(1).split("←")[0].strip()
        else:
            label = re.sub(r"\s*\(\d+\).*$", "", s).strip()
        start, end = page + 1, page + n
        out.append(("BLK", label, start, end))
        page += n
    # рендер карты
    res = io.StringIO()
    res.write(f"# Эталонная карта тома ({page} стр.)\n")
    for item in out:
        if item[0] == "SEC":
            res.write(f"\n## {item[1]} (с стр.{item[2]})\n")
        else:
            _, label, a, b = item
            rng = f"{a}" if a == b else f"{a}-{b}"
            res.write(f"{rng}: {label}\n")
    return res.getvalue(), page

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python build_map.py <assemble_log.txt>"); sys.exit(1)
    txt = open(sys.argv[1], encoding="utf-8").read()
    card, total = build(txt)
    sys.stdout.reconfigure(encoding="utf-8")
    print(card)
    print(f"\n# ИТОГО {total} стр. Дополни карту вручную (что именно ожидается) + собери список forbidden.", file=sys.stderr)
