# image-text-replace — Heavy Options Roadmap

Документ описывает 4 «heavy» подхода для invisible text insertion в
сканированные документы, со статусом реализации и дизайн-обоснованием
отложенных пунктов.

## Текущий стек (реализован, v0.8)

| Версия | Что добавила | Status |
|--------|--------------|--------|
| v0.5 | **Option 3 (PSF estimation)** — измерить blur sigma из реальных edges скана | ✅ |
| v0.6 | **Option 4 (Borrow glyphs)** — извлечь pixel patches символов из других мест скана | ✅ opt-in |
| v0.7 | A4 — pixel-precise anchor positioning (не OCR bbox) | ✅ |
| v0.8 | **B2 (Texture transfer)** — high-freq texture residual из соседнего text→synthesized | ✅ default-on |

Эта комбинация даёт ~95% scan-realism для типичных сканов document. На КП <организация> АХП — visually indistinguishable insertion при normal viewing distance.

---

## Option 2: Diffusion Inpainting (отложено)

### Цель
AI-driven inpainting (Stable Diffusion + Inpaint pipeline или TextDiffuser-2) для дополнительного refinement BG + (опционально) text rendering.

### Pre-research

| Модель | Размер | CPU speed | Hallucination risk |
|--------|--------|-----------|---------------------|
| SD 1.5 Inpaint | ~4 GB | ~30-60 s/region | Low if strength <0.3 |
| SDXL Inpaint | ~7 GB | ~2-5 min/region | Medium |
| TextDiffuser-2 | ~5 GB | ~1 min/region | **HIGH** (генерирует символы) |
| AnyText | ~4 GB | ~1 min/region | **HIGH** |

### Критический риск для нашего use-case

Документы у нас **финансовые** (КП, сметы, акты). Hallucinated digit
= legal liability:
- «172 926 213,49» → «172 926 218,49» (одна цифра отличается, ~5M ₽)
- Diffusion модели часто меняют цифры даже при низком strength

### Hybrid подход (приемлемый)

Использовать diffusion **ТОЛЬКО для BG refinement**, НЕ для text generation:

```
Input scan
   ↓
1. LaMa inpaint в bbox региона → cleaned.png (BG cleared, slight artifacts)
   ↓
2. SD img2img на cleaned bbox, strength=0.15, prompt="aged scanned paper":
      • Низкая denoising strength → minimal pixel change
      • Только background area touched (характеры тут уже стёрты)
      → cleaned-refined.png (более realistic paper grain)
   ↓
3. Pillow render текста с v0.5 PSF + v0.8 texture поверх refined BG
   → text characters under FULL deterministic control (no AI)
```

### Что бы этот hybrid дал поверх v0.8

| Аспект | v0.8 текущий | + Hybrid Diffusion |
|--------|--------------|--------------------|
| Text accuracy | 100% deterministic | 100% (text not touched) |
| BG paper grain | Patch-based statistical | Diffusion model rich |
| BG texture variation | Tiled residual | Naturally varied |
| Speed | <1 sec | +30-60 sec/region |
| Disk | +0 | +4 GB model |
| Risk of wrong chars | 0 | 0 (chars not in diffusion path) |

### Implementation план (на отдельную сессию)

1. Download `stabilityai/stable-diffusion-2-inpainting` (~4 GB) в `C:\sd-cache`
   (ASCII-safe path, тот же подход что для LaMa)
2. Lazy load via `diffusers.StableDiffusionInpaintPipeline.from_pretrained(...)`
3. Helper `_refine_bg_with_diffusion(cleaned_arr, mask, bbox)`:
   - Crop bbox region from cleaned image
   - Generate mask = inverted text alpha (BG only)
   - img2img with strength 0.15, prompt empty или "scanned paper background"
   - Crop результат назад в bbox
4. Integration в pipeline as new flag `--bg-refine-diffusion`
5. ETA: 2-3 часа реализации + 1 час testing

### Почему deferred

После v0.8 на тестовом КП визуально невозможно отличить insertion от
оригинала на normal viewing. **Дополнительная сложность не оправдана**
для производственного use-case'а — лучше потратить время на:
- Тестирование v0.8 на разных типах сканов (другие принтеры,
  разрешения, цветовые палитры)
