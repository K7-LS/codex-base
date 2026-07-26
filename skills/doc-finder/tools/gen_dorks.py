#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_dorks.py — генератор поисковых запросов (Google dorks) для поиска
документа качества (сертификат / паспорт / декларация) на оборудование.

Сам поиск выполняет Codex через web (exa / fetch / playwright) по этим запросам
(см. memory/feedback_web_direct_access). Генерация запросов сети НЕ требует.

Usage:
  python gen_dorks.py --article "VT.051" --brand "VALTEC" --type сертификат [--site santech.ru]
  python gen_dorks.py --brand "Grundfos" --article "UPS 25-40" --type любой
"""
import argparse

DOC_SYNONYMS = {
    'сертификат': '(сертификат OR "сертификат соответствия" OR "ТР ТС" OR EAC)',
    'паспорт': '(паспорт OR "паспорт изделия" OR "руководство по эксплуатации" OR РЭ)',
    'декларация': '(декларация OR "декларация о соответствии")',
    'любой': '(сертификат OR паспорт OR декларация OR "ТР ТС")',
}


def gen(article, brand, dtype, site):
    syn = DOC_SYNONYMS.get(dtype, DOC_SYNONYMS['любой'])
    a = f'"{article}"' if article else ''
    b = f'"{brand}"' if brand else ''
    raw = []
    if article:
        raw.append(f'filetype:pdf {a} {syn}')
    if brand and article:
        raw.append(f'filetype:pdf {b} {a} {syn}')
    if brand:
        raw.append(f'intitle:"index of" {b} filetype:pdf')
    if site:
        raw.append(f'site:{site} filetype:pdf {a}')
        raw.append(f'site:{site} {a} {syn}')
    raw.append(f'{b} {a} {syn} filetype:pdf')

    seen, out = set(), []
    for x in raw:
        x = ' '.join(x.split())
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--article', default='')
    ap.add_argument('--brand', default='')
    ap.add_argument('--type', default='любой', choices=list(DOC_SYNONYMS))
    ap.add_argument('--site', default='')
    a = ap.parse_args()
    if not (a.article or a.brand):
        ap.error('нужен хотя бы --article или --brand')

    print("# Поисковые запросы (прогнать через web: exa/fetch/playwright):")
    for i, q in enumerate(gen(a.article, a.brand, a.type, a.site), 1):
        print(f"{i}. {q}")
    print("\n# Дальше: Codex выполняет каждый запрос через web-поиск, заходит в карточку")
    print("# товара актуального артикула и берёт PDF из раздела «Документация/Сертификаты»")
    print("# (методы добычи и обхода антибота — memory/feedback_web_direct_access).")


if __name__ == '__main__':
    main()
