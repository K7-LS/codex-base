# image-text-replace — установка и примеры

Скилл для замены текста на растровых изображениях через OCR + AI-инпейнтинг.
Полная методология — в [SKILL.md](SKILL.md). **Status: v0.2 (2026-05-19),
end-to-end протестирован на реальном сканированном PDF.**

## Установка зависимостей

Все 4 пакета: `easyocr`, `iopaint`, `Pillow`, `opencv-python` (+ `numpy`)
в нашем `mcp-manifest.json` → ставятся через `setup-extras.ps1`.

Если ставить вручную:

```powershell
python -m pip install --user easyocr iopaint Pillow opencv-python numpy
```

**Важно: модель LaMa нужно загрузить однократно**, ~196 MB:

```powershell
# Создаём ASCII-safe папку (важно при кириллице в имени пользователя)
mkdir "C:\iopaint-cache\torch\hub\checkpoints"
curl -L --retry 10 --retry-delay 5 --retry-all-errors `
    -o "C:\iopaint-cache\torch\hub\checkpoints\big-lama.pt" `
    "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"
```

Сеть может рваться — curl с `--retry 10 --retry-all-errors` обычно
дотягивает за 1-2 попытки. Pipeline сам ставит `TORCH_HOME=C:\iopaint-cache\torch`
и iopaint находит модель по этому пути.

### Почему ASCII-safe путь

Windows + Python + кириллица в имени пользователя (`C:\Users\Даниил\...`)
ломает несколько вещей:
- `cv2.imread()` не открывает Unicode-пути → читаем через Pillow
  (`np.array(Image.open(path).convert("RGB"))`)
- iopaint грузит модель из `~/.cache/torch/...` и Python мангнул байты
  для имени `Даниил` → форсируем `TORCH_HOME=C:\iopaint-cache\torch`

## Quick smoke test

```powershell
# 1. Возьми любой скан с печатным русским текстом
Copy-Item "scan.png" "$HOME\.codex/base/_sandbox\test-scan.png"

# 2. Dry-run: посмотреть что OCR нашёл
python "$HOME\.agents/skills/image-text-replace\pipeline.py" `
    --input "$HOME\.codex/base/_sandbox\test-scan.png" `
    --find "АОСР" `
    --replace "АОСР-1" `
    --dry-run

# 3. Если bbox совпадают — без --dry-run
python "$HOME\.agents/skills/image-text-replace\pipeline.py" `
    --input "$HOME\.codex/base/_sandbox\test-scan.png" `
    --find "АОСР" `
    --replace "АОСР-1"

# 4. Результат: ~/.codex/base/_sandbox/test-scan.replaced.png
```

## Типовые сценарии

### 1. Заменить шифр в скане документа

```powershell
python pipeline.py `
    --input "C:\Documents\AOSR_skan.png" `
    --find "Ф.2024.NNNNNNNNN" `
    --replace "Ф.2026.MMMMMMMMM" `
    --font "C:\Windows\Fonts\arial.ttf"
```

### 2. Batch-замена в нескольких файлах одинаковыми правилами

```powershell
$files = Get-ChildItem "C:\Sканы\*.png"
foreach ($f in $files) {
    python pipeline.py `
        --input $f.FullName `
        --find "ВКР-12" `
        --replace "ВКР-13" `
        --mode fast  # на белых сканах + однотипных правках fast быстрее
}
```

### 3. Несколько замен в одном файле

```powershell
python pipeline.py `
    --input "scan.png" `
    --find "Подрядчик: ООО Рога" --replace "Подрядчик: ООО Копыта" `
    --find "Дата: 18.05.2025"   --replace "Дата: 18.05.2026"
```

### 4. Замена по regex

```powershell
python pipeline.py `
    --input "scan.png" `
    --find "\d{2}\.\d{2}\.\d{4}" --replace "18.05.2026" `
    --regex
