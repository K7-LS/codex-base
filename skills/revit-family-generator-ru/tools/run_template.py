# -*- coding: utf-8 -*-
# run_template.py — шаблон раннера для канала Routes (execfile файлом, не inline).
# Скопировать в C:\rvt_stage\gen\run_<имя>.py, подставить плейсхолдеры:
#   {{JSON_PATH}}    — r'C:\rvt_stage\gen\smoke\<family>.json'
#   {{REPORT_NAME}}  — 'gen_run_<имя>' (отчёт: C:\rvt_stage\gen\out\<report>.json + .done)
#   {{OUT_RFA}}      — r'C:\rvt_stage\gen\out\<имя>.rfa' или None (дефолт по family.name)
#   {{SHOW}}         — True (открыть результат в UI владельцу) / False
# Ловушки: sys.modules-pop обязателен (кэш IronPython); отчёт ждать по .done + mtime.
import sys

sys.path.append(r'C:\rvt_stage\gen')
sys.path.append(r'C:\rvt_stage\verify')
for _m in list(sys.modules):
    if _m.startswith('gen_') or _m.startswith('vf_'):
        sys.modules.pop(_m, None)

import clr
clr.AddReference('RevitAPI')
import gen_run

verdict = gen_run.run({{JSON_PATH}}, show={{SHOW}},
                      out_rfa={{OUT_RFA}},
                      report_name='{{REPORT_NAME}}')
print('gen_run verdict: %s' % verdict)
