#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_pdf_metadata.py — проверка подлинности PDF по метаданным.

Ловит признаки правки/подделки скан-копий сертификатов/паспортов изделий:
документ редактировали ПОСЛЕ создания, создан в графическом/PDF-редакторе,
многократная история правок, метка сканера + редактора (правка текста на скане).

Зависит только от pikepdf (есть в базе). Сеть НЕ нужна — работает на любом ПК.

Usage:  python verify_pdf_metadata.py <file.pdf> [file2.pdf ...]
Exit:   0 = по метаданным чисто, 1 = есть флаги, 2 = ошибка чтения/аргументов.
"""
import sys
import re
from datetime import datetime

try:
    import pikepdf
except ImportError:
    print("ОШИБКА: нужен pikepdf (pip install pikepdf)", file=sys.stderr)
    sys.exit(2)

# Наличие в Producer/Creator = повод присмотреться (документ мог редактироваться)
EDITORS = ['photoshop', 'gimp', 'illustrator', 'coreldraw', 'foxit', 'pdfescape',
           'smallpdf', 'ilovepdf', 'sejda', 'pdf-xchange', 'nitro', 'able2extract',
           'pdfelement', 'canva', 'inkscape', 'paint.net', 'libreoffice', 'microsoft word']
SCANNERS = ['scan', 'canon', 'epson', 'kyocera', 'xerox', 'ricoh', 'twain', 'wia', 'mfp']


def parse_pdfdate(v):
    if not v:
        return None
    m = re.search(r'D:(\d{4})(\d{2})?(\d{2})?', str(v))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1))
    except ValueError:
        return None


def check(path):
    try:
        pdf = pikepdf.open(path)
    except Exception as e:
        print(f"  ОШИБКА чтения: {e}")
        return None

    info, flags = {}, []
    docinfo = pdf.docinfo or {}
    for k in ('/Producer', '/Creator', '/Author', '/Title', '/CreationDate', '/ModDate', '/Subject'):
        if k in docinfo:
            info[k] = str(docinfo[k])

    xmp_hist = 0
    try:
        with pdf.open_metadata() as m:
            for key in ('xmp:CreatorTool', 'pdf:Producer', 'xmp:ModifyDate', 'xmp:CreateDate'):
                if key in m:
                    info['xmp:' + key] = str(m[key])
            hist = m.get('xmpMM:History')
            if hist:
                xmp_hist = len(hist) if isinstance(hist, list) else 1
    except Exception:
        pass

    prod = (info.get('/Producer', '') + ' ' + info.get('/Creator', '') +
            ' ' + info.get('xmp:xmp:CreatorTool', '')).lower()

    hit_ed = sorted({e for e in EDITORS if e in prod})
    if hit_ed:
        flags.append(('WARN', f"создан/правлен в редакторе: {', '.join(hit_ed)} — возможна правка содержимого"))

    cd = parse_pdfdate(info.get('/CreationDate'))
    md = parse_pdfdate(info.get('/ModDate'))
    if cd and md and (md - cd).days >= 1:
        flags.append(('WARN', f"изменён ПОСЛЕ создания на {(md - cd).days} дн (Created {cd.date()} -> Modified {md.date()})"))
    if cd and cd.year > datetime.now().year:
        flags.append(('CRIT', f"дата создания в БУДУЩЕМ: {cd.date()}"))

    if xmp_hist > 1:
        flags.append(('WARN', f"XMP история правок: {xmp_hist} событий — многократное редактирование"))

    if any(s in prod for s in SCANNERS) and hit_ed:
        flags.append(('CRIT', "метка сканера + редактора одновременно — возможна правка текста на скане"))

    if not info:
        flags.append(('WARN', "метаданные пусты/вычищены — возможна намеренная зачистка следов"))

    pdf.close()
    return info, flags


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    any_flag = False
    for path in sys.argv[1:]:
        print(f"\n=== {path} ===")
        r = check(path)
        if r is None:
            any_flag = True
            continue
        info, flags = r
        print("Метаданные:")
        for k, v in info.items():
            print(f"  {k} = {v}")
        if not flags:
            print("Флагов подозрительности нет (по метаданным чисто).")
        else:
            any_flag = True
            print("ФЛАГИ:")
            for sev, msg in flags:
                print(f"  [{sev}] {msg}")
        print("Примечание: чистые метаданные != гарантия подлинности. При сомнении — "
              "ELA/визуальная сверка + сверка реквизитов (номер/дата) с реестром АРШИН/Росаккредитации.")
    sys.exit(1 if any_flag else 0)


if __name__ == '__main__':
    main()
