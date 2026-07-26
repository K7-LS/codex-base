#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
web_get.py — ЕДИНЫЙ вход веб-доступа Codex: одна команда вместо ручного
перебора curl/exa/firecrawl/playwright/WebFetch/r.jina по памяти.

Боль, которую чиним: лестница веб-доступа жила ТЕКСТОМ (правило в AGENTS.md).
Модель каждый раз должна была её вспоминать и вручную дёргать 3-6 инструментов
по очереди — ступени забывались, падение одной читалось как «в интернете нет».
Здесь детерминированная часть лестницы вынесена в КОД: скрипт сам определяет
egress, перебирает ступени до первого ВЕРИФИЦИРОВАННОГО успеха и печатает, что
сработало. Если кодовые ступени исчерпаны — печатает next_hint: какую MCP-ступень
взять Codex (exa/firecrawl/playwright). 0 «забыл ступень», 0 токенов на логику.

Честная граница (см. SKILL.md): код покрывает curl-семейство + r.jina (облачный
reader). MCP-ступени (exa http, firecrawl, playwright-браузер) из питона не
дёргаются — они инструменты Codex; скрипт лишь маршрутизирует к ним явно.

RU-слой НЕ дублируется: российский exit-IP делегируется соседнему скиллу
ru-gov-access (tools/ru_fetch.py) — один дом на RU-SOCKS5-логику.

Usage:
  python web_get.py <URL> [--kind page|file|auto] [-o out] [--timeout 20] [--json]
  # --kind auto (дефолт): file если задан -o или URL кончается на .pdf/.zip/...
  # --json: только машиночитаемый JSON в stdout (для парсинга Codex), без лога

Needs: curl + python3. No pip deps. ru-слой требует соседний ru_fetch.py.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
IPINFO = "https://ipinfo.io/json"
# Маркеры HTML-заглушки/челленджа: тело с ними = НЕ настоящий контент, ступень провалена.
CHALLENGE_MARKERS = (
    "ddos-guard", "cf-browser-verification", "cf_chl_", "just a moment",
    "checking your browser", "attention required", "enable javascript and cookies",
    "проверка браузера", "доступ ограничен",
)
FILE_EXT = (".pdf", ".zip", ".xlsx", ".xls", ".docx", ".doc", ".rar",
            ".dwg", ".dxf", ".png", ".jpg", ".jpeg", ".rtf", ".7z")
