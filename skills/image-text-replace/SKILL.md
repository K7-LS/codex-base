---
name: image-text-replace
description: Use when в скане или изображении нужно заменить текст.
---

# image-text-replace v3.1

Скилл для **программной замены/вставки текста** на сканированных
растровых изображениях. Финансовые документы (КП, акты, счета),
техническая документация, отсканированные таблицы.

## ⚠ ОБЯЗАТЕЛЬНОЕ правило перед первым render (для нового документа)

**ПЕРЕД** любым LaMa inpaint / render / SD pass на скан, **который
ранее не обрабатывался в данной сессии** — Codex **обязан** вызвать
`request_user_input`:

```yaml
question: "Документ <имя.pdf>: выполнена ли font calibration?"
header: "Calibration"
options:
  - label: "Нет, прогнать calibration.py сейчас (Recommended)"
    description: "30 секунд: render эталонной строки в 12 шрифтах → визуально подобрать. Защита от потери 3+ итераций на неверном шрифте."
  - label: "Да, шрифт известен"
    description: "Указать font path в --font параметре pipeline (например C:/Windows/Fonts/timesbd.ttf)."
  - label: "Пропускаем, default Times Bold"
    description: "Понимаю риск: <организация> АХП case — 8 итераций на Arial; LS АХП case — 3 итерации на Bold vs Regular."
```

**Без явного ответа пользователя — Шаг 2 (pipeline) не запускать.**

**Почему правило-«пометка» в LESSONS-LEARNED не сработала:** пропуск
калибровки **повторился в LS АХП case** (2026-05-20) несмотря на
урок из <организация> АХП case (2026-05-19). Жёсткий guard через request_user_input
защищает от повторения как у `stroy-formatting` со стилями.

**Исключение** — если пользователь **явно** в запросе указал
шрифт или сказал «работаю с тем же шаблоном что и раньше, шрифт
`<path>`» — calibration можно пропустить, переход к Шагу 2.

## ⚠ ОБЯЗАТЕЛЬНОЕ правило для буквенных ячеек (импорт из LS case)

Если в pipeline есть SD pass на ячейку **с буквами** (русские/латинские)
— **не использовать** `refine_text_region_with_diffusion` (он может
галлюцинировать символы при strength > 0.15: Н→П в LS case).

**Использовать** `refine_bg_with_diffusion` (refine'ит только фон
вокруг текста через inverse-alpha mask, zero risk искажения символов).

Для **числовых** ячеек `refine_text_region_with_diffusion` остаётся
default — цифры устойчивее к SD distortion.

## Когда подключать

- Пользователь приложил скан/PDF и сказал «здесь должно быть X вместо Y»
- В рамках pdf-edit/word-helper нужно поменять текст в **картинке**
  внутри документа
- Batch-замена однотипного текста в 10+ сканах (например, шифры,
  даты, проценты)

**Не подключать:**
- Векторный PDF где текст редактируется напрямую → используй pikepdf/pypdf напрямую (см. skill pdf-edit)
- Просто извлечь текст → `paddleocr`/`easyocr` напрямую
- Один-два файла с Photoshop/Acrobat под рукой → user делает руками

## native custom agent plan v3.0 (для нового типа документа)

### Шаг 1 — Font calibration (5 минут, делается ОДИН раз для типа документа)

```powershell
# Render same digits в 12 fonts рядом со scan → визуально подобрать matching
python ~/.agents/skills/image-text-replace/calibration.py `
    --input scan.png `
    --bbox 1114,686,96,26 `        # OCR bbox любого числа на скане
    --text "16 877,50" `             # сам text для render
    --output font-sheet.png

# Открой font-sheet.png → выбери row которая LOOKS наиболее похожа на REAL SCAN
# Запомни font path (e.g. "C:/Windows/Fonts/timesbd.ttf")
```

Без этого шага можно потратить часы на render param tuning неправильного
шрифта.

### Шаг 2 — Замена/вставка через pipeline

```powershell
python ~/.agents/skills/image-text-replace/pipeline.py `
    --input scan.png `
    --find "Ф.2024.NNNNNNNNN" `
    --replace "Ф.2026.MMMMMMMMM" `
    --font "C:/Windows/Fonts/timesbd.ttf"  ` # ← из calibration!
    --mode lama `
    --sd-refine `                          # ← v3.0 финальный SD pass
    --sd-strength 0.10
