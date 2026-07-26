# reference_revit_mcp — pyRevit MCP (Revit-Connector): паттерны и грабли

Канонический справочник по live-работе с Autodesk Revit через MCP `Revit-Connector`
(pyRevit Routes). Распространяется со всей базой. Локальная копия-удобство (авто-load при
работе в папке сервера) — `~/.codex/base/mcp-servers/revit-mcp-python/AGENTS.md` (в git НЕ трекается).
Используется агентом [[pyrevit-engineer]]. Сервер в `mcp-manifest.json` (tier optional, needs_admin).

## Что это
Мост Codex → `main.py` (FastMCP) → pyRevit Routes (REST внутри Revit, `127.0.0.1:48884`)
→ Revit API. Ключевой инструмент `execute_revit_code` (IronPython 2.7 в контексте `doc`; доступны
`doc`/`uidoc`/`DB`/`revit`/`print`) + ~18 готовых tools (get_revit_model_info, list_levels,
list_revit_views, get_revit_view, list_families, place_family, color_splash, и др.).
Repo: github.com/revit-mcp/revit-mcp-python (MIT). Routes в draft, БЕЗ аутентификации.

## Установка/подключение (кратко; полно — post_install_note в манифесте)
Нужны Revit + pyRevit + admin. Шаги в Revit UI (за пользователем): Extensions → «MCP Server for
Revit Python» → Install+Enable; Settings → Routes → on; `%APPDATA%\pyRevit\pyRevit_config.ini`
секция `[routes]`: `server_host="127.0.0.1"`, `server_port=48884` (по умолчанию 0.0.0.0 — небезопасно);
pyRevit Reload; проверка `http://127.0.0.1:48884/revit_mcp/status/`; restart Codex.

## Инструменты не видит Codex — СНАЧАЛА ToolSearch (deferred), НЕ чинить мост

Инструменты Revit-Connector приходят DEFERRED: висят в списке по имени, схемы НЕ загружены,
вызвать нельзя. «Коннектор не появился» ≠ мост мёртв — это норма. ПЕРВЫМ делом оживить одной строкой:
`ToolSearch query "select:capability `revit.inspect`,capability `revit.inspect`"`
После КАЖДОГО реконнекта — это первым, затем `get_revit_status`. Строить HTTP-обход на Routes
(POST `/execute_code/`) НЕ надо — костыль вокруг несуществующей проблемы.

## "Failed to connect" у uv-серверов — команда `uv run --with` рвёт connect-таймаут

Симптом: `Codex mcp list` → Revit-Connector (и все uvx/uv-run серверы) `× Failed to connect`,
а прямой HTTP на Routes `:48884` даёт 200 (Revit жив). Причина: `uv run --with mcp[cli] mcp run main.py`
при каждом старте резолвит окружение (~6с, докачивает `--with`-оверлей) → дольше connect-таймаута.
Фикс — прямой запуск из venv (mcp[cli] уже в `.venv`, `main.py` имеет `__main__`→`mcp.run(stdio)`):
```
Codex mcp remove Revit-Connector -s user
Codex mcp add Revit-Connector -s user -- <install_dir>\.venv\Scripts\python.exe <install_dir>\main.py
```
Старт <1с, handshake сразу (тест: пайп initialize-JSON в эту команду → result за ~1с). Тот же паттерн
у рабочего autocad-mcp (прямой venv python, не uvx). После правки — реконнект/рестарт, затем ToolSearch select.

## Подключение мертво / команды виснут — диагностика отказа (прокси / IPv6 / Home / 2 копии)

Симптомы (Revit при этом открыт и исправен): ВСЕ MCP-команды → `Request timed out after Ns`,
ИЛИ `Error: 503 - ` (ПУСТОЕ тело), ИЛИ `Server disconnected without sending a response`.
**НЕ перезапускать Revit вслепую.** Сначала отделить «коннектор» от «Revit» прямым HTTP:
```powershell
Invoke-WebRequest http://127.0.0.1:48884/revit_mcp/status/ -UseBasicParsing   # 200 = Revit/Routes ЖИВЫ
Get-NetTCPConnection -State Listen | ? LocalPort -eq 48884                      # порт слушается?
```
Прямой HTTP даёт 200, а MCP-команда висит/503 → проблема в python-обёртке (`main.py`), НЕ в Revit.
Тело 500/503 читать через `[Net.HttpWebRequest]` (там точная причина: «route does not exist» ≠ поломка).