```

### 5. Скан внутри PDF (страница со штампом-картинкой)

```powershell
# 1. Извлечь страницу как PNG через pypdfium2 или pikepdf
# 2. Применить наш скилл
# 3. Вставить обратно (см. skill pdf-edit)
```

## Тонкая настройка

### Цвет нового текста не совпадает с оригиналом

По умолчанию pipeline берёт **медианный цвет тёмных пикселей внутри bbox**.
Если результат бледнее — задать явно:

```powershell
--color "#000000"   # чёрный
--color "#1a1a1a"   # тёмно-серый
```

### Размер шрифта не совпадает

Default: `int(bbox_height × 0.85)` — обычно правильно для PaddleOCR
который рисует bbox чуть больше реальной высоты букв. Если новый текст
вылазит за оригинал:

```powershell
--font-size 18
```

### Шов после инпейнта виден

Увеличить `dilate` (захватить больше пикселей вокруг текста — анти-алиасинг):

```powershell
--dilate 8
```

### OCR не находит текст

PaddleOCR ru по умолчанию. Если на картинке смесь русского + цифр —
обычно сработает. Если только английский / только цифры:

```powershell
--ocr-lang en
--ocr-lang ch  # китайский если такое попадётся
```

Можно вообще обойти OCR — если знаешь точные координаты bbox, добавить
прямой режим. Это пока не реализовано в pipeline.py (`--bbox x,y,w,h`),
TODO для следующей итерации.

## Когда LaMa не подходит — fast mode

`--mode fast` использует `cv2.inpaint` с алгоритмом TELEA. Качество ниже,
но:
- В 50-100 раз быстрее (LaMa: 1-3 сек, TELEA: <50 мс)
- Не требует загрузки 174 MB модели
- Не зависит от torch

Применяй на:
- Белых сканах с печатным текстом без декоративных элементов
- Batch'ах в 100+ файлов где LaMa суммарно займёт час
- ПК без интернета для скачивания модели

На цветных документах, штампах, печатях, watermark'ах — **только LaMa**.

## Известные ограничения (на 2026-05-18, версия 0.1)

1. **Нет detection rotated text** — PaddleOCR умеет, но pipeline пока
   рендерит новый текст только горизонтально. Если оригинал под углом,
   получится криво.
2. **Нет multi-line wrapping** — если новый текст длиннее оригинала,
   просто вылезет за bbox. Pillow в DrawText не делает auto-wrap.
3. **font-matching = поиск похожего вручную**. Auto-detect шрифта
   оригинала не реализован (Adobe `font_recommend` платный, своих
   моделей не нашли). Workaround: использовать **один и тот же шрифт
   для всех документов** в пайплайне (твой типичный документ ведь
   набирается в Times/Arial?).
4. **HuggingFace зависимость** — первое скачивание модели LaMa
   ходит на huggingface.co. На полностью оффлайн-машине положить
   модель руками в `~/.cache/iopaint/big_lama/`.

## Альтернативы которые НЕ взяли

- **Adobe Firefly MCP** — `image_fill_area` + `fill_text` есть в API,
  но Adobe явно пишет «text removal from photo — not available»
  (см. session-report 2026-05-15).
- **Stable Diffusion inpaint** — для документов overkill, шанс
  галлюцинаций выше чем у специализированной LaMa.
- **OpenCV-only** — без OCR пользователь должен задавать bbox руками,
  это не scaleable.
- **Google Document AI** — облако, paid, требует выгрузки изображений
  во внешний сервис (для документов клиентов — не делаем).

## Тесты — выполнены 2026-05-19

### Test 1 — синтетический скан (smoke)

Генерация: `tmp/make-test-scan.py` создаёт PNG 1200×800 с текстом
«Шифр документа: Ф.2024.NNNNNNNNN» + другой контент.

Запуск:
```powershell
python pipeline.py --input test-scan-input.png `
    --find "Ф.2024.NNNNNNNNN" --replace "Ф.2026.MMMMMMMMM" --mode lama
```

Результат: «Ф.2024.NNNNNNNNN» заменён на «Ф.2026.MMMMMMMMM», цвет
подобран автоматически из bbox оригинала, шов после LaMa инпейнта
не виден. **PASSED.**

### Test 2 — реальный сканированный КП

Файл: `КП <организация> АХП от 07.05.26.pdf` (4 страницы, все сканы, ~1 MB).

