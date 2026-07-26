# -*- coding: utf-8 -*-
"""
co_engine — универсальный движок координатного извлечения и сверки спецификаций
оборудования (СО) из ПРОЕКТНЫХ PDF (ВОР / спецификации / ведомости).

Не привязан к конкретному проекту: пути и источники данных передаются вызывающим.
Зависимости: PyMuPDF (fitz). Опц.: openpyxl (для чтения xlsx как источника данных).

Главная идея: таблицы СО в проектных PDF читаются НЕ визуальным рендером, а
координатно — page.find_tables(strategy="lines") строит сетку по векторным линиям
таблицы и раскладывает каждое слово в правильную ячейку. Детерминированно, дёшево,
точнее глаза на ВЕКТОРНОМ PDF. Рендер — только для адъюдикации единичных спорных ячеек.

Обойдённые ловушки СО-листов:
 - страницы А3 повёрнуты на 90° (find_tables справляется сам);
 - переносы в шапке («Коли-\nчество», «Единица измере-\nния») — дегифенизация;
 - разные шапки («Поз.» vs «Позиция»);
 - название в строках данных уезжает на ±1 колонку относительно шапки → название =
   склейка ячеек от позиции до колонки тип/код;
 - безномерные строки в PDF — берём по наличию кол-ва, не по номеру;
 - опечатки/рестарт номеров в мульти-СО → матчинг гибридный (позиция + название +
   нормализация гомоглифов лат/кир), не только по номеру.
"""
import re, difflib
import fitz

POS_RE = re.compile(r'^\s*\d+(?:\.\d+)*[а-яёa-z]?\s*$', re.IGNORECASE)
CO_RE = re.compile(r'\.СО(\d*)\b')  # маркер спецификации в шифре: ...СО, ...СО1, ...СО2

_HOMO = str.maketrans({
    'а':'a','в':'b','е':'e','к':'k','м':'m','н':'h','о':'o','р':'p',
    'с':'c','т':'t','у':'y','х':'x','ё':'e','і':'i','ј':'j','ѕ':'s'})


def norm_name(s):
    s = (s or '').lower().translate(_HOMO)
    s = re.sub(r'[^a-zа-я0-9]+', ' ', s)
    return ' '.join(s.split())[:90]

def norm_unit(u):
    return re.sub(r'[.\s]', '', (u or '').lower())

def norm_qty(q):
    if q is None: return None
    s = str(q).strip().replace(' ', '').replace(' ', '').replace(',', '.')
    if s == '': return None
    try:
        f = float(s); return int(f) if f == int(f) else f
    except ValueError:
        return s

def _dehyph(s):
    s = (s or "").lower().replace("\n", " ")
    return " ".join(re.sub(r'-\s+', '', s).split())

def is_co_page(txt):
    return (("Поз." in txt or "Позиция" in txt)
            and "Кол." in txt and "Наименование и техническ" in txt)

def co_of_page(txt):
    m = CO_RE.findall(txt)
    if not m: return ''
    nums = [x for x in m if x != '']
    return nums[-1] if nums else ''

def map_columns(data):
    ncols = max((len(r) for r in data), default=0)
    for ri, row in enumerate(data[:8]):
        joined = _dehyph(" ".join((c or "") for c in row))
        if "поз" in joined and "кол" in joined and "наименование и техническ" in joined:
            colhdr = [_dehyph(c) for c in (list(row) + [""] * (ncols - len(row)))]
            def find(keys):
                for ci, h in enumerate(colhdr):
                    if any(k in h for k in keys):
                        return ci
                return None
            cm = {'pos': find(['позиция', 'поз.']),
                  'name': find(['наименование и техническ']),
                  'tip': find(['тип, марка', 'тип,']),
                  'code': find(['код обор', 'код ']),
                  'unit': find(['измер', 'единица']),
                  'qty': find(['колич', 'кол.'])}
            return cm, ri
    return None, None

def extract_co(pdf_path):
    """-> list of dict(co,pos,name,tip,code,unit,qty,page). Все материальные строки СО."""
    doc = fitz.open(pdf_path)
    out = []
    for pi in range(doc.page_count):
        pg = doc[pi]; txt = pg.get_text()
        if not is_co_page(txt):
            continue
        co = co_of_page(txt)
        try:
            tabs = pg.find_tables(strategy="lines")
        except Exception:
            continue
        if not tabs.tables:
            continue
        t = max(tabs.tables, key=lambda x: x.row_count)
        data = t.extract()
        cm, hr = map_columns(data)
        if not cm or cm['pos'] is None or cm['qty'] is None:
            continue
        name_end = next((cm[k] for k in ('tip', 'code', 'unit') if cm.get(k) is not None), None)
        for ri in range(hr + 1, len(data)):
            row = data[ri]
            def cell(ci):
                return '' if ci is None or ci >= len(row) else (row[ci] or '').replace('\n', ' ').strip()
            pos = cell(cm['pos']); qty = norm_qty(cell(cm['qty']))
            if name_end is not None and cm['pos'] is not None:
                name = ' '.join(cell(c) for c in range(cm['pos'] + 1, name_end) if cell(c)).strip()
            else:
                name = cell(cm['name'])
            if qty in (None, '') or not name or re.fullmatch(r'\d{1,2}', name):
                continue
            out.append({'co': co, 'pos': pos.strip(), 'name': name, 'tip': cell(cm['tip']),
                        'code': cell(cm['code']), 'unit': cell(cm['unit']), 'qty': qty, 'page': pi + 1})
    return out

def tag(co, pos):
    return f"СО{co}-{pos}" if co else (pos or '?')

def pair_by_position_then_name(A, B):
    """Гибрид: матч по (co,pos), добор остатка по нормализованному названию.
    A,B — списки rows. Возвращает (pairs[(a,b)], only_A, only_B)."""
    from collections import defaultdict
    ak = defaultdict(list); bk = defaultdict(list)
    for r in A: ak[(r['co'], r['pos'])].append(r)
    for r in B: bk[(r['co'], r['pos'])].append(r)
    ma, mb = set(), set(); pairs = []
    for key in set(ak) & set(bk):
        for a, b in zip(ak[key], bk[key]):
            pairs.append((a, b)); ma.add(id(a)); mb.add(id(b))
    rem_b = [r for r in B if id(r) not in mb]
    for a in [r for r in A if id(r) not in ma]:
        best, bsc = None, 0.0
        for b in rem_b:
            if id(b) in mb or b['co'] != a['co']:
                continue
            sc = difflib.SequenceMatcher(None, norm_name(a['name']), norm_name(b['name'])).ratio()
            if sc > bsc: bsc, best = sc, b
        if best and bsc >= 0.6:
            pairs.append((a, best)); ma.add(id(a)); mb.add(id(best))
    return pairs, [r for r in A if id(r) not in ma], [r for r in B if id(r) not in mb]

def pair_by_name_sequence(A, B):
    """Для diff двух редакций (нумерация могла смениться): выравнивание по
    последовательности нормализованных названий. Возвращает (pairs, only_A, only_B)."""
    an = [norm_name(r['name']) for r in A]
    bn = [norm_name(r['name']) for r in B]
    sm = difflib.SequenceMatcher(None, an, bn, autojunk=False)
    pairs, onlyA, onlyB = [], [], []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == 'equal':
            for k in range(a1 - a0):
                pairs.append((A[a0 + k], B[b0 + k]))
        else:
            onlyA += A[a0:a1]; onlyB += B[b0:b1]
    return pairs, onlyA, onlyB
