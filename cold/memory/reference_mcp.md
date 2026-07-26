# Lazy tool capabilities

Codex-base маршрутизирует работу по capability ID, а не по имени конкретного
MCP-сервера или plugin.

## Правила

- Ни один внешний инструмент не обязателен для простого разговора.
- Навык объявляет `required_capabilities` в каталоге.
- Инструмент подключается lazy только после выбора навыка.
- База не устанавливает, не включает и не авторизует MCP/plugins сама.
- `doctor` возвращает `READY`, `BLOCKED` или `NOT_REQUIRED`.
- Отсутствующая обязательная capability → `BLOCKED`, а не имитация результата.

Типовые capability: `document.word.read`, `spreadsheet.read`, `pdf.read`,
`web.fetch`, `web.search`, `web.browser.interact`, `cad.read`,
`revit.inspect`. Конкретный provider выбирается текущим host и может меняться
без изменения методологии навыка.
