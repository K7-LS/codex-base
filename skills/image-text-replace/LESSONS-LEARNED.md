# image-text-replace — Lessons Learned (КП <организация> АХП case, 2026-05-19)

Реальный production case: добавить « 20%» к лейблу «Итоговая сумма (вкл. НДС)»
в сканированный PDF (4 страницы, бухгалтерское КП). После **16 итераций**
v0.1 → v3.0 — финальный результат принят пользователем как «именно то что
нужно».

Этот документ фиксирует **ключевые уроки** чтобы следующий случай не
повторил все 16 шагов.

## TL;DR — порядок действий для нового кейса

1. **CALIBRATION SHEET ПЕРВЫМ.** Перед любым tuning — отрендерить такую
   же строку в 10+ шрифтах рядом со сканом → подобрать визуально.
   Без этого можно потратить часы на tuning неправильного шрифта.
2. **Reference = ячейка-сосед**, не сам label. Цвет/размер/PSF берём из
   ближайшей text-cell тоже типа value (числа).
3. **Cap height detector** должен игнорировать descenders (запятые,
   скобки): row = "core stroke" если dark pixels > 30% bbox width.
4. **Position via midline** (центр строки), не baseline и не top.
5. **SD inpaint strength 0.10** на финал — добавляет scan-look без
   hallucination risk.

## Главное открытие — сканированный финансовый документ часто использует Times Bold

8 итераций были потрачены на tuning Arial Regular. Все попытки делали
"plausibly close" но в итоге всегда «не такой». Font calibration sheet
(render «16 877,50» в 10 шрифтах) показал что cells в нашем КП — **Times
Bold**, не Arial.

**Признаки serif font в скане:**
- Серифы (горизонтальные штрихи) на цифре «7»
- Прямоугольные пропорции цифр (не круглые)
- Slab-like character density
- Bold weight

**Если scan имеет эти признаки** → пробовать `timesbd.ttf` ПЕРВЫМ, не arial.

## Анти-паттерны (не повторять)

### 1. Blind iteration по одному параметру

Я делал так:
- User: "светлее" → я делаю цвет darker
- User: "ниже" → я двигаю text вниз
- User: "толще" → я добавляю dilation
- User: "тоньше" → я убираю dilation

Это градиентный спуск **без понимания** что user видит. Каждый фикс ломал
что-то другое. Правильно: **diagnose first** — попросить у user конкретную
характеристику (font / size / weight / color / position / sharpness)
**перед** изменением.

### 2. Размер из full OCR bbox

Включает descenders (запятые, нижние части скобок). Дает font_size
~+30% от реальной cap height → текст визуально крупнее cells.

**Правильно:** smart cap detector — row считается "core stroke" только
если dark pixels >= 30% bbox width. Это игнорирует isolated descender
pixels.

### 3. Histogram match с high blend strength

Strength 0.85 → текст становится hollow/transparent (color values mapped
into reference distribution overshoots). Strength 0.25-0.4 — sweet spot
для preserving original character shape + adding variance.

### 4. Multiple "scan-style" tricks одновременно

Если применять одновременно: PSF blur + texture residual + histogram
match + edge noise — каждый шаг "разводит" контраст. Результат: text
менее dark чем нужно.

