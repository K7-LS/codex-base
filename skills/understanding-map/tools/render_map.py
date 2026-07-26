#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_map.py — детерминированный генератор «карты понимания» из JSON в HTML.

Карта понимания = зеркало того, что Codex понял по задаче, для сверки ДО работы.
Форма следует за содержанием: зоны (понято / допущения / пробелы) + ход разбора +
архитектура + штамп.

Два режима (разные среды — разные ограничения):
  --mode widget      фрагмент под Codex show_widget (CDS-стиль хоста: CSS-переменные
                     --surface/--text, без DOCTYPE, без градиент-фонов). stdout.
  --mode standalone  самодостаточный «чертёжный лист» (свои стили, миллиметровка,
                     ГОСТ-штамп, mobile viewport) — для браузера / VS Code Simple
                     Browser / телефона. Пишет в --out (или stdout).

Сквозной принцип skill-development: рендер — кодом, не генерировать HTML заново.
Творческое (что Codex понял → данные) — модель; детерминированное (данные → HTML) — здесь.

Формат данных (JSON), все секции кроме title опциональны:
{
  "title":   "Что я понял: ...",
  "goal":    "Цель ... (допускается <b>разметка</b>)",
  "eyebrow": ["левая подпись", "правая подпись"],
  "okTitle": "Что понято", "asTitle": "Допущения · проверь", "peTitle": "Пробелы · решаем",
  "items":   [{"zone":"ok|as|pe", "tag":"Р1 · решено", "title":"...", "detail":"..."}],
  "flowTitle":"Как шёл разбор",
  "flow":    [{"n":"Ш1", "title":"...", "detail":"...", "turn":false}],
  "archTitle":"Архитектура",
  "arch":    [{"ln":"слой 1", "title":"...", "detail":"..."}],
  "stamp":   [{"k":"Понял", "v":"Codex · selected-model 4.8", "soft":false}]
}

