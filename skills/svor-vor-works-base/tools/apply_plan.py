# -*- coding: utf-8 -*-
"""Применение плана правок через win32com (НЕ openpyxl — относительные формулы H/I СВОР).

  python apply_plan.py --plan plan.json --blocks blocks.json --dst-suffix " v2"
Файл берётся по blocks.json['path'] (исходник), копируется в папку "<родитель><dst-suffix>"
(рядом с исходной), правки строго снизу вверх. При удалении строк значения №/B/C из якоря
merge переносятся в новую верхнюю строку блока (иначе теряются).
"""
import json, os, shutil, time, argparse
import win32com.client as win32

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', default='plan.json')
    ap.add_argument('--blocks', default='blocks.json')
    ap.add_argument('--dst-suffix', default=' v2', help='суффикс к имени папки исходников')
    ap.add_argument('--only', default=None, help='подстрока имени файла (пилот)')
    args = ap.parse_args()

    plan = json.load(open(args.plan, encoding='utf-8'))
    blocks = json.load(open(args.blocks, encoding='utf-8'))
    path_by_file = {(b['kind'], b['file']): b['path'] for b in blocks}

    targets = []
    for fp in plan:
        if args.only and args.only.lower() not in fp['file'].lower():
            continue
        src = path_by_file[(fp['kind'], fp['file'])]
        dst_dir = os.path.dirname(src) + args.dst_suffix
        os.makedirs(dst_dir, exist_ok=True)
        targets.append((fp, src, os.path.join(dst_dir, fp['file'])))

    excel = win32.DispatchEx('Excel.Application')
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        excel.ScreenUpdating = False
        excel.EnableEvents = False
        for fp, src, dst in targets:
            t0 = time.time()
            shutil.copy2(src, dst)
            wb = excel.Workbooks.Open(dst, UpdateLinks=0)
            try:
                calc_prev = excel.Calculation
                excel.Calculation = -4135  # manual
            except Exception:
                calc_prev = None
            ws = wb.Worksheets(fp['sheet'])
            n_rep = n_del = 0
            for a in sorted(fp['actions'], key=lambda a: -a['rows'][0]):
                if a['action'] == 'replace':
                    for r in a['rows']:
                        ws.Cells(r, 4).Value = a['new_text']
                    n_rep += 1
                else:
                    r1, r2 = a['rows'][0], a['rows'][-1]
                    ws.Rows(f'{r1}:{r2}').Delete()
                    ws.Cells(r1, 1).Value = a['carry'].get('A')
                    if 'B' in a['carry']:
                        ws.Cells(r1, 2).Value = a['carry']['B']
                    if 'C' in a['carry']:
                        ws.Cells(r1, 3).Value = a['carry']['C']
                    n_del += 1
            if calc_prev is not None:
                excel.Calculation = calc_prev
            wb.Save()
            wb.Close(SaveChanges=False)
            print(f"OK {fp['kind']:4s} {fp['file'][:55]:57s} rep={n_rep} del={n_del} {time.time()-t0:.0f}s",
                  flush=True)
    finally:
        excel.Quit()
    print('DONE')

if __name__ == '__main__':
    main()