Лучше: **минимум tricks** для нужного эффекта. У нас:
- PSF blur с halved sigma (sharpness preserved)
- Skip texture residual (вносит light noise)
- Skip hist match (push'ит к greyer values)
- Just SD low-strength на финал

### 5. Bold через dilation

cv2.dilate alpha mask делает strokes толще — но это явно "bold"
appearance, не "scan-natural". Cell digits регулярного веса имеют
определённую плотность от toner spread, не от dilation.

**Правильно:** render at slightly larger font size, downsample to target —
natural Lanczos anti-alias дает thickness без явного bold.

## Финальный pipeline для типичного сканированного документа

```python
# 1. OCR + find label + find neighbor cell digit value as reference
matches = run_ocr(scan_path)
label = find_match(matches, label_pattern)
cell_ref = find_neighbor_digit_match(matches, label, side='right')

# 2. Smart cap_height detection on reference cell (ignore commas/parens)
cell_cap_top, cell_cap_bottom = smart_cap_detect(arr, cell_ref.bbox)

# 3. Reference samples from CELL (color, PSF, noise std)
text_color = sample_color(arr, cell_ref.bbox, percentile=2)  # very dark cores
psf_sigma = estimate_psf(arr, cell_ref.bbox) * 0.5  # halved for sharpness
noise_std = sample_bg_noise(arr, cell_ref.bbox)

# 4. Font — preferably the one matched by calibration sheet
font_path = "C:/Windows/Fonts/timesbd.ttf"  # Times Bold for typical scans
font_size = round(cell_cap_height * 1.42)

# 5. Render with minimal degradation
rgb_text, alpha_text, offset = render_scan_realistic(
    font, font_size, "20%", text_color, noise_std,
    psf_sigma=psf_sigma,
)

# 6. Position via midline alignment
label_midline = (label_top + label_bottom) // 2
cell_midline = (cell_cap_top + cell_cap_bottom) // 2
target_midline = (label_midline + cell_midline) // 2
paste_y = target_midline - text_canvas_midline

# 7. Blend
arr = blend(arr, rgb_text, alpha_text, paste_x, paste_y)

# 8. SD low-strength scan-ify на финал
arr = sd_img2img(arr, region_around_text, strength=0.10, steps=15)
```

## SD download caveat

`stabilityai/stable-diffusion-2-inpainting` deprecated (404 на API).
Use `runwayml/stable-diffusion-inpainting` mirror. Download = 3.4 GB
UNet + smaller VAE/text_encoder/safety_checker. На корп-сети с прерываниями
- huggingface_hub resume_download автоматический, но `ignore_patterns`
  должен включать `*.bin` файлы тоже (не только `.safetensors`!)
- ASCII-safe cache dir `C:/sd-cache` обязателен (HF symlinks ломаются на
  Cyrillic-username paths)

## Время

- 16 итераций render параметров
- 1 итерация font calibration (решающая!)
- 1 SD download + 1 SD inpaint run
- ETA для следующего similar case: с этим документом + правильным шрифтом
  с первой попытки = **15 минут** вместо 4+ часов.

## §6 Унификация font_size для batch замены (КП ЛС АХП v7, 2026-05-20)

### Симптом

После v6.1 pipeline (`do_v6_surgical.py`) при replacement 13 ячеек на
странице 3 КП ЛС АХП — визуально цифры разного размера: в одной строке
выглядят меньше, в другой крупнее.

### Корень

`do_v6_surgical.py:169`:

```python
orig_h_real = anc["bottom_y"] - anc["top_y"]  # per-cell
font_size = max(10, int(orig_h_real / cap_ratio))  # per-cell
```

Каждая ячейка получает **свой** `orig_h_real` (через
`find_dark_anchors` или `smart_cap_height_detect`). OCR bbox содержит
±2-3px noise → cap_height варьируется → font_size меняется на ±1-2pt
между строками. В документе где все Regular-цифры должны быть одного
размера — это сразу заметно.

Из реальных данных v7 run:

```
[unified] Regular: heights=[18, 18, 19, 18, 17, 18, 18, 18, 17, 17, 19, 20]
```

Variance 17-20 → font_size 25-30pt в зависимости от строки.

### Фикс

Pre-pass до основного цикла: посчитать `median(cap_height)` отдельно
по weight-категории (Regular vs Bold), затем использовать ОДИН font_size
на категорию.

Реализован как `unify_font_size_for_batch()` в `pipeline.py` (v3.1+).

```python
from pipeline import unify_font_size_for_batch

regular_matches = [m for m in target_matches if m.bbox_rect()[1] < BOLD_Y]
bold_matches    = [m for m in target_matches if m.bbox_rect()[1] >= BOLD_Y]

font_size_reg, _  = unify_font_size_for_batch(arr, regular_matches, cap_ratio=0.66)
font_size_bold, _ = unify_font_size_for_batch(arr, bold_matches,    cap_ratio=0.70)

for m in target_matches:
    is_bold = m.bbox_rect()[1] >= BOLD_Y
    font_size = font_size_bold if is_bold else font_size_reg
    # ... render ...
```

Median (а не mean) — устойчив к outliers OCR bbox (1 сильно неправильный
bbox не должен сдвигать font_size всей группы).

### Когда применять

- **Всегда** для batch text replacement (3+ ячеек одной категории) в
  табличных документах.
- **Не применять**, если ячейки **действительно** разного размера в
  оригинале (например header bold large + body regular small) —
  в этом случае разделить на 2 batch'а по визуальному размеру и
  unify каждую отдельно.

### Тесты

См. `~/.codex/base/evals/test_image_text_replace.py` →
`TestUnifyFontSizeForBatch` (5 кейсов включая воспроизведение
heights из реального КП ЛС АХП v7).

## §7 OCR-альтернативы — DocTR и PaddleOCR проверены, не взяты (2026-05-20)

### Контекст

После 22+ итераций (<организация> АХП 16 + ЛС АХП 6) возникло подозрение что
EasyOCR — источник нестабильности bbox и корень всех bug'ов с позицией.
Запущен harvest (см. `session-reports/2026-05-20_base-audit/harvested/
scan-text-replace-alternatives.md`) — 5 кандидатов из 3 категорий.

### Эмпирический benchmark на КП ЛС АХП page3.png

**EasyOCR baseline (наш текущий):**
- heights `[18, 18, 19, 18, 17, 18, 18, 18, 17, 17, 19, 20]`
- median = 18, **std = 0.90**, range = 3

**DocTR (Mindee, Apache-2.0, polygon bbox обещало быть лучше):**
- найдено 29 numeric matches вместо ожидаемых 12 (false positives)
- DocTR агрессивно делит `1 679,11` на 2 слова (`1679,11` + `492,61`)
- cap_heights `[17,16,17,16,8,17,15,15,16,16,13,16,18,16,18,17,4,18,9,...]`
- median = 16, **std = 3.23** — в **3.6× хуже** EasyOCR
- outliers 4, 8, 9, 12 — descenders / partial detections

**PaddleOCR PP-StructureV3:**
- Установка ОК (paddleocr 3.5.0 + paddlex[ocr] 3.5.2)
- baidu CDN (`paddlepaddle.org.cn`) **доступен напрямую** (status=200) — корп-прокси
  НЕ виноват
- НО: модели **скачиваются частично** в `~/.paddlex/official_models/`
  и при load падают `RuntimeError: json.exception.parse_error.101:
  empty input`. После clean cache + retry — скачалось 6.6 MB из
  ожидаемых ~200 MB. Silent network failures.
- Невозможно использовать без deep debug paddle installer'а.

### Корневой вывод

**OCR не был источником боли.** EasyOCR std=0.90 — это **очень устойчивый**
bbox. Проблема была в **per-cell font_size** в нашем коде (см. §6).

После внедрения `unify_font_size_for_batch()` (§6) — переход на другой
OCR-движок даёт **diminishing returns** или, как в случае DocTR,
**деградацию**.

### Что не брать (с обоснованием)

- **DocTR** — agressive word-segmentation, false positives, std в 3.6× хуже.
- **PaddleOCR PP-Structure** — не запускается reliably в нашей среде
  (silent model download failures).
- **AnyText** (Category C, end-to-end) — не пробовали, conda-only,
  cyrillic editing не подтверждён. Backlog если возникнет реальная
  необходимость в radical-апгрейде.

### Action items для будущего

1. **Не возвращаться к замене EasyOCR без новых данных** — мы потратили
   на это исследование ~1 сессии, результат отрицательный.
2. Если bbox опять окажется проблемой — сначала проверить `std` через
   `unify_font_size_for_batch` diagnostic dict. Если std уже < 1.5 —
   корень не в OCR.
3. AnyText проверить только при появлении **custom agent где нужно editing
   многих стилей одновременно** (не наш текущий tabular use case).

## Связанные

- `pipeline.py` — главная реализация (`unify_font_size_for_batch`)
- `SKILL.md` — описание скилла
- `ROADMAP-heavy-options.md` — другие подходы (CNN style transfer и др.)
- `~/.codex/base/evals/test_image_text_replace.py` — regression-тесты
- `~/.codex/base/session-reports/2026-05-20_base-audit/harvested/scan-text-replace-alternatives.md` — полный отчёт harvest 5 кандидатов