```

Pipeline автоматически:
1. OCR → bbox целевого text
2. `find_neighbor_cell_reference()` → берём ref color/PSF/size с ячейки рядом
3. `smart_cap_height_detect()` → font_size без descender ошибок
4. Render с matching font + minimal degradation
5. `compute_midline_paste_y()` → centered alignment
6. LaMa inpaint → erase old text
7. Blend rendered new text
8. **SD img2img strength=0.10** → final scan-ification

### Шаг 3 — Verification

```powershell
# Render result region, eyeball compare к surrounding text
python -c "from PIL import Image; Image.open('scan.replaced.png').crop((x,y,x+w,y+h)).resize((W*3,H*3)).save('result-zoom.png')"
```

Если **не матч** — see LESSONS-LEARNED.md перед next iteration.
**Не tune blindly.** Diagnose: font / size / weight / color / position / sharpness.

## Pipeline в одном экране

```
input.png (scan)
    │
    ├── EasyOCR.readtext(input)
    │       └→ [(text, bbox, conf), ...]
    │
    ├── filter_matches → label OCR bbox
    │
    ├── find_neighbor_cell_reference(matches, label, side='right', digits_only=True)
    │       └→ cell_ref OCR match (для color/PSF/font matching)
    │
    ├── smart_cap_height_detect(cell_ref.bbox) → cell_cap_height
    │       (игнорирует descenders запятой "16 877,50")
    │
    ├── sample text_color, noise_std, psf_sigma из cell_ref region
    │
    ├── _render_scan_realistic(font=TIMES BOLD, size=cap_h × 1.42,
    │                          psf_sigma=measured × 0.5)
    │       └→ rgb_text, alpha, canvas anchors
    │
    ├── compute_midline_paste_y(label_anchors, cell_anchors, ...)
    │       └→ paste_x, paste_y
    │
    ├── LaMa inpaint (mode=lama) erase old text → cleaned.png
    │
    ├── Blend rendered text onto cleaned at paste position
    │
    └── [v3.0] refine_text_region_with_diffusion(crop_bbox,
                                                    strength=0.10)
            → final scan-style polish via SD
```

## Зависимости

| Пакет | Размер | Required for |
|-------|--------|-------------|
| `easyocr` | ~140 MB + 100 MB models | OCR с bbox |
| `Pillow` | ~3 MB | render |
| `opencv-python` | ~30 MB | mask ops |
| `iopaint` (LaMa) | ~200 MB + 174 MB model | inpaint backend |
| `diffusers` + `transformers` + `accelerate` | ~500 MB + **3.4 GB SD model** | v3.0 SD refine |

Базовые (без SD) — лениво ставятся при первом запуске. SD требует
явной установки + HF auth + ASCII-safe cache dir `C:/sd-cache`.

## SD setup (только для v3.0 финального pass)

```powershell
# 1. Создать HF token (https://huggingface.co/settings/tokens, Read access)
$env:HF_TOKEN = "hf_..."
$env:HF_HOME = "C:/sd-cache"

# 2. Скачать model (3.4 GB, на корп-сети может занять ~30-60 min):
python -c "
import os
os.environ['HF_HOME'] = 'C:/sd-cache'
from huggingface_hub import snapshot_download, login
login(token=os.environ['HF_TOKEN'])
snapshot_download(
    repo_id='runwayml/stable-diffusion-inpainting',
    cache_dir='C:/sd-cache',
    allow_patterns=['*.json', '*.txt', '*.safetensors', '*.bin'],
)
"

# 3. Revoke token после первой загрузки (cache сохранится локально)
```

## Failure modes

1. **Hallucinated characters в SD pass** — strength > 0.20 на digits.
   Mitigation: держать `--sd-strength <= 0.15` для финансовых documents.
2. **OCR confidence < 0.7** — skill ОСТАНАВЛИВАЕТСЯ, не fall back на
   regex/fuzzy без явного `--fuzzy`.
3. **Несколько матчей find pattern** — show OCR results + ask user.
4. **No neighbor cell found** — fall back к label own bbox (lower quality).

## Связанные

- `LESSONS-LEARNED.md` (в папке скилла) — 16-итераций retrospective + anti-patterns
- `ROADMAP-heavy-options.md` (в папке скилла) — 4 heavy techniques (PSF, Borrow, SD, CNN)
- скилл `doc-extract` — единственный вход извлечения из PDF; сканы без текст-слоя маршрутизирует сюда
- скилл `pdf-edit` — редактирование PDF (связка PDF → image → этот скилл → PDF)
- harvest-источники см. в секции «Источники (harvest)» ниже (Appt-OCR, IOPaint, PaddleOCR)

## Источники (harvest)

- [Appt-OCR](https://github.com/aarontzeng/Appt-OCR) — архитектурное вдохновение
- [IOPaint](https://github.com/Sanster/IOPaint) — LaMa backend
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) — OCR engine (заменил PaddleOCR из-за CDN issues)
- [runwayml/stable-diffusion-inpainting](https://huggingface.co/runwayml/stable-diffusion-inpainting) — SD model (v3.0)
- [PERO-Enhance](https://github.com/DCGM/pero-enhance) — fallback option

## Versioning

- v0.1-v0.3: crisp digital — deprecated
- v0.5: PSF estimation (Option 3) — kept as helper
- v0.6: glyph borrowing (Option 4) — opt-in helper
- v1.4: cap-height font sizing — integrated
- v2.3: Times Bold default — integrated
- v3.0: SD scan-ification — production stack (КП <организация> АХП case, 2026-05-19)
- **v3.1**: hard calibration guard через request_user_input + `refine_bg_with_diffusion` preference для буквенных ячеек (импорт из КП ЛС АХП case, 2026-05-20)

## Tools (слой 3)

В папке скилла лежат детерминированные скрипты — это 3-й слой стандарта
скиллов (Description + Instructions + **Tools**): повторяемая логика вынесена
в код, а не пересобирается моделью каждый раз.

- `pipeline.py` — основной OCR → mask → LaMa inpaint → render → SD-refine pipeline (Шаг 2).
- `calibration.py` — font calibration: render эталонной строки в 12 шрифтах для визуального подбора (Шаг 1).

Скрипты вызываются как `python ~/.agents/skills/image-text-replace/<script>.py` (см. native custom agent plan выше).
