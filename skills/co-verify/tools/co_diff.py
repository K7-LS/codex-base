# -*- coding: utf-8 -*-
"""
co_diff — детерминированный diff СО двух редакций проектного PDF (старая ↔ новая).
Нумерация позиций между редакциями могла смениться, поэтому матчинг — по
последовательности наименований (не по номеру). Выдаёт: добавлено / убрано /
изменено количество / изменена единица.

Использование:
  python co_diff.py --old <старое_СО.pdf> --new <новое_СО.pdf> [--json]
"""
import sys, os, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import co_engine as E

def diff(old_pdf, new_pdf):
    OLD = E.extract_co(old_pdf); NEW = E.extract_co(new_pdf)
    pairs, only_old, only_new = E.pair_by_name_sequence(OLD, NEW)
    res = {'old_n': len(OLD), 'new_n': len(NEW), 'qty': [], 'unit': [], 'added': [], 'removed': []}
    for a, b in pairs:
        t = E.tag(b['co'], b['pos'])
        if E.norm_qty(a['qty']) != E.norm_qty(b['qty']):
            res['qty'].append({'pos': t, 'name': b['name'], 'old': a['qty'], 'new': b['qty'], 'unit': b['unit']})
        if E.norm_unit(a['unit']) != E.norm_unit(b['unit']):
            res['unit'].append({'pos': t, 'name': b['name'], 'old': a['unit'], 'new': b['unit']})
    res['added'] = [{'pos': E.tag(b['co'], b['pos']), 'name': b['name'], 'qty': b['qty'], 'unit': b['unit']} for b in only_new]
    res['removed'] = [{'pos': E.tag(a['co'], a['pos']), 'name': a['name'], 'qty': a['qty'], 'unit': a['unit']} for a in only_old]
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    d = diff(a.old, a.new)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1)); return
    ch = len(d['qty']) + len(d['unit']) + len(d['added']) + len(d['removed'])
    print(f"позиций old={d['old_n']} new={d['new_n']} | изменений={ch}")
    for x in d['qty']:     print(f"  [КОЛ-ВО] {x['pos']:10} {x['old']} -> {x['new']} {x['unit']}  «{x['name'][:50]}»")
    for x in d['unit']:    print(f"  [ЕД]     {x['pos']:10} '{x['old']}' -> '{x['new']}'  «{x['name'][:46]}»")
    for x in d['added']:   print(f"  [+ДОБАВ] {x['pos']:10} {x['qty']} {x['unit']}  «{x['name'][:50]}»")
    for x in d['removed']: print(f"  [-УБРАН] {x['pos']:10} {x['qty']} {x['unit']}  «{x['name'][:50]}»")

if __name__ == "__main__":
    main()