native custom agent plan:
1. Render 4 страниц в PNG через pypdfium2 (200 DPI).
2. OCR на каждой → find_value_near_label('Итоговая.*сумм') нашёл
   на стр. 4: label «Итоговая сумма (вкл НДС)» (conf 1.00) + value
   «144 105 177,91» (conf 0.998).
3. Compute new = 144105177.91 × 1.2 = 172926213.49 → форматирую
   как «172 926 213,49».
4. pipeline.py --mode lama --find "144 105 177,91" --replace "172 926 213,49"
   → page-4-replaced.png.
5. Pillow `save_all` собрал 4 страницы в `КП <организация> АХП от 07.05.26 (+20%).pdf`
   на Desktop. 1.42 MB.

**PASSED.** Замена визуально неотличима от оригинального шрифта,
LaMa чисто стёр прежнее число. См. session-report
`2026-05-15_handoff-manifest-extras-installer-stage8/artifacts/`.

## Найденные баги (fixed в v0.2)

1. **cv2.imread не читает Unicode-пути** (Cyrillic username) →
   `easyocr.readtext(np.array(Image.open(path).convert("RGB")))`.
2. **color sampling из cleaned image** возвращал почти-белый →
   текст невидим. Fix: семплировать из `original_path`, не из
   `cleaned_path`.
3. **PaddleOCR 3.x качает модели с baidu CDN** который недоступен с
   нашей сети → заменили на EasyOCR (модели с GitHub Releases).
4. **iopaint грузит модель из `~/.cache/torch/...`** который ломается
   на Windows с кириллицей в username → форсируем
   `TORCH_HOME=C:\iopaint-cache\torch`.
5. **LaMa download через iopaint рвался на 46-51%** (MD5 mismatch).
   Workaround: качать модель руками через `curl --retry 10` в
   ASCII-safe путь перед первым запуском.
6. **Color sampling сероватый** — брал bottom 30 percentile интенсивности
   как «тёмные пиксели», но туда попадали anti-aliased edge-pixels →
   median ~rgb(98,98,98) серый вместо чёрного. Fix: bottom **10**
   percentile = только ядро штрихов = `rgb(21,21,21)`. Замечено
   пользователем на КП <организация> АХП 2026-05-19.
7. **Текст «слишком цифровой»** — crisp ImageDraw render очевидно
   отличался от сканового текста (тот имеет ink-bleed, scan blur,
   шум). Fix: интегрирован полноценный `_render_scan_realistic()` стек
   (v0.3):
   - Render at 2× scale → LANCZOS downsample → natural anti-aliasing
   - Horizontal motion blur 3-tap (имитация ink-bleed принтера)
   - Gaussian blur 0.3 px → soft edges
   - Subpixel char jitter ±0.4-0.8 px
   - Contrast × 0.95 → washed scan look
   - Edge noise = local bg noise std × 0.8 на alpha-transition pixels

   Контролируется параметром `scan_realistic_degrade=True` (default).
   Для debug crisp-режима: `--no-scan-degrade` в CLI.

## API (Python lib)

```python
from pipeline import replace_text_in_image, run_ocr, find_value_near_label

# Базовый find/replace со scan degradation (default)
result = replace_text_in_image(
    input_path="scan.png",
    replacements=[("old", "new")],
    font_path="C:/Windows/Fonts/arialbd.ttf",
    mode="lama",
)

# Debug: crisp digital render без degradation
result = replace_text_in_image(
    input_path="scan.png",
    replacements=[("old", "new")],
    scan_realistic_degrade=False,
)

# Helper для "Label: value" сценариев — найти лейбл и взять
# value справа от него на той же строке (КП <организация> use-case)
matches = run_ocr("scan.png")
label, value = find_value_near_label(matches, r"Итог.*сумм")
# label.text = "Итоговая сумма (вкл НДС)"
# value.text = "144 105 177,91"
```

## Связанные

- [SKILL.md](SKILL.md) — методология подключения
- [[../skills|каталог скиллов]]
- [[../pdf-edit/SKILL|pdf-edit]] — частая связка (PDF → картинка → этот скилл → вставка)
- [[../../session-reports/2026-05-15_handoff-manifest-extras-installer-stage8/harvested/image-text-replace-stack|harvest заметки]]