**(1) Корп-прокси — главная и самая неочевидная причина.** `httpx` (по умолчанию `trust_env=True`)
гонит ДАЖE `http://127.0.0.1:48884` через `HTTP_PROXY`, когда `NO_PROXY` не задан. Прокси не достаёт
до localhost клиента → **`503` с ПУСТЫМ телом** (а обработчик `/status/` при ошибке отдаёт 503 с JSON —
значит пустой 503 пришёл НЕ от Revit). Репро тем же httpx:
`httpx.get(url)` → 503 len0; `httpx.Client(trust_env=False).get(url)` → 200.
ФИКС: обоим `httpx.AsyncClient(...)` в `main.py` добавить `trust_env=False` (в `revit_image` и
`_revit_call`). Системно — задать `NO_PROXY=127.0.0.1,localhost,::1` (см. [[proxy_github]]).

**(2) localhost → IPv6.** Routes слушает `0.0.0.0:48884` (только IPv4). На Windows `localhost`
резолвится в IPv6 `::1` первым → прямой httpx виснет. ФИКС: `REVIT_HOST = "127.0.0.1"` в `main.py`.
Тест: `http://[::1]:48884/...` → connection refused, `http://127.0.0.1:48884/...` → 200.

**(3) Home-экран Revit = «нет активного документа».** `Error: 503 -` (тут JSON «No active Revit
document») при открытой модели → активна стартовая страница Revit, `ActiveUIDocument=None`.
Лечение: открыть/активировать ВИД модели (двойной клик по плану), закрыть Home-экран.

**Грабли: ДВЕ копии `main.py`.** Codex запускает MCP-КЛИЕНТ из `~/.codex/base/mcp-servers/revit-mcp-python/main.py`
(точно определять по CommandLine: `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` → строка
с `mcp.exe run ...main.py`). Вторая копия — серверная в `%APPDATA%\pyRevit\Extensions\<...>.extension\main.py`
(это HTTP-Routes ВНУТРИ Revit), на коннектор Codex НЕ влияет — правка её бесполезна. После правки
`main.py` обязателен **Reload Window** (запущенный python держит старый код в памяти).
`mcp-servers/` НЕ в Codex-base git → правка локальна; для раздачи всем — внести в setup-extras/дистрибутив.

## Грабли и паттерны (ОБЯЗАТЕЛЬНО при live-работе)

**Кириллица.** IronPython 2.7 парсит exec-исходник как latin-1 (объявление `# coding` игнорится) →
прямые литералы `u"Текст"` ломаются (кракозябры `ÐÐ¾Ð·...`). Хелпер (идемпотентный — `str`/`unicode`
в IronPython это одно, повторный `.decode` падает):
```python
def u(s):
    try: return s.decode("utf-8")
    except Exception: return s
```
Оборачивать им ВСЕ русские литералы. Данные из Revit (`doc.Title`, имена семейств) корректны сами.

**safe_tx — транзакция с гашением диалогов.** Модальный диалог вешает Routes-поток (таймаут 60с,
запрос «зависает»). Обёртка:
```python
class Swallow(DB.IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        fa.DeleteAllWarnings(); return DB.FailureProcessingResult.Continue
def safe_tx(name, fn):
    t = DB.Transaction(doc, name); t.Start()
    fo = t.GetFailureHandlingOptions(); fo.SetForcedModalHandling(False)
    fo.SetFailuresPreprocessor(Swallow()); fo.SetClearAfterRollback(True)
    t.SetFailureHandlingOptions(fo)
    try: fn(); t.Commit(); return "ok"
    except Exception as e:
        if t.HasStarted() and not t.HasEnded(): t.RollBack()
        return "err: " + str(e)
```