Поля goal/detail/title пропускаются как есть (доверенный вход от Codex) — это
позволяет лёгкую разметку (<b>). Данные не из доверенного источника сюда не подавать.
"""
import argparse
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def g(d, key, default=""):
    v = d.get(key, default)
    return v if v is not None else default


# ───────────────────────────── STANDALONE («чертёжный лист») ─────────────────────────────

CSS_STANDALONE = r"""
  :root{
    --field:#f5f8fb; --grid:#dde5ee; --grid2:#cfd9e6;
    --ink:#1f2933; --ink-soft:#5a6776; --line:#9fb2c6;
    --blue:#2f5d8c;
    --ok:#2e7d32; --ok-bg:#e7f3e8;
    --as:#b9760a; --as-bg:#fbf2e0;
    --pe:#c0392b; --pe-bg:#fbe7e4;
    --paper:#ffffff;
    --mono:"Cascadia Code","Consolas",ui-monospace,monospace;
    --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    font-family:var(--sans); color:var(--ink); background:var(--field);
    background-image:
      linear-gradient(var(--grid) 1px,transparent 1px),
      linear-gradient(90deg,var(--grid) 1px,transparent 1px),
      linear-gradient(var(--grid2) 1px,transparent 1px),
      linear-gradient(90deg,var(--grid2) 1px,transparent 1px);
    background-size:20px 20px,20px 20px,100px 100px,100px 100px;
    padding:18px; -webkit-font-smoothing:antialiased;
  }
  .sheet{max-width:1080px;margin:0 auto;background:var(--paper);
    border:2px solid var(--ink); box-shadow:0 2px 0 var(--line),0 14px 40px rgba(31,41,51,.10);}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;color:var(--blue);
    text-transform:uppercase;border-bottom:1px solid var(--grid);padding:9px 18px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
  .head{padding:18px 20px 6px}
  .head h1{margin:0;font-size:26px;font-weight:700;letter-spacing:-.01em;line-height:1.12}
  .goal{margin:8px 0 0;color:var(--ink-soft);font-size:14.5px;max-width:760px;line-height:1.5}
  .goal b{color:var(--ink)}
  .bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:14px 20px;border-top:1px solid var(--grid);border-bottom:1px solid var(--grid);margin-top:14px;background:#fbfdff}
  .bar .lbl{font-family:var(--mono);font-size:11px;letter-spacing:.12em;color:var(--ink-soft);text-transform:uppercase;margin-right:2px}
  .f{font-family:var(--mono);font-size:12px;border:1px solid var(--line);background:#fff;color:var(--ink);
    padding:5px 11px;border-radius:2px;cursor:pointer;display:inline-flex;gap:6px;align-items:center}
  .f .dot{width:9px;height:9px;border-radius:50%}
  .f[aria-pressed="true"]{background:var(--ink);color:#fff;border-color:var(--ink)}
  .f.ok .dot{background:var(--ok)} .f.as .dot{background:var(--as)} .f.pe .dot{background:var(--pe)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
  .col{padding:18px 20px}
  .col + .col{border-left:1px solid var(--grid)}
  .zone-h{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--blue);
    display:flex;align-items:center;gap:8px;margin:0 0 12px}
  .zone-h::after{content:"";flex:1;height:1px;background:var(--grid)}
  .item{border:1px solid var(--grid);border-left-width:3px;border-radius:2px;padding:10px 12px;margin-bottom:9px;cursor:pointer;transition:transform .12s ease,box-shadow .12s ease;background:#fff}
  .item:hover{transform:translateY(-1px);box-shadow:0 3px 10px rgba(31,41,51,.08)}
  .item:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
  .item .tag{font-family:var(--mono);font-size:10.5px;color:var(--ink-soft);letter-spacing:.06em}
  .item .t{font-size:14px;font-weight:600;margin:3px 0 0;line-height:1.35}
  .item .d{font-size:13px;color:var(--ink-soft);line-height:1.5;margin-top:7px;display:none}
  .item.open .d{display:block}
  .item.ok{border-left-color:var(--ok)} .item.ok .tag{color:var(--ok)}
  .item.as{border-left-color:var(--as);background:var(--as-bg)} .item.as .tag{color:var(--as)}
  .item.pe{border-left-color:var(--pe);background:var(--pe-bg)} .item.pe .tag{color:var(--pe)}
  .hidden{display:none!important}
  .flow{position:relative;padding-left:20px}
  .flow::before{content:"";position:absolute;left:6px;top:4px;bottom:4px;width:2px;background:var(--grid2)}
  .step{position:relative;padding:0 0 13px 4px}
  .step::before{content:"";position:absolute;left:-17px;top:3px;width:9px;height:9px;border-radius:50%;background:#fff;border:2px solid var(--blue)}
  .step.turn::before{background:var(--pe);border-color:var(--pe)}
  .step .s-n{font-family:var(--mono);font-size:10.5px;color:var(--blue);letter-spacing:.06em}
  .step.turn .s-n{color:var(--pe)}
  .step .s-t{font-size:13.5px;font-weight:600;margin-top:1px}
  .step .s-d{font-size:12.5px;color:var(--ink-soft);line-height:1.45;margin-top:2px}
  .arch{display:flex;flex-direction:column;gap:0;border:1px solid var(--grid);border-radius:2px;overflow:hidden}
  .layer{padding:11px 13px;border-bottom:1px solid var(--grid);display:flex;gap:11px;align-items:flex-start;background:#fff}
  .layer:last-child{border-bottom:none}
  .layer .ln{font-family:var(--mono);font-size:11px;color:#fff;background:var(--blue);border-radius:2px;padding:2px 7px;margin-top:1px;white-space:nowrap}
  .layer .lt{font-size:13.5px;font-weight:600} .layer .ld{font-size:12.5px;color:var(--ink-soft);line-height:1.45;margin-top:2px}
  .stamp{border-top:2px solid var(--ink);display:grid;grid-template-columns:repeat(4,1fr);font-family:var(--mono)}
  .stamp .c{padding:9px 12px;border-right:1px solid var(--grid);font-size:12px}
  .stamp .c:last-child{border-right:none}
  .stamp .k{font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-soft)}
  .stamp .v{font-size:13px;color:var(--ink);margin-top:3px;font-weight:600}
  .stamp .v.s{color:var(--as)}
  @media (max-width:720px){
    body{padding:8px}
    .grid{grid-template-columns:1fr}
    .col + .col{border-left:none;border-top:1px solid var(--grid)}
    .head h1{font-size:21px}
    .stamp{grid-template-columns:1fr 1fr}
    .stamp .c:nth-child(2){border-right:none}
  }
  @media (prefers-reduced-motion:reduce){.item{transition:none}}
"""

JS_STANDALONE = r"""
  const btns=[...document.querySelectorAll('.f')], items=[...document.querySelectorAll('.item')];
  btns.forEach(b=>b.addEventListener('click',()=>{
    btns.forEach(x=>x.setAttribute('aria-pressed', x===b ? 'true':'false'));
    const f=b.dataset.f;
    items.forEach(it=> it.classList.toggle('hidden', !(f==='all'||it.dataset.c===f)) );
  }));
  items.forEach(it=>{
    const toggle=()=>it.classList.toggle('open');
    it.addEventListener('click',toggle);
    it.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();} });
  });
"""


def _item_std(it):
    z = g(it, "zone", "ok")
    return (f'<div class="item {z}" data-c="{z}" tabindex="0">'
            f'<div class="tag">{g(it,"tag")}</div>'
            f'<div class="t">{g(it,"title")}</div>'
            f'<div class="d">{g(it,"detail")}</div></div>')


def _step_std(s):
    turn = " turn" if s.get("turn") else ""
    return (f'<div class="step{turn}"><div class="s-n">{g(s,"n")}</div>'
            f'<div class="s-t">{g(s,"title")}</div>'
            f'<div class="s-d">{g(s,"detail")}</div></div>')


def _layer_std(a):
    return (f'<div class="layer"><span class="ln">{g(a,"ln")}</span>'
            f'<div><div class="lt">{g(a,"title")}</div>'
            f'<div class="ld">{g(a,"detail")}</div></div></div>')


def _stamp_std(c):
    soft = " s" if c.get("soft") else ""
    return (f'<div class="c"><div class="k">{g(c,"k")}</div>'
            f'<div class="v{soft}">{g(c,"v")}</div></div>')


def build_standalone(d):
    items = d.get("items", [])
    ok = [i for i in items if g(i, "zone") == "ok"]
    as_ = [i for i in items if g(i, "zone") == "as"]
    pe = [i for i in items if g(i, "zone") == "pe"]
    eb = d.get("eyebrow", ["Общая среда видимости · Codex ↔ инженер", "Карта понимания"])
    eb_l = eb[0] if len(eb) > 0 else ""
    eb_r = eb[1] if len(eb) > 1 else ""

    right = []
    if as_:
        right.append(f'<h2 class="zone-h">{g(d,"asTitle","Допущения · проверь")}</h2>')
        right.append("".join(_item_std(i) for i in as_))
    if pe:
        right.append(f'<h2 class="zone-h" style="margin-top:18px">{g(d,"peTitle","Пробелы · решаем")}</h2>')
        right.append("".join(_item_std(i) for i in pe))
    arch = d.get("arch", [])
    if arch:
        right.append(f'<h2 class="zone-h" style="margin-top:18px">{g(d,"archTitle","Архитектура")}</h2>')
        right.append('<div class="arch">' + "".join(_layer_std(a) for a in arch) + "</div>")

    flow = d.get("flow", [])
    flow_block = ""
    if flow:
        flow_block = (f'<div class="col" style="border-top:1px solid var(--grid)">'
                      f'<h2 class="zone-h">{g(d,"flowTitle","Как шёл разбор")}</h2>'
                      f'<div class="flow">' + "".join(_step_std(s) for s in flow) + "</div></div>")

    stamp = d.get("stamp", [])
    stamp_block = ""
    if stamp:
        stamp_block = '<div class="stamp">' + "".join(_stamp_std(c) for c in stamp) + "</div>"

    body = f"""<div class="sheet">
  <div class="eyebrow"><span>{eb_l}</span><span>{eb_r}</span></div>
  <div class="head">
    <h1>{g(d,"title","Что я понял в этой сессии")}</h1>
    <p class="goal">{g(d,"goal")}</p>
  </div>
  <div class="bar">
    <span class="lbl">Фильтр сверки:</span>
    <button class="f" data-f="all" aria-pressed="true">Всё</button>
    <button class="f ok" data-f="ok" aria-pressed="false"><span class="dot"></span>Понято</button>
    <button class="f as" data-f="as" aria-pressed="false"><span class="dot"></span>Допущения</button>
    <button class="f pe" data-f="pe" aria-pressed="false"><span class="dot"></span>Пробелы</button>
    <span class="lbl" style="margin-left:auto">тапни карточку — детали</span>
  </div>
  <div class="grid">
    <div class="col">
      <h2 class="zone-h">{g(d,"okTitle","Что понято")}</h2>
      {"".join(_item_std(i) for i in ok)}
    </div>
    <div class="col">
      {"".join(right)}
    </div>
  </div>
  {flow_block}
  {stamp_block}
</div>"""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{g(d,"title","Карта понимания")}</title>
<style>{CSS_STANDALONE}</style>
</head>
<body>
{body}
<script>{JS_STANDALONE}</script>
</body>
</html>"""


# ───────────────────────────── WIDGET (CDS под show_widget) ─────────────────────────────

ZONE_CDS = {
    "ok": ("ti-circle-check", "var(--text-success)"),
    "as": ("ti-alert-triangle", "var(--text-warning)"),
    "pe": ("ti-circle-dashed", "var(--text-danger)"),
}


def _item_cds(it):
    return (
        '<div style="margin-bottom:10px;">'
        f'<div style="font-size:11px;font-family:var(--font-mono);color:var(--text-muted)">{g(it,"tag")}</div>'
        f'<div style="font-size:14px;color:var(--text-primary);font-weight:500;line-height:1.35">{g(it,"title")}</div>'
        f'<div style="font-size:13px;color:var(--text-secondary);line-height:1.5;margin-top:2px">{g(it,"detail")}</div>'
        "</div>"
    )


def _zone_card_cds(d, zone, default_title):
    items = [i for i in d.get("items", []) if g(i, "zone") == zone]
    if not items:
        return ""
    icon, color = ZONE_CDS[zone]
    title = g(d, {"ok": "okTitle", "as": "asTitle", "pe": "peTitle"}[zone], default_title)
    head = (
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
        f'<i class="ti {icon}" style="font-size:18px;color:{color}" aria-hidden="true"></i>'
        f'<span style="font-size:13px;font-weight:500;color:{color}">{title}</span></div>'
    )
    return (
        '<div style="background:var(--surface-2);border:0.5px solid var(--border);border-radius:12px;padding:1rem 1.25rem;">'
        + head + "".join(_item_cds(i) for i in items) + "</div>"
    )


def _flow_cds(d):
    flow = d.get("flow", [])
    if not flow:
        return ""
    rows = []
    for s in flow:
        col = "var(--text-danger)" if s.get("turn") else "var(--text-accent)"
        rows.append(
            '<div style="display:flex;gap:10px;margin-bottom:8px;">'
            f'<span style="font-size:11px;font-family:var(--font-mono);color:{col};min-width:54px;flex-shrink:0">{g(s,"n")}</span>'
            '<div>'
            f'<div style="font-size:13px;color:var(--text-primary);font-weight:500">{g(s,"title")}</div>'
            f'<div style="font-size:12px;color:var(--text-secondary);line-height:1.45">{g(s,"detail")}</div>'
            "</div></div>"
        )
    return (
        '<div style="background:var(--surface-2);border:0.5px solid var(--border);border-radius:12px;padding:1rem 1.25rem;">'
        f'<div style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:10px">{g(d,"flowTitle","Как шёл разбор")}</div>'
        + "".join(rows) + "</div>"
    )


def _arch_cds(d):
    arch = d.get("arch", [])
    if not arch:
        return ""
    rows = []
    for a in arch:
        rows.append(
            '<div style="display:flex;gap:10px;margin-bottom:8px;align-items:flex-start;">'
            f'<span style="font-size:11px;font-family:var(--font-mono);color:var(--text-accent);background:var(--bg-accent);border-radius:var(--radius);padding:2px 7px;flex-shrink:0">{g(a,"ln")}</span>'
            '<div>'
            f'<div style="font-size:13px;color:var(--text-primary);font-weight:500">{g(a,"title")}</div>'
            f'<div style="font-size:12px;color:var(--text-secondary);line-height:1.45">{g(a,"detail")}</div>'
            "</div></div>"
        )
    return (
        '<div style="background:var(--surface-2);border:0.5px solid var(--border);border-radius:12px;padding:1rem 1.25rem;">'
        f'<div style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:10px">{g(d,"archTitle","Архитектура")}</div>'
        + "".join(rows) + "</div>"
    )


def _stamp_cds(d):
    stamp = d.get("stamp", [])
    if not stamp:
        return ""
    cells = []
    for c in stamp:
        vcol = "var(--text-warning)" if c.get("soft") else "var(--text-primary)"
        cells.append(
            '<div style="background:var(--surface-1);border-radius:var(--radius);padding:0.75rem 1rem;">'
            f'<div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em">{g(c,"k")}</div>'
            f'<div style="font-size:14px;color:{vcol};font-weight:500;margin-top:3px">{g(c,"v")}</div></div>'
        )
    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;">'
        + "".join(cells) + "</div>"
    )