# Сигнатуры бинарных файлов (первые байты) для верификации скачанного.
MAGIC = {
    b"%PDF": "pdf", b"PK\x03\x04": "zip/office", b"Rar!": "rar",
    b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg", b"{\\rt": "rtf",
    b"AC10": "dwg", b"7z\xbc\xaf": "7z",
}


def run(args, timeout):
    """Запуск процесса. Возвращает (returncode, stdout_bytes, stderr_bytes)."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 28, b"", b"timeout"
    except Exception as e:  # noqa: BLE001
        return 1, b"", str(e).encode()


EGRESS_CACHE = os.path.join(tempfile.gettempdir(), "web_get_egress.txt")
EGRESS_TTL = 1200  # сек (20 мин): egress стабилен в сессии, меняется лишь при вкл/выкл VPN


def _country(out):
    m = re.search(rb'"country"\s*:\s*"([^"]+)"', out or b"")
    return m.group(1).decode() if m else None


def _detect_egress():
    """
    Детект гео + живости --noproxy одним заходом. Возвращает (country, noproxy_ok).
    Боевой урок 2026-07-08: на WARP-машине `--noproxy` к ipinfo не пробивается (egress
    вечно None + ступени с --noproxy висят 15с по таймауту, http=000). Поэтому:
    сначала --noproxy (если ответил → обход прокси жив, noproxy_ok=True), иначе обычный
    curl через окно (WARP отвечает, но noproxy_ok=False → в лестнице --noproxy пропускаем).
    max-time=6 — fail-fast.
    """
    rc, out, _ = run(["curl", "--noproxy", "*", "-s", "--max-time", "6", IPINFO], 9)
    c = _country(out) if rc == 0 else None
    if c:
        return c, True
    rc, out, _ = run(["curl", "-s", "--max-time", "6", IPINFO], 9)
    return (_country(out) if rc == 0 else None), False


def egress_probe(no_cache=False):
    """
    (country, noproxy_ok) с кешем на сессию (temp + mtime-TTL 20 мин) — устраняет
    12-40с задержки на каждый запуск (жалоба владельца «топорно/долго»). Формат
    кеша: 'COUNTRY|0|1'. '??' = детект не удался.
    """
    if not no_cache and os.path.exists(EGRESS_CACHE):
        try:
            if (time.time() - os.path.getmtime(EGRESS_CACHE)) < EGRESS_TTL:
                raw = open(EGRESS_CACHE, encoding="utf-8").read().strip()
                cc, _, nk = raw.partition("|")
                return (None if cc in ("", "??") else cc), (nk == "1")
        except Exception:  # noqa: BLE001
            pass
    country, noproxy_ok = _detect_egress()
    try:
        open(EGRESS_CACHE, "w", encoding="utf-8").write(f"{country or '??'}|{1 if noproxy_ok else 0}")
    except Exception:  # noqa: BLE001
        pass
    return country, noproxy_ok


def egress_country(no_cache=False):
    """Только страна (совместимость/тесты)."""
    return egress_probe(no_cache)[0]


def is_ru_host(url):
    """RU-цель по TLD: .ru/.su/.рф(xn--p1ai). Грубо, но покрывает наш словарь сайтов."""
    m = re.match(r"https?://([^/:]+)", url.strip(), re.I)
    host = (m.group(1) if m else url).lower()
    return bool(re.search(r"\.(ru|su)$", host) or host.endswith(".xn--p1ai"))


def classify_kind(url, kind, out):
    """auto → file, если задан -o или расширение файловое; иначе page."""
    if kind in ("page", "file"):
        return kind
    low = url.lower().split("?")[0]
    if out or any(low.endswith(e) for e in FILE_EXT):
        return "file"
    return "page"


def _http_code(stdout):
    m = re.search(rb"__HTTP__(\d{3})", stdout or b"")
    return m.group(1).decode() if m else None


def verify_page(body_bytes, http):
    """Страница валидна: 2xx, непустая, без challenge-маркеров."""
    if not http or http[0] not in "23":
        return False, f"http={http}"
    if not body_bytes or len(body_bytes) < 64:
        return False, "empty/too-short"
    head = body_bytes[:4000].decode("utf-8", "replace").lower()
    for mk in CHALLENGE_MARKERS:
        if mk in head:
            return False, f"challenge:{mk}"
    return True, "ok"


def verify_file(path, http, expect_pdf):
    """Файл валиден: скачан, не HTML-заглушка, магическая сигнатура известна."""
    if not http or http[0] not in "23":
        return False, f"http={http}"
    if not path or not os.path.exists(path) or os.path.getsize(path) < 64:
        return False, "missing/too-short"
    with open(path, "rb") as f:
        head = f.read(8)
    if head[:5].lower() in (b"<!doc", b"<html"):
        return False, "html-stub (not a file)"
    sig = next((name for magic, name in MAGIC.items() if head.startswith(magic)), None)
    if sig is None:
        return False, f"unknown-magic:{head[:4]!r}"
    if expect_pdf and sig != "pdf":
        return False, f"expected pdf, got {sig}"
    return True, sig


def curl_page(url, direct, timeout):
    """curl страницы. direct=True → --noproxy (обход корп-прокси окна)."""
    args = ["curl", "-sSL", "-A", UA, "-w", "\n__HTTP__%{http_code}",
            "--max-time", str(timeout)]
    if direct:
        args += ["--noproxy", "*"]
    args += [url]
    rc, out, _ = run(args, timeout + 6)
    http = _http_code(out)
    body = re.sub(rb"\n__HTTP__\d{3}$", b"", out or b"")
    return http, body


def curl_file(url, out_path, direct, timeout):
    args = ["curl", "-sSL", "-A", UA, "-w", "__HTTP__%{http_code}",
            "--max-time", str(timeout), "-o", out_path]
    if direct:
        args += ["--noproxy", "*"]
    args += [url]
    rc, tail, _ = run(args, timeout + 6)
    return _http_code(tail)


def jina_page(url, timeout):
    """r.jina.ai — облачный reader: берёт антибот/JS-сайты, отдаёт текст. Без ключа."""
    jurl = "https://r.jina.ai/" + url
    args = ["curl", "-sSL", "-A", UA, "-w", "\n__HTTP__%{http_code}",
            "--max-time", str(timeout + 15), jurl]
    rc, out, _ = run(args, timeout + 22)
    http = _http_code(out)
    body = re.sub(rb"\n__HTTP__\d{3}$", b"", out or b"")
    return http, body


def build_ladder(kind, ru_host, egress, noproxy_ok=True):
    """
    Порядок ступеней = f(тип, RU-цель, egress, живость --noproxy). Только БЫСТРЫЕ
    ступени (curl-семейство + облачный jina). Медленный RU exit-IP (ru-gov-access)
    в авто-переборе НЕ участвует — он отдельный осознанный шаг из next_hint.
    """
    # noproxy включаем в лестницу ТОЛЬКО если обход прокси жив (боевой урок 08.07:
    # на WARP --noproxy мёртв → ступень висит 15с по таймауту зря).
    if egress == "RU" or ru_host:
        # RU-контекст: обход прокси (--noproxy, локальный RU-IP) приоритетен, если жив.
        direct_stages = ["noproxy", "direct"] if noproxy_ok else ["direct"]
    else:
        # Зарубеж: обычный прямой первым, --noproxy лишь как запасной (если жив).
        direct_stages = ["direct", "noproxy"] if noproxy_ok else ["direct"]
    # jina (облачный reader) — только для СТРАНИЦ: берёт гео-блок/антибот, отдаёт текст.
    # Медленный RU-прокси (ru_fetch) в АВТО-лестницу НЕ ставим (30с вис на эфемерном
    # прокси) — реально гео-блокированные RU-цели уходят в next_hint → ru-gov-access.
    return direct_stages + (["jina"] if kind == "page" else [])


def next_hint(kind, ru_host, tried):
    """Что взять Codex, когда кодовые ступени исчерпаны. MCP — не из питона."""
    ru_extra = ("; RU-цель и не взялась прямым → возможно ГЕО-блок: запусти "
                "ru-gov-access (skills/ru-gov-access/tools/ru_fetch.py, RU exit-IP) "
                "или playwright с RU-proxy") if ru_host else ""
    if kind == "file":
        return ("Кодовые ступени пали. Для файла: (1) playwright browser_navigate на "
                "КАРТОЧКУ товара → снять cookies → curl -b (Метод 2 feedback_web_direct_access)"
                + ru_extra + ". Скриншот карточки глазами ДО вывода «документа нет».")
    if ru_host:
        return ("Кодовые ступени пали для RU-страницы. Codex: (1) exa/firecrawl "
                "(облачный канал, читают RU-коммерч); (2) гео-блок → ru-gov-access "
                "(ru_fetch.py, RU exit-IP); (3) SPA-данные реестра → playwright с RU-proxy. "
                "Скриншот перед выводом «нет».")
    return ("Кодовые ступени пали для зарубежной страницы. Codex: (1) exa web_search/"
            "web_fetch (semantic, антибот); (2) firecrawl_scrape; (3) playwright для JS/SPA. "
            "Сделай browser_take_screenshot ДО вывода «сайта/данных нет».")


def attempt(stage, url, kind, out_path, timeout, expect_pdf):
    """Одна ступень: выполнить + верифицировать. Возвращает dict-результат."""
    r = {"stage": stage}
    if kind == "page":
        if stage == "direct":
            http, body = curl_page(url, direct=False, timeout=timeout)
        elif stage == "noproxy":
            http, body = curl_page(url, direct=True, timeout=timeout)
        elif stage == "jina":
            http, body = jina_page(url, timeout=timeout)
        else:
            r.update(ok=False, reason="unknown stage")
            return r
        ok, reason = verify_page(body, http)
        r.update(ok=ok, http=http, bytes=len(body or b""), reason=reason)
        if ok:
            r["preview"] = body[:600].decode("utf-8", "replace")
        return r
    # file
    if stage in ("direct", "noproxy"):
        http = curl_file(url, out_path, direct=(stage == "noproxy"), timeout=timeout)
    else:
        r.update(ok=False, reason="unknown stage")
        return r
    ok, reason = verify_file(out_path, http, expect_pdf)
    r.update(ok=ok, http=http, reason=reason)
    if ok:
        r["out"] = out_path
        r["bytes"] = os.path.getsize(out_path)
    return r


def fetch(url, kind="auto", out=None, timeout=20, egress=None):
    """Главная лестница. Возвращает единый dict-результат (для --json и как API)."""
    kind = classify_kind(url, kind, out)
    ru_host = is_ru_host(url)
    noproxy_ok = True
    if egress is None:
        egress, noproxy_ok = egress_probe()
    expect_pdf = bool(out and out.lower().endswith(".pdf")) or url.lower().split("?")[0].endswith(".pdf")
    ladder = build_ladder(kind, ru_host, egress, noproxy_ok)

    tried = []
    for stage in ladder:
        res = attempt(stage, url, kind, out, timeout, expect_pdf)
        tried.append({k: res[k] for k in ("stage", "ok", "http", "reason", "bytes")
                      if k in res})
        if res.get("ok"):
            return {"ok": True, "url": url, "kind": kind, "ru_host": ru_host,
                    "egress": egress, "stage": stage, "http": res.get("http"),
                    "bytes": res.get("bytes"), "out": res.get("out"),
                    "preview": res.get("preview"), "tried": tried}
    return {"ok": False, "url": url, "kind": kind, "ru_host": ru_host,
            "egress": egress, "stage": None, "tried": tried,
            "next": next_hint(kind, ru_host, tried)}


def force_utf8_stdio():
    """
    БОЕВОЙ ФИКС 2026-07-08: web_get печатает preview/reason с юникодом (китайские
    бренды оборудования, спецтире, emoji). Windows-консоль без PYTHONIOENCODING = cp1251,
    и print() ловит UnicodeEncodeError → «упал на выводе» (репорт владельца на palerom/
    tincraft). Инструмент обязан быть устойчив САМ, не полагаться на env пользователя.
    reconfigure есть у TextIOWrapper (Py 3.7+); при перенаправлении/отсутствии — тихо мимо.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def render_human(res):
    """Человекочитаемый отчёт как СТРОКА (тестируемо отдельно от печати)."""
    lines = [f"[egress] {res['egress']}  [kind] {res['kind']}  [ru_host] {res['ru_host']}"]
    for t in res["tried"]:
        mark = "OK " if t.get("ok") else "-- "
        size = f"({t['bytes']}b)" if t.get("bytes") else ""
        lines.append(f"  {mark}{t['stage']:8} http={t.get('http')} {t.get('reason','')} {size}")
    if res["ok"]:
        where = res.get("out") or f"{res.get('bytes')}b (preview ниже)"
        lines.append(f"[OK] via '{res['stage']}' -> {where}")
        if res.get("preview") and not res.get("out"):
            lines.append("---8<--- preview ---")
            lines.append(res["preview"])
    else:
        lines.append(f"[FAIL] все кодовые ступени пали.\n[next] {res['next']}")
    return "\n".join(lines)


def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="Единый вход веб-доступа (лестница в коде).")
    ap.add_argument("url")
    ap.add_argument("--kind", choices=["page", "file", "auto"], default="auto")
    ap.add_argument("-o", "--out")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="только JSON в stdout")
    a = ap.parse_args()

    res = fetch(a.url, kind=a.kind, out=a.out, timeout=a.timeout)

    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(render_human(res))
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