**Read-only ADSK-параметры.** Электрические/тепловые ADSK-параметры (фазы, мощности) часто
формульные/из каталога семейства → `IsReadOnly=True`, через API не записать, только правкой rfa.
Проверять `p.IsReadOnly` до записи. Обозначение модели в спеках обычно в `ADSK_Марка` /
«Модель сборочной единицы» (редактируемые), не в имени типа Revit.

**Имя типа элемента.** Читать/писать `DB.Element.Name.__get__(et)` / `et.Name = ...`;
`getattr(et,'Name','?')` может вернуть default. Внимание: выноски/спеки часто читают НЕ имя типа,
а параметр (`ADSK_Марка`) — менять надо его.

**Спеки.** У `ViewSchedule` нет `TEXT_FONT`. Ячейки: `TableSectionData.GetTableCellStyle(r,c)` /
`SetCellStyle`. СКРЫТЫЕ колонки сдвигают индексы — `GetCellText(sec,r,c)` нумерует ТОЛЬКО видимые,
а `Definition.GetField(i)` — все; строить порядок видимых по `IsHidden`, иначе перепутаешь поля
(реальный случай: принял `ADSK_Масса` за `ADSK_Количество`). Ручные таблицы (ХОВС) хранят данные в
секции `Header`, не `Body`. `SetCellText` на теле стандартного расписания запрещён (значения — из
параметров элементов).

**Шрифты — 3 уровня** (унификация, напр. «GOST Common»):
1. Типы: `TextNoteType`/`DimensionType`/`SpotDimensionType` — `BuiltInParameter.TEXT_FONT`.
2. Ячейки спек — через `TableCellStyle.FontName` (`GetCellStyleOverrideOptions().Font=True`).
3. ВНУТРИ семейств: `doc.EditFamily(fam)` → в famdoc сменить `TextNoteType.TEXT_FONT` → `fdoc.LoadFamily(doc, opt)` → `fdoc.Close(False)`.
   `IFamilyLoadOptions` (out-параметры через `.Value`):
   `class FamOpt(DB.IFamilyLoadOptions): def OnFamilyFound(self,fu,ov): ov.Value=True; return True` (+ `OnSharedFamilyFound` с `src.Value=DB.FamilySource.Family`).
   EditFamily/LoadFamily МЕДЛЕННЫЕ → батчами по 3-6 (иначе таймаут 60с; ответы могут
   рассинхрониться — отправить уникальный `print`-маркер для пересинхрона). Системные «Ведомости
   изменений» — шрифт в семействе «Форма»/штампа.

**get_revit_view** не находит виды с кириллическими именами (теряется кодировка параметра) →
временно переименовать вид в ASCII (в транзакции) → отрендерить → вернуть имя. Рендерит ТОЛЬКО
модельные виды (не листы). Рендер pdf-mcp/PyMuPDF garbлит спец-шрифты (GOST type в таблицах) —
таблицы читать через API, схемы/планы визуально ок.

**Аннотации — ОБЯЗАТЕЛЬНЫЙ визуальный контроль.** После add/move выноски/текста — отрендерить и
посмотреть глазами; вслепую по координатам ставить нельзя (позиция выходит неудачной). Одна
`TextNote` может иметь НЕСКОЛЬКО leaders (одна надпись → 2+ одинаковых элемента) — при анализе
«есть ли выноска» брать ВСЕ `tn.GetLeaders()`, не `lds[0]`, иначе добавишь дубль.

**Листы/штамп.** «Листов» (общее число) — глобальный параметр (напр. «Кол-во листов»), поле штампа
`ADSK_Штамп_Количество листов` read-only подвязано к нему → менять глобальный, обновятся все листы.
Экспорт листов в PDF: `doc.Export(folder, ids, PDFExportOptions())` — путь только ASCII
(кириллица в литерале пути ломается; брать `System.IO.Path.GetTempPath()`).

**Боевые модели.** Routes без аутентификации; работать по копии, правки подтверждать, после —
предложить save/sync. Финальная приёмка поведения — на реальной модели (даже при live-MCP: до/после).
