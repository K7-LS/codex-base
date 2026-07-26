"""Парсинг УПД (Универсального передаточного документа) в structured dict.

Минимально достаточный helper. Не пытается заменить полноценный парсер ЭДО —
ловит шапку (продавец/покупатель/номер/дата), таблицу позиций и итоги.

Использование:
    import pdfplumber
    from parse_upd import parse_header, parse_items, parse_totals

    with pdfplumber.open(upd_path) as pdf:
        text = "\\n".join(p.extract_text() for p in pdf.pages)
    header = parse_header(text)
    items = parse_items(upd_path)
    totals = parse_totals(text)
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

import pdfplumber


_MONTHS = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
    "мая": "05", "июня": "06", "июля": "07", "августа": "08",
    "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip() if s else s


def _to_iso_date(raw: str) -> Optional[str]:
    """'15.05.2026' / '15 мая 2026 г.' → '2026-05-15'."""
    if not raw:
        return None
    raw = raw.strip().lower().replace("г.", "").strip()
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})$", raw)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:
            y = "20" + y
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})\s+([а-яё]+)\s+(\d{4})", raw)
    if m:
        d, month_ru, y = m.groups()
        mo = _MONTHS.get(month_ru)
        if mo:
            return f"{y}-{mo}-{int(d):02d}"
    return None


def _to_float(s) -> Optional[float]:
    """'1 234,56' / '1234.56' / '— ' → float или None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("\xa0", " ").replace(" ", "")
    if not s or s in {"-", "—", "–", "без ндс", "без НДС"}:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_header(full_text: str) -> dict:
    """Извлекает шапку УПД. Возвращает dict со seller/buyer/upd_number/upd_date/contract_ref."""
    text = _norm_space(full_text)
    result: dict = {
        "upd_number": None,
        "upd_date": None,
        "seller": {"name": None, "inn": None, "kpp": None, "address": None},
        "buyer": {"name": None, "inn": None, "kpp": None, "address": None},
        "contract_ref": None,
    }

    # Номер УПД (после "Счёт-фактура №" / "УПД №" / просто "№")
    m = re.search(
        r"(?:Счёт-фактура|Счет-фактура|УПД|Универсальный передаточный документ)[^№]*№\s*([\w\-/]+)",
        text, re.IGNORECASE,
    )
    if m:
        result["upd_number"] = m.group(1).strip()

    # Дата (рядом с номером или после "от")
    m = re.search(
        r"от\s+«?(\d{1,2})»?[\s.\-/]+([а-яё]+|\d{1,2})[\s.\-/]+(\d{2,4})",
        text, re.IGNORECASE,
    )
    if m:
        d, mo, y = m.groups()
        if mo.isalpha():
            mo_iso = _MONTHS.get(mo.lower())
            if mo_iso:
                if len(y) == 2:
                    y = "20" + y
                result["upd_date"] = f"{y}-{mo_iso}-{int(d):02d}"
        else:
            if len(y) == 2:
                y = "20" + y
            result["upd_date"] = f"{y}-{int(mo):02d}-{int(d):02d}"

    # Все ИНН/КПП в документе — первая пара обычно продавец, вторая покупатель
    inns = re.findall(r"ИНН[/\s:]*(\d{10}|\d{12})", text)
    kpps = re.findall(r"КПП[/\s:]*(\d{9})", text)
    if len(inns) >= 1:
        result["seller"]["inn"] = inns[0]
    if len(inns) >= 2:
        result["buyer"]["inn"] = inns[1]
    if len(kpps) >= 1:
        result["seller"]["kpp"] = kpps[0]
    if len(kpps) >= 2:
        result["buyer"]["kpp"] = kpps[1]

    # Названия — рядом со словами "Продавец" / "Покупатель"
    m = re.search(r"Продавец[:\s]+([^,;\n]{3,120}?)(?:,|ИНН|Адрес|$)", text)
    if m:
        result["seller"]["name"] = _norm_space(m.group(1)).strip(' "«»')
    m = re.search(r"Покупатель[:\s]+([^,;\n]{3,120}?)(?:,|ИНН|Адрес|$)", text)
    if m:
        result["buyer"]["name"] = _norm_space(m.group(1)).strip(' "«»')

    # Ссылка на договор
    m = re.search(
        r"(?:Основание|по договору|Договор[\s-]?(?:поставки|купли)?)[:\s№]*([^\n,;]{3,80})",
        text, re.IGNORECASE,
    )
    if m:
        result["contract_ref"] = _norm_space(m.group(0))

    return result