def build_widget(d):
    sr = ("Карта понимания: что Codex понял по задаче — зоны «понято», «допущения», "
          "«пробелы», ход разбора и архитектура, для сверки до начала работы.")
    parts = [
        f'<h2 style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);border:0;">{sr}</h2>',
        '<div style="padding:1rem 0;display:flex;flex-direction:column;gap:12px;">',
        f'<div><div style="font-size:22px;font-weight:500;color:var(--text-primary);line-height:1.2">{g(d,"title","Что я понял")}</div>',
    ]
    if g(d, "goal"):
        parts.append(f'<div style="font-size:14px;color:var(--text-secondary);line-height:1.6;margin-top:6px">{g(d,"goal")}</div>')
    parts.append("</div>")
    parts.append(_zone_card_cds(d, "ok", "Что понято"))
    parts.append(_zone_card_cds(d, "as", "Допущения · проверь"))
    parts.append(_zone_card_cds(d, "pe", "Пробелы · решаем"))
    parts.append(_flow_cds(d))
    parts.append(_arch_cds(d))
    parts.append(_stamp_cds(d))
    parts.append(
        '<div style="background:var(--surface-2);border:0.5px solid var(--border);border-radius:12px;padding:1rem 1.25rem;">'
        '<div style="font-size:13px;font-weight:500;color:var(--text-secondary);margin-bottom:8px">Сверка — всё верно или поправить?</div>'
        '<textarea id="um-fix" rows="2" placeholder="Что я понял не так? Укажи пункт и как правильно — уйдёт мне как правка" '
        'style="width:100%;font-size:13px;margin-bottom:8px"></textarea>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">'
        '<button onclick="sendPrompt(\'Карта понимания верна — можно работать\')">Понял верно ↗</button>'
        '<button onclick="var t=document.getElementById(\'um-fix\').value.trim();sendPrompt(t?(\'Правка карты понимания: \'+t):\'В карте понимания есть расхождения, сейчас уточню какие\')">Отправить правку ↗</button>'
        "</div></div>"
    )
    parts.append("</div>")
    return "".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser(description="Карта понимания: JSON → HTML (widget | standalone).")
    ap.add_argument("data", help="путь к JSON с данными карты")
    ap.add_argument("--mode", choices=["widget", "standalone"], required=True)
    ap.add_argument("--out", help="файл для standalone (если не задан — stdout)")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        d = json.load(f)

    out = build_widget(d) if args.mode == "widget" else build_standalone(d)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stdout.write(args.out)
    else:
        sys.stdout.write(out)


if __name__ == "__main__":
    main()
