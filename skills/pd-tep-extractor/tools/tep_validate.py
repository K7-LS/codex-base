#!/usr/bin/env python3
"""pd-tep-extractor Layer-3 — детерминированные проверки ТЭП.

Вынесено из SKILL.md (skill-development правило 2). Логика, которую нельзя
переписывать каждый раз без риска: определение типа PDF, sanity-проверки
показателей и — главное — контроль cite (без цитаты поле невалидно).

Функции (importable):
  detect_pdf_type(path)    -> "text" | "scan"  (Stage 2)
  validate_cites(tep)      -> [field, ...] без валидного cite (нарушение правила)
  sanity_checks(tep)       -> [warning, ...]   (Stage 5)
  validate(tep)            -> dict {missing_cites, warnings, ok}

CLI:
  python tep_validate.py detect  ОПЗ.pdf
  python tep_validate.py check   <объект>-tep.json

`tep` — список полей вида {"field","value","unit","cite":{"page","quote"},...}
ИЛИ {"field","value":null,"status":"not_found"}; принимается также dict
field->obj и обёртка {"fields":[...]} / {"tep":[...]}.
"""
import sys
import json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def detect_pdf_type(path):
    """Stage 2: text vs scan по плотности текстового слоя (как в doc-extract)."""
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        text_total = sum(len((p.extract_text() or "").strip()) for p in pdf.pages)
        n_pages = len(pdf.pages) or 1
    return "scan" if text_total < 50 * n_pages else "text"


def _as_fields(tep):
    """Нормализует вход в список field-объектов."""
    if isinstance(tep, dict):
        for k in ("fields", "tep", "data"):
            if isinstance(tep.get(k), list):
                return tep[k]
        # dict field -> obj
        out = []
        for fname, obj in tep.items():
            if isinstance(obj, dict):
                o = dict(obj)
                o.setdefault("field", fname)
                out.append(o)
        return out
    if isinstance(tep, list):
        return tep
    return []


def _val(fields, name):
    for f in fields:
        if f.get("field") == name and f.get("value") is not None:
            try:
                return float(f["value"])
            except (TypeError, ValueError):
                return None
    return None


def validate_cites(tep):
    """Поля с непустым value, но без валидного cite (page+quote) — нарушение
    главного правила скилла ('без cite поле не записывается')."""
    bad = []
    for f in _as_fields(tep):
        if f.get("value") in (None, "") or f.get("status") == "not_found":
            continue
        cite = f.get("cite") or {}
        if not cite.get("page") or not str(cite.get("quote", "")).strip():
            bad.append(f.get("field", "?"))
    return bad


def sanity_checks(tep):
    """Stage 5: проверки правдоподобия. Не блокируют — формируют warnings."""
    f = _as_fields(tep)
    w = []
    ba = _val(f, "building_area")
    ta = _val(f, "total_area")
    la = _val(f, "living_area")
    ap = _val(f, "apartments_count")
    ep = _val(f, "electric_power")
    fl = _val(f, "floors_count")

    if ba is not None and ba <= 0:
        w.append("building_area <= 0")
    if ta is not None and ba is not None and fl is not None and fl > 0:
        if ta < ba * fl * 0.5:
            w.append(f"total_area ({ta}) сильно < building_area*floors ({ba*fl}) — расхождение >50%")
    if la is not None and ap is not None and ap > 0:
        avg = la / ap
        if not (25 <= avg <= 250):
            w.append(f"средняя площадь квартиры {avg:.1f} м² вне 25–250 (living/apartments)")
    if ep is not None and ap is not None and ap > 0:
        per = ep / ap
        if not (5 <= per <= 30):
            w.append(f"электрическая нагрузка {per:.1f} кВт/кв вне 5–30")
    return w


def validate(tep):
    missing = validate_cites(tep)
    warnings = sanity_checks(tep)
    return {"missing_cites": missing, "warnings": warnings,
            "ok": not missing}


def _main(argv):
    if len(argv) >= 3 and argv[1] == "detect":
        print(detect_pdf_type(argv[2]))
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        tep = json.loads(open(argv[2], encoding="utf-8").read())
        res = validate(tep)
        if res["missing_cites"]:
            print("НАРУШЕНИЕ cite (поле без цитаты, записывать нельзя):")
            for m in res["missing_cites"]:
                print("  -", m)
        else:
            print("cite: OK (все заполненные поля имеют цитату)")
        print("warnings:" if res["warnings"] else "warnings: []")
        for x in res["warnings"]:
            print("  !", x)
        return 0 if res["ok"] else 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