def parse_items(pdf_path: str | Path) -> list[dict]:
    """Извлекает таблицу позиций УПД через pdfplumber.extract_tables().

    Возвращает list[dict] с полями row/code/name/unit/qty/price/amount/vat_rate/vat_amount/amount_with_vat.
    """
    items: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                header_row = [(_norm_space(c) or "").lower() for c in tbl[0]]
                if not _looks_like_items_header(header_row):
                    continue
                col_map = _map_columns(header_row)
                if "name" not in col_map:
                    continue
                for raw_row in tbl[1:]:
                    if not raw_row or all((not c or not str(c).strip()) for c in raw_row):
                        continue
                    item = _row_to_item(raw_row, col_map, row_idx=len(items) + 1)
                    if item and (item.get("name") or item.get("code")):
                        items.append(item)
    return items


def _looks_like_items_header(header_cells: list[str]) -> bool:
    joined = " ".join(header_cells)
    return any(k in joined for k in (
        "наимен", "товар", "услуг", "ед. изм", "ед.изм", "количеств",
    )) and any(k in joined for k in ("цена", "стоимост", "сумма"))


def _map_columns(header_cells: list[str]) -> dict:
    """Маппит индексы колонок таблицы на семантические имена."""
    m: dict[str, int] = {}
    for i, h in enumerate(header_cells):
        if "наимен" in h or ("товар" in h and "код" not in h):
            m["name"] = i
        elif "код" in h:
            m["code"] = i
        elif "ед" in h and "изм" in h:
            m["unit"] = i
        elif "количеств" in h or "объ" in h:
            m["qty"] = i
        elif "цена" in h:
            m["price"] = i
        elif "стоимост" in h and "без" in h and "налог" in h:
            m["amount"] = i
        elif "ставка" in h and "налог" in h:
            m["vat_rate"] = i
        elif "сумма" in h and "налог" in h:
            m["vat_amount"] = i
        elif "стоимост" in h and ("всего" in h or "с налог" in h):
            m["amount_with_vat"] = i
    return m


def _row_to_item(row: list, col_map: dict, row_idx: int) -> Optional[dict]:
    def cell(key):
        idx = col_map.get(key)
        if idx is None or idx >= len(row):
            return None
        return _norm_space(str(row[idx])) if row[idx] is not None else None

    return {
        "row": row_idx,
        "code": cell("code"),
        "name": cell("name"),
        "unit": cell("unit"),
        "qty": _to_float(cell("qty")),
        "price": _to_float(cell("price")),
        "amount": _to_float(cell("amount")),
        "vat_rate": cell("vat_rate"),
        "vat_amount": _to_float(cell("vat_amount")),
        "amount_with_vat": _to_float(cell("amount_with_vat")),
    }


def parse_totals(full_text: str) -> dict:
    """Извлекает итоги УПД из текста (после таблицы позиций)."""
    text = full_text.replace("\xa0", " ")
    result = {
        "sum_without_vat": None,
        "vat_total": None,
        "sum_total": None,
        "vat_breakdown": {},
    }

    m = re.search(
        r"(?:Всего к оплате|Итого к оплате)[\s:]*([\d\s.,]+)",
        text, re.IGNORECASE,
    )
    if m:
        result["sum_total"] = _to_float(m.group(1))

    m = re.search(r"(?:Сумма налога.*?продавцу|Сумма НДС)[\s:]*([\d\s.,]+)", text, re.IGNORECASE)
    if m:
        result["vat_total"] = _to_float(m.group(1))

    m = re.search(r"Всего без налога[\s:]*([\d\s.,]+)", text, re.IGNORECASE)
    if m:
        result["sum_without_vat"] = _to_float(m.group(1))
    elif result["sum_total"] is not None and result["vat_total"] is not None:
        result["sum_without_vat"] = round(result["sum_total"] - result["vat_total"], 2)

    return result


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python parse_upd.py <upd.pdf>")
        sys.exit(1)
    path = sys.argv[1]
    with pdfplumber.open(path) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    result = {
        "header": parse_header(full_text),
        "items": parse_items(path),
        "totals": parse_totals(full_text),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