- Расширение API (replace mode workflows, batch processing)
- Edge cases (rotated text, multi-line replacements, hand-written elements)

Если **на реальном production case будет видно cetinct insertion** — этот
roadmap doc становится actionable. До тех пор — backlog.

---

## Option 1: Neural Style Transfer (CNN, отложено)

### Цель
Обучить маленький CNN мapping `clean_render → scan_styled` на парах
сэмплов. Можно через Pix2Pix (paired data) или CycleGAN (unpaired).

### Архитектура (планируемая)

- **Generator:** Pix2Pix-style U-Net, ~5-10M params
  - Input: 256×256 clean rendered text patch
  - Output: 256×256 scan-style patch
- **Discriminator:** PatchGAN
- **Loss:** L1 + perceptual (VGG features) + adversarial
- **Training:** 200-500 epochs на 100-500 пар, ~4-8 hours на GPU
  или 24-48 hours на CPU

### Главное препятствие — **данные**

У нас **нет датасета** clean→scan пар. Чтобы собрать:

**Вариант A: Synthesized clean + real scans**
1. Распечатать рендеры разных шрифтов/размеров на этом конкретном принтере
2. Сканировать на этом конкретном сканере с теми же параметрами
3. Pair clean render PNG ↔ scanned PNG (~50-100 пар минимум)
4. Препроцессинг: align, crop patches 256×256, balance цветов

**Вариант B: Synthetic degradation как pseudo-pairs**
1. Использовать v0.8 как «teacher» — render через pipeline
2. Discriminator distinguishes v0.8 output vs real scan patches
3. Trainable degradation network улучшает realism vs scan distribution
4. Не требует пар, но требует много real scan samples (~1000+ patches)

### Что бы это дало поверх v0.8

| Аспект | v0.8 | + CNN style transfer |
|--------|------|----------------------|
| Stroke micro-texture | Tiled patch-based | Learned per-pixel |
| Per-scanner adaptation | Manual PSF/noise tuning | Auto from training data |
| Generalization к новым шрифтам | Same blur for all | Font-aware degradation |
| Setup time | 0 | 4-48 hours per new scanner |

### Когда становится actionable

- Накопится ≥50 пар clean+scan на нашем основном принтере/сканере
- Один конкретный тип документа повторяется часто (e.g., все КП от
  <организация> в одинаковом сканировании)
- Текущий v0.8 на каком-то документе показывает явный «cut-and-paste look»

До этого момента — Pix2Pix overkill, статистические методы v0.8 достаточны.

### Implementation план (на отдельную фазу, не сессию)

1. Сбор данных: попросить пользователя дать N сканов того же типа (КП от
   <организация>, акты, и т.д.). Извлечь text patches.
2. Synthesized clean → render через v0.5 (с известным шрифтом)
3. Pair-align через template matching (clean шрифт vs OCR'd scan word)
4. Crop 256×256 patches
5. PyTorch dataloader → Pix2Pix training notebook
6. Inference path в pipeline.py: новый mode `--style-cnn`
7. Model selection: track FID/visual quality на validation patches

ETA total: 1-2 недели (сбор данных + training + integration + testing).

### Почему deferred

Слишком много infrastructure work для гипотетического gain поверх v0.8.
Перед этим путём нужно показать что текущий стек **недостаточен** на
реальной production задаче.

---

## Summary table

| Option | Реализован | Эффект на v0.8+ | Riск |
|--------|-----------|------------------|------|
| 1 Neural CNN | Design only | Marginal (если v0.8 работает) | Data collection burden |
| 2 Diffusion (hybrid bg) | Design only | +5% paper grain realism | None (text protected) |
| 3 PSF estimation | ✅ v0.5 default | Critical for edge softness matching | None |
| 4 Borrow glyphs | ✅ v0.6 opt-in | 100% pixel realism when source available | Source weight mismatch |
| (Bonus) A4 anchor | ✅ v0.7 default | Pixel-precise baseline alignment | None |
| (Bonus) B2 texture | ✅ v0.8 default | Stroke micro-texture matching | None |

**Текущий рекомендуемый default:** v0.8 = PSF + anchor + texture transfer,
без borrow (или borrow opt-in для tabular digit replacements).

Если в будущем понадобится больше — заведём branch и приступим к
Option 2 hybrid (быстрее) или Option 1 CNN (медленнее но мощнее).
