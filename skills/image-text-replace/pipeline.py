#!/usr/bin/env python
"""
image-text-replace pipeline v0.2.

Заменяет указанный текст на растровом изображении (скан, JPEG, PNG):
1. OCR через EasyOCR (RU+EN) -> текст + bbox координаты
2. Фильтр по запросу пользователя (literal / regex)
3. Mask из bbox с расширением (dilate)
4. Inpaint: IOPaint LaMa (default) либо cv2.inpaint TELEA (fast mode)
5. Render нового текста через Pillow в том же месте
6. Сохранение result рядом с оригиналом

v0.2 changelog:
- Switch OCR engine PaddleOCR -> EasyOCR. Причина: paddleocr 3.x
  тянет модели с baidu CDN, на корп-сети не работает.
- PIL-loaded image для обхода cv2.imread ANSI-path issue (папки с
  кириллицей в пути).
- Singleton OCR reader (cache) для batch-обработки.
- Helper `find_value_near_label()` для кейса "Метка: значение".
- find/replace теперь поддерживает мульти-OCR-результаты (join
  соседних bbox'ов в одну строку).

CLI usage:
    python pipeline.py --input scan.png \\
        --find "Ф.2024.NNNNNNNNN" \\
        --replace "Ф.2026.MMMMMMMMM" \\
        --font "C:/Windows/Fonts/arial.ttf" \\
        --mode lama

Python lib:
    from pipeline import replace_text_in_image, run_ocr, find_value_near_label
    matches = run_ocr("scan.png")
    label_bbox, value_match = find_value_near_label(matches, r"Итоговая сумма")
    # ... compute new value ...
    replace_text_in_image("scan.png",
        replacements=[(value_match.text, "new value")],
        font_path="C:/Windows/Fonts/arial.ttf")

Зависимости (ставятся через setup-extras.ps1):
    easyocr, iopaint, Pillow, opencv-python, numpy
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence


# ----------------------------------------------------------------------
# Lazy deps installer
# ----------------------------------------------------------------------

_IMPORT_MAP = {
    "easyocr": "easyocr",
    "Pillow": "PIL",
    "opencv-python": "cv2",
    "numpy": "numpy",
    "iopaint": "iopaint",
}


def _ensure_deps(mode: str) -> None:
    required = ["easyocr", "Pillow", "opencv-python", "numpy"]
    if mode == "lama":
        required.append("iopaint")
    missing: list[str] = []
    for pkg in required:
        import_name = _IMPORT_MAP[pkg]
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[ensure-deps] Installing: {missing}", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user", *missing],
            check=True,
        )


# ----------------------------------------------------------------------
# Core types
# ----------------------------------------------------------------------

@dataclass
class OcrMatch:
    """One text region recognized by OCR."""
    text: str
    bbox: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]
    confidence: float

    def bbox_rect(self) -> tuple[int, int, int, int]:
        """Axis-aligned bounding rectangle: (x, y, w, h)."""
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        x, y = min(xs), min(ys)
        return x, y, max(xs) - x, max(ys) - y

    def center_y(self) -> int:
        ys = [p[1] for p in self.bbox]
        return (min(ys) + max(ys)) // 2

    def height_px(self) -> int:
        return self.bbox_rect()[3]


# ----------------------------------------------------------------------
# OCR (EasyOCR with PIL-load workaround)
# ----------------------------------------------------------------------

_READER_CACHE: dict[tuple[str, ...], object] = {}


def _get_reader(langs: Sequence[str]):
    import easyocr
    key = tuple(sorted(langs))
    if key not in _READER_CACHE:
        _READER_CACHE[key] = easyocr.Reader(list(langs), gpu=False, verbose=False)
    return _READER_CACHE[key]


def _load_image_as_array(image_path: str):
    """Read image via Pillow (handles Unicode paths) → numpy RGB array."""
    from PIL import Image
    import numpy as np
    return np.array(Image.open(image_path).convert("RGB"))


def run_ocr(image_path: str, langs: Sequence[str] = ("ru", "en")) -> list[OcrMatch]:
    """Run EasyOCR on image, return list of OcrMatch."""
    reader = _get_reader(langs)
    img = _load_image_as_array(image_path)
    raw = reader.readtext(img)
    matches: list[OcrMatch] = []
    for region in raw:
        bbox_pts, text, conf = region
        bbox_tuple = tuple((int(p[0]), int(p[1])) for p in bbox_pts)
        matches.append(OcrMatch(text=text, bbox=bbox_tuple, confidence=float(conf)))
    return matches


def filter_matches(
    matches: Sequence[OcrMatch],
    find_pattern: str,
    use_regex: bool,
    min_confidence: float = 0.5,
) -> list[OcrMatch]:
    """Pick matches whose text matches user's pattern."""
    if use_regex:
        rx = re.compile(find_pattern)
        return [m for m in matches if rx.search(m.text) and m.confidence >= min_confidence]
    return [m for m in matches if find_pattern in m.text and m.confidence >= min_confidence]


def find_value_near_label(
    matches: Sequence[OcrMatch],
    label_pattern: str,
    side: str = "right",
    row_tolerance_px: int = 20,
    use_regex: bool = True,
) -> Optional[tuple[OcrMatch, OcrMatch]]:
    """For 'Label: value' patterns. Find label match, then the nearest
    OcrMatch on the same row (right side by default).

    Returns (label_match, value_match) or None.
    """
    label_hits = filter_matches(matches, label_pattern, use_regex=use_regex)
    if not label_hits:
        return None
    label_match = max(label_hits, key=lambda m: m.confidence)
    lx, ly, lw, lh = label_match.bbox_rect()
    label_right = lx + lw
    label_left = lx
    label_cy = label_match.center_y()
    candidates = [
        m for m in matches
        if m is not label_match
        and abs(m.center_y() - label_cy) <= row_tolerance_px
    ]
    if side == "right":
        candidates = [m for m in candidates if m.bbox_rect()[0] >= label_right - 10]
        candidates.sort(key=lambda m: m.bbox_rect()[0])
    elif side == "left":
        candidates = [m for m in candidates if (m.bbox_rect()[0] + m.bbox_rect()[2]) <= label_left + 10]
        candidates.sort(key=lambda m: -(m.bbox_rect()[0] + m.bbox_rect()[2]))
    else:
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")
    if not candidates:
        return None
    return label_match, candidates[0]


# ----------------------------------------------------------------------
# Mask building
# ----------------------------------------------------------------------

def build_mask(image_shape: tuple[int, int, ...], matches: Iterable[OcrMatch], dilate_px: int = 4):
    """Binary mask (0/255) covering match bboxes + dilation."""
    import cv2
    import numpy as np

    h, w = image_shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for m in matches:
        pts = np.array(m.bbox, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_px * 2 + 1, dilate_px * 2 + 1))
        mask = cv2.dilate(mask, kernel)
    return mask


# ----------------------------------------------------------------------
# Inpainting backends
# ----------------------------------------------------------------------

def _ascii_safe_cache_dir() -> Path:
    """Return an ASCII-only cache directory for torch/iopaint models.

    Windows + Python + Cyrillic username breaks model loading
    (`~/.cache/torch/...` resolves to garbled bytes for usernames like
    'Даниил'). Use C:\\iopaint-cache as a stable fallback.
    """
    if os.name == "nt":
        candidate = Path(r"C:\iopaint-cache")
    else:
        candidate = Path.home() / ".cache" / "iopaint-pipeline"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def inpaint_lama(image_path: str, mask, output_path: str) -> None:
    """Use IOPaint CLI with LaMa model. Sets TORCH_HOME to ASCII-safe path."""
    from PIL import Image

    cache_root = _ascii_safe_cache_dir()
    env = os.environ.copy()
    env["TORCH_HOME"] = str(cache_root / "torch")
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    env["HF_HOME"] = str(cache_root / "hf")
    (cache_root / "torch").mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        img_dir = Path(td) / "img"
        mask_dir = Path(td) / "mask"
        out_dir = Path(td) / "out"
        img_dir.mkdir()
        mask_dir.mkdir()
        out_dir.mkdir()

        ascii_name = "input.png"
        Image.open(image_path).convert("RGB").save(img_dir / ascii_name)
        Image.fromarray(mask).save(mask_dir / ascii_name)

        cmd = [
            sys.executable, "-m", "iopaint", "run",
            "--model=lama",
            "--device=cpu",
            f"--model-dir={cache_root / 'torch'}",
            f"--image={img_dir}",
            f"--mask={mask_dir}",
            f"--output={out_dir}",
        ]
        print(f"[lama] cache={cache_root}", flush=True)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"iopaint failed (rc={result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        out_files = list(out_dir.glob("input.*"))
        if not out_files:
            raise RuntimeError(f"iopaint produced no output in {out_dir}")
        Image.open(out_files[0]).save(output_path)


def inpaint_fast(image_path: str, mask, output_path: str) -> None:
    """cv2.inpaint with TELEA — fast for uniform backgrounds."""
    import cv2
    from PIL import Image
    import numpy as np
    img = np.array(Image.open(image_path).convert("RGB"))
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    result = cv2.inpaint(bgr, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB)).save(output_path)


# ----------------------------------------------------------------------
# Rendering new text
# ----------------------------------------------------------------------

def _sample_text_color(arr, x: int, y: int, w: int, h: int,
                        percentile: float = 5.0) -> tuple[int, int, int]:
    """Median color of darkest N-percentile pixels in bbox = real stroke cores.

    v1.0: default 5% (raньше 10%). User feedback "светлее оригинала" —
    нужны более тёмные cores. Bottom 5% даёт rgb~(10..15) для типичных
    сканов вместо rgb~(20..25).
    """
    import numpy as np
    region = arr[max(y, 0):y + h, max(x, 0):x + w]
    if region.size == 0:
        return (0, 0, 0)
    gray = np.mean(region, axis=2)
    dark_mask = gray < np.percentile(gray, percentile)
    if not dark_mask.any():
        return (0, 0, 0)
    return tuple(int(c) for c in np.median(region[dark_mask], axis=0))


def _match_histogram_to_reference(
    rendered_rgb,
    rendered_alpha,
    reference_arr,
    ref_x: int,
    ref_y: int,
    ref_w: int,
    ref_h: int,
):
    """Match intensity histogram of stroke pixels in rendered text to reference scan text.

    Diagnostic 2026-05-19 показал что synthesized text слишком однородный:
    mean=54 std=27 (rendered) vs mean=85 std=60 (real scan). Решение —
    histogram matching: CDF intensity всех stroke-pixels рендера mapping'ит
    в CDF reference text pixels.

    rendered_rgb: HxWx3 float32 наш рендер
    rendered_alpha: HxW float32 0..1 (где текст)
    reference_arr: full image array
    ref_x, ref_y, ref_w, ref_h: bbox эталона на скане

    Returns adjusted rgb где stroke pixels следуют CDF реального скана.
    """
    import numpy as np

    ref_patch = reference_arr[max(ref_y, 0):ref_y + ref_h,
                              max(ref_x, 0):ref_x + ref_w].astype(np.float32)
    if ref_patch.size == 0 or rendered_rgb.size == 0:
        return rendered_rgb

    # Reference stroke pixels — только тёмные ядра (bottom 25%, не 50% —
    # иначе захватываются edge anti-alias pixels которые light grey)
    ref_gray = ref_patch.mean(axis=2)
    ref_stroke_mask = ref_gray < np.percentile(ref_gray, 25)
    if not ref_stroke_mask.any():
        return rendered_rgb
    ref_stroke_pixels = ref_patch[ref_stroke_mask]  # Nx3

    # Rendered stroke pixels — где alpha значимая
    rendered_stroke_mask = rendered_alpha > 0.3
    if not rendered_stroke_mask.any():
        return rendered_rgb

    # Match histograms per channel via CDF interpolation
    result = rendered_rgb.copy()
    for c in range(3):
        ref_values = ref_stroke_pixels[:, c]
        rendered_values = rendered_rgb[:, :, c][rendered_stroke_mask]
        ref_sorted = np.sort(ref_values)
        rendered_sorted = np.sort(rendered_values)
        rendered_percentiles = np.searchsorted(rendered_sorted, rendered_values).astype(np.float32)
        rendered_percentiles /= max(len(rendered_sorted) - 1, 1)
        ref_target_indices = (rendered_percentiles * (len(ref_sorted) - 1)).astype(np.int32)
        ref_target_indices = np.clip(ref_target_indices, 0, len(ref_sorted) - 1)
        mapped = ref_sorted[ref_target_indices]
        # Blend strength 0.25 (v1.0) — preserve dark cores intact, only
        # gently push outliers toward ref CDF. v0.9 strength=0.4 ещё видно
        # «прерывистость» — выше strength делает text прозрачнее, не темнее.
        blend_strength = 0.25
        new_values = blend_strength * mapped + (1 - blend_strength) * rendered_values
        result[:, :, c][rendered_stroke_mask] = new_values

    return result


def _extract_texture_residual(arr, x: int, y: int, w: int, h: int):
    """Extract high-frequency texture/noise residual from scan reference area.

    Идея: реальный scan-текст имеет шум внутри штрихов (неравномерный
    тонер, paper texture, scanner CCD). Synthesized text штрихи слишком
    гладкие. Residual = region - heavy_smooth(region) — выделяет именно
    high-freq texture, которую можно наложить на synthesized text для
    matching plausibility.

    Returns HxWx3 float32 residual (mean ≈ 0, captures texture pattern).

    Phase B2 (Patch-based style transfer, 2026-05-19).
    """
    import numpy as np
    import cv2

    region = arr[max(y, 0):y + h, max(x, 0):x + w].astype(np.float32)
    if region.size == 0:
        return None
    smooth = cv2.GaussianBlur(region, (5, 5), 2.0)
    residual = region - smooth
    return residual


def _apply_texture_residual(rendered_rgb, alpha_norm, texture_residual,
                             weight: float = 0.5):
    """Overlay texture residual onto rendered text where alpha is high.

    Tiled if texture smaller than rendered. Weight scales how strongly the
    texture pattern shows up — too high обращается в noise, too low — нет
    эффекта.
    """
    import numpy as np

    if texture_residual is None or texture_residual.size == 0:
        return rendered_rgb

    rh, rw = rendered_rgb.shape[:2]
    th, tw = texture_residual.shape[:2]

    if th < rh or tw < rw:
        tile_h = (rh + th - 1) // th
        tile_w = (rw + tw - 1) // tw
        tiled = np.tile(texture_residual, (tile_h, tile_w, 1))[:rh, :rw]
    else:
        # Use random crop of bigger reference for variety
        max_ty = th - rh
        max_tx = tw - rw
        ty = int(np.random.randint(0, max_ty + 1)) if max_ty > 0 else 0
        tx = int(np.random.randint(0, max_tx + 1)) if max_tx > 0 else 0
        tiled = texture_residual[ty:ty + rh, tx:tx + rw]

    alpha_3d = alpha_norm[:, :, np.newaxis] if alpha_norm.ndim == 2 else alpha_norm
    result = rendered_rgb + tiled * alpha_3d * weight
    return result.clip(0, 255)


def smart_cap_height_detect(arr, x: int, y: int, w: int, h: int,
                              core_ratio: float = 0.3) -> dict:
    """Detect cap height ignoring descenders (commas, parens, dots).

    Row counts as "core stroke" if dark pixels >= core_ratio × bbox_width.
    Top/bottom of core rows = actual cap top/bottom of letters/digits.
    Critical для accurate font_size calculation на text with mixed
    descenders (например '16 877,50' с запятой descender).

    Returns dict {'cap_top', 'cap_bottom', 'cap_height'}.

    v2.2+ pipeline.
    """
    import numpy as np

    region = arr[max(y, 0):y + h, max(x, 0):x + w]
    if region.size == 0:
        return {"cap_top": y, "cap_bottom": y + h, "cap_height": h}
    gray = region.mean(axis=2) if region.ndim == 3 else region
    dark = gray < 150
    core_rows = np.where(dark.sum(axis=1) > w * core_ratio)[0]
    if len(core_rows) == 0:
        return {"cap_top": y, "cap_bottom": y + h, "cap_height": h}
    cap_top = int(core_rows[0]) + y
    cap_bottom = int(core_rows[-1]) + y
    return {"cap_top": cap_top, "cap_bottom": cap_bottom,
            "cap_height": cap_bottom - cap_top + 1}


def unify_font_size_for_batch(
    arr,
    target_matches: Sequence[OcrMatch],
    cap_ratio: float = 0.66,
) -> tuple[int, dict]:
    """For batch text replacement: compute ONE font_size for the whole
    batch via median cap_height — instead of per-cell sizing which gives
    visible size variance.

    Background (LESSONS-LEARNED §6, КП ЛС АХП v7 case 2026-05-20):
    Per-cell font_size, рассчитанный из smart_cap_height_detect на OCR
    bbox каждой ячейки, варьируется на ±1-3px из-за OCR noise → font_size
    колеблется ±1-2pt между строками → визуально цифры разного размера
    в табличном документе где должны быть одного.

    Fix: ОДИН font_size на batch (одна weight-категория). Median
    устойчив к outliers OCR bbox.

    Usage:
        regular_matches = [m for m in target_matches if m.bbox_rect()[1] < 1100]
        bold_matches    = [m for m in target_matches if m.bbox_rect()[1] >= 1100]

        font_size_reg, diag_reg   = unify_font_size_for_batch(arr, regular_matches, cap_ratio=0.66)
        font_size_bold, diag_bold = unify_font_size_for_batch(arr, bold_matches,    cap_ratio=0.70)

        for m in target_matches:
            is_bold = m.bbox_rect()[1] >= 1100
            font_size = font_size_bold if is_bold else font_size_reg
            # ... render ...

    Args:
        arr: image as numpy array
        target_matches: matches whose font_size to unify
        cap_ratio: cap_height / font_size ratio (0.66 ≈ Times Regular,
                   0.70 ≈ Times Bold).

    Returns: (font_size, diagnostic_dict)
        diagnostic_dict = {
            'heights': list[int],   # raw cap_heights per match
            'median': int,
            'mean': float,
            'std': float,
            'n': int,
        }

    Edge cases:
        - Empty matches: returns (24, dict с empty stats).

    v3.1+ pipeline. Import from КП ЛС АХП case 2026-05-20.
    """
    import statistics

    if not target_matches:
        return 24, {"heights": [], "median": 0, "mean": 0.0, "std": 0.0, "n": 0}

    heights = []
    for m in target_matches:
        x, y, w, h = m.bbox_rect()
        result = smart_cap_height_detect(arr, x, y, w, h)
        heights.append(int(result["cap_height"]))

    median_h = int(statistics.median(heights))
    mean_h = float(statistics.mean(heights))
    std_h = float(statistics.stdev(heights)) if len(heights) > 1 else 0.0
    font_size = max(10, int(median_h / cap_ratio))

    return font_size, {
        "heights": heights,
        "median": median_h,
        "mean": mean_h,
        "std": std_h,
        "n": len(heights),
    }


def find_neighbor_cell_reference(
    matches: Sequence[OcrMatch],
    label_match: OcrMatch,
    side: str = "right",
    row_tolerance_px: int = 15,
    digits_only: bool = True,
):
    """Find OCR match of CELL DIGITS на той же строке справа/слева от label.

    Используется для sampling color/PSF/font reference точно по типу
    text который должен match (numeric cells vs bold label = разные стили).
    Без этого можно вставлять bold-style text в место где должен быть
    regular numeric value.

    v1.5+ pipeline.
    """
    import re

    lx, ly, lw, lh = label_match.bbox_rect()
    label_y_center = ly + lh // 2
    label_right_edge = lx + lw
    label_left_edge = lx

    DIGITS_RE = re.compile(r'^[\d\s,.\-]+$')

    candidates = []
    for m in matches:
        if m is label_match:
            continue
        mx, my, mw, mh = m.bbox_rect()
        if abs((my + mh // 2) - label_y_center) > row_tolerance_px:
            continue
        if side == "right" and mx <= label_right_edge:
            continue
        if side == "left" and (mx + mw) >= label_left_edge:
            continue
        if digits_only and not DIGITS_RE.match(m.text.strip()):
            continue
        candidates.append(m)

    if not candidates:
        return None
    # Closest to label horizontally
    if side == "right":
        candidates.sort(key=lambda m: m.bbox_rect()[0])
    else:
        candidates.sort(key=lambda m: -(m.bbox_rect()[0] + m.bbox_rect()[2]))
    return candidates[0]


def compute_midline_paste_y(
    label_anchors: dict,
    cell_anchors: dict,
    text_canvas_height: int,
    text_anchors_in_canvas: dict,
) -> int:
    """Compute paste_y so that rendered text center aligns with cell row midline.

    Combines label and cell midlines (averaged for robustness).
    Used for "по центру ячейки" alignment пользовательский request.

    v1.8+ pipeline.
    """
    cell_midline = (cell_anchors['cap_top'] + cell_anchors['cap_bottom']) // 2
    label_midline = (label_anchors['top_y'] + label_anchors['bottom_y']) // 2
    target_midline = (cell_midline + label_midline) // 2
    text_canvas_midline = (text_anchors_in_canvas['top_y'] +
                            text_anchors_in_canvas['bottom_y']) // 2
    return target_midline - text_canvas_midline


def refine_text_region_with_diffusion(
    rendered_arr,
    crop_bbox: tuple[int, int, int, int],
    sd_cache_dir: str = "C:/sd-cache",
    sd_repo: str = "runwayml/stable-diffusion-inpainting",
    strength: float = 0.10,
    inference_steps: int = 15,
    prompt: str = "scanned document paper, bold serif text, fine paper grain, monochrome",
    negative_prompt: str = "blurry, distorted, illegible, wrong characters",
    guidance_scale: float = 5.0,
):
    """SD img2img на cropped region вокруг inserted text для scan-ification.

    КЛЮЧЕВОЙ финальный pass v3.0. Превращает синтезированный text в
    «visually scanned» через AI-generated paper grain + edge softness.

    Strength 0.10 — ОЧЕНЬ низкий → SD едва меняет content. Text shapes
    preserved (читаемость), но получают scan-style texture.

    !!! RISK !!! Strength > 0.20 может галлюцинировать символы. Для
    финансовых документов держать strength <= 0.15.

    Args:
        rendered_arr: full page HxWx3 uint8 (с уже вставленным text)
        crop_bbox: (x1, y1, x2, y2) — bounding box region для SD pass.
            Should include margin around inserted text + some surrounding
            scan context.
        sd_cache_dir: HF cache directory (ASCII-safe path required)
        sd_repo: HF repo ID. Default runwayml mirror (non-gated).
        strength: 0.05-0.15 безопасно. 0.10 default.
        inference_steps: 15 на CPU = ~1-3 min. Lower = faster, worse.
        prompt: text-conditioning. "scanned document" works для most cases.
        negative_prompt: anti-hallucination.

    Returns:
        modified rendered_arr (in-place) with SD-refined region.

    v3.0 — финальная итерация после 16 шагов на КП <организация> АХП case.
    """
    import numpy as np
    from PIL import Image

    try:
        import torch
        from diffusers import StableDiffusionInpaintPipeline
    except ImportError:
        print("[sd-refine] diffusers not installed, skipping", flush=True)
        return rendered_arr

    x1, y1, x2, y2 = crop_bbox
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(rendered_arr.shape[1], x2)
    y2 = min(rendered_arr.shape[0], y2)
    if (x2 - x1) <= 0 or (y2 - y1) <= 0:
        return rendered_arr

    region = rendered_arr[y1:y2, x1:x2]
    orig_size = (x2 - x1, y2 - y1)

    target_size = 512
    region_pil = Image.fromarray(region)
    region_512 = region_pil.resize((target_size, target_size), Image.LANCZOS)
    # Mask: full white = SD touches everything. Low strength → minimal change.
    mask_512 = Image.new("L", (target_size, target_size), 255)

    print(f"[sd-refine] Loading SD pipeline (cache: {sd_cache_dir})...", flush=True)
    pipe = StableDiffusionInpaintPipeline.from_pretrained(
        sd_repo,
        cache_dir=sd_cache_dir,
        torch_dtype=torch.float32,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.to("cpu")

    print(f"[sd-refine] img2img strength={strength}, steps={inference_steps}...", flush=True)
    result = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        image=region_512,
        mask_image=mask_512,
        strength=strength,
        num_inference_steps=inference_steps,
        guidance_scale=guidance_scale,
    ).images[0]

    refined = np.array(result.resize(orig_size, Image.LANCZOS))
    rendered_arr[y1:y2, x1:x2] = refined
    return rendered_arr


def refine_bg_with_diffusion(
    rendered_arr,
    paste_x: int,
    paste_y: int,
    text_alpha,
    sd_cache_dir: str = "C:/sd-cache",
    strength: float = 0.12,
    prompt: str = "scanned document paper",
    inference_steps: int = 15,
):
    """SD-2-inpaint bg-only refinement (Option 2 hybrid, B3).

    Refines paper texture around inserted text. Character pixels are
    PROTECTED by inverse-alpha inpaint mask — SD diffuses ONLY background.
    Zero risk of hallucinated characters (text shapes unchanged by SD).

    Args:
        rendered_arr: full page image numpy array (HxWx3 uint8)
        paste_x, paste_y: where text alpha was placed in rendered_arr
        text_alpha: HxW float 0..1 — text mask in canvas coords
        sd_cache_dir: HF cache dir (ASCII-safe, e.g. C:/sd-cache)
        strength: 0.10-0.15 minimal change. >0.25 risks visible artifacts.
        prompt: optional context. Empty works too.
        inference_steps: 10-20 на CPU (60-120 sec). Lower = faster, worse.

    Returns:
        refined numpy array (same shape as rendered_arr).

    Requires diffusers + transformers + accelerate + SD-2 model downloaded.
    Falls back to no-op if model unavailable.
    """
    import numpy as np
    from PIL import Image

    try:
        import torch
        from diffusers import StableDiffusionInpaintPipeline
    except ImportError:
        print("[diffusion] diffusers not installed, skipping bg refinement", flush=True)
        return rendered_arr

    # Crop region around text with margin (smaller crop = faster SD)
    canvas_h, canvas_w = text_alpha.shape
    margin = 30
    crop_x1 = max(0, paste_x - margin)
    crop_y1 = max(0, paste_y - margin)
    crop_x2 = min(rendered_arr.shape[1], paste_x + canvas_w + margin)
    crop_y2 = min(rendered_arr.shape[0], paste_y + canvas_h + margin)
    if (crop_x2 - crop_x1) <= 0 or (crop_y2 - crop_y1) <= 0:
        return rendered_arr

    region = rendered_arr[crop_y1:crop_y2, crop_x1:crop_x2].copy()
    # Build inpaint mask in crop coords. 1 = regenerate (BG), 0 = preserve (text).
    crop_h, crop_w = region.shape[:2]
    text_in_crop = np.zeros((crop_h, crop_w), dtype=np.float32)
    text_x_offset = paste_x - crop_x1
    text_y_offset = paste_y - crop_y1
    text_x2 = min(crop_w, text_x_offset + canvas_w)
    text_y2 = min(crop_h, text_y_offset + canvas_h)
    text_in_crop[text_y_offset:text_y2, text_x_offset:text_x2] = text_alpha[
        :text_y2 - text_y_offset, :text_x2 - text_x_offset
    ]
    inpaint_mask = (text_in_crop < 0.3).astype(np.float32)  # 1=BG, 0=text strokes

    # SD requires 8-multiple dims, common 512x512
    target_size = 512
    image_pil = Image.fromarray(region).resize((target_size, target_size), Image.LANCZOS)
    mask_pil = Image.fromarray((inpaint_mask * 255).astype(np.uint8)).resize(
        (target_size, target_size), Image.LANCZOS
    )

    print(f"[diffusion] Loading SD-1.5-inpaint pipeline (cache: {sd_cache_dir})...", flush=True)
    pipe = StableDiffusionInpaintPipeline.from_pretrained(
        "runwayml/stable-diffusion-inpainting",
        cache_dir=sd_cache_dir,
        torch_dtype=torch.float32,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.to("cpu")

    print(f"[diffusion] Inpainting (strength={strength}, steps={inference_steps})...", flush=True)
    result = pipe(
        prompt=prompt,
        image=image_pil,
        mask_image=mask_pil,
        strength=strength,
        num_inference_steps=inference_steps,
        guidance_scale=7.5,
    ).images[0]

    # Resize back to crop size + paste
    refined = np.array(result.resize((crop_w, crop_h), Image.LANCZOS))
    rendered_arr[crop_y1:crop_y2, crop_x1:crop_x2] = refined
    return rendered_arr


def _find_alpha_anchors(alpha_norm, threshold: float = 0.05) -> dict:
    """Find pixel anchors based on alpha channel — для rendered text.

    Использует alpha вместо darkness threshold, потому что у synthesized
    text anti-aliased edges имеют gray=150-200 которые проваливаются
    под darkness threshold, но они визуально являются частью глифа.
    Alpha > 0.05 = любой видимый wisp = реальный visual top/bottom.

    v1.1 fix для "ниже оригинала" жалобы.
    """
    import numpy as np

    if alpha_norm.size == 0 or not (alpha_norm > threshold).any():
        h, w = alpha_norm.shape
        return {"top_y": 0, "bottom_y": h, "left_x": 0, "right_x": w, "baseline_y": h}
    mask = alpha_norm > threshold
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return {
        "top_y": int(rows[0]),
        "bottom_y": int(rows[-1]),
        "left_x": int(cols[0]),
        "right_x": int(cols[-1]),
        "baseline_y": int(rows[-1]),
    }


def _find_pixel_anchors(arr, x: int, y: int, w: int, h: int,
                        darkness_threshold: Optional[float] = None) -> dict:
    """Find precise pixel-based anchors within OCR bbox для positioning.

    OCR bbox имеет padding под antialiasing → top-left bbox ≠ actual top-left
    глифа. Для baseline-precise alignment нужны actual dark-pixel coordinates.

    Returns dict с:
        - 'top_y': topmost row с dark pixels
        - 'bottom_y': bottommost row с dark pixels
        - 'left_x': leftmost col с dark pixels
        - 'right_x': rightmost col с dark pixels
        - 'baseline_y': estimated baseline (≈ bottom_y - small descender offset)

    A4: Pixel-precise anchor detection (2026-05-19).
    """
    import numpy as np

    region = arr[max(y, 0):y + h, max(x, 0):x + w]
    if region.size == 0:
        return {
            "top_y": y, "bottom_y": y + h,
            "left_x": x, "right_x": x + w,
            "baseline_y": y + int(h * 0.85),
        }
    gray = region.mean(axis=2) if region.ndim == 3 else region
    # Threshold: что-то значимо темнее фона
    if darkness_threshold is None:
        darkness_threshold = float(np.percentile(gray, 70)) - 30
        darkness_threshold = max(darkness_threshold, 100)
    dark_mask = gray < darkness_threshold

    if not dark_mask.any():
        # Fallback to bbox edges
        return {
            "top_y": y, "bottom_y": y + h,
            "left_x": x, "right_x": x + w,
            "baseline_y": y + int(h * 0.85),
        }

    rows_with_dark = np.where(dark_mask.any(axis=1))[0]
    cols_with_dark = np.where(dark_mask.any(axis=0))[0]
    top_local = int(rows_with_dark[0])
    bottom_local = int(rows_with_dark[-1])
    left_local = int(cols_with_dark[0])
    right_local = int(cols_with_dark[-1])

    # baseline ≈ bottom of x-height letters, обычно ~95% от глифа высоты
    # для строк без descenders. С descenders — bottom уже = baseline + descender.
    baseline_local = bottom_local  # для строки с descenders это близко к baseline
    return {
        "top_y": y + top_local,
        "bottom_y": y + bottom_local,
        "left_x": x + left_local,
        "right_x": x + right_local,
        "baseline_y": y + baseline_local,
    }


def _extract_char_glyph(arr, match: OcrMatch, char_index: int):
    """Extract pixel patch for a single character within an OCR'd word.

    Uses uniform-width assumption (bbox_width / len(text)). Точнее всего
    для tabular digits в одинаковом шрифте, менее точно для proportional
    шрифтов. Returns (patch_rgb_arr, patch_bbox_in_original) or (None, None).

    Option 4 (borrow glyphs) из roadmap 2026-05-19.
    """
    text = match.text
    if not text or char_index < 0 or char_index >= len(text):
        return None, None
    x, y, w, h = match.bbox_rect()
    char_w = w / len(text)
    px1 = int(x + char_index * char_w)
    px2 = int(x + (char_index + 1) * char_w)
    pad = max(1, int(char_w * 0.12))
    px1 = max(0, px1 - pad)
    px2 = min(arr.shape[1], px2 + pad)
    py1 = max(0, y - 1)
    py2 = min(arr.shape[0], y + h + 1)
    patch = arr[py1:py2, px1:px2].copy()
    return patch, (px1, py1, px2 - px1, py2 - py1)


def _find_char_in_scan(
    target_char: str,
    all_matches: Sequence[OcrMatch],
    min_confidence: float = 0.7,
    prefer_height: Optional[int] = None,
):
    """Search OCR matches for one containing target_char.

    `prefer_height` (если задана) — выбирать match с bbox-height ближе к этому
    значению (для веса matching: bold ≈ taller). Иначе — самый confident.

    Returns (ocr_match, char_position_in_word_text) or None.
    """
    candidates = []
    for m in all_matches:
        if m.confidence < min_confidence:
            continue
        if target_char in m.text:
            candidates.append((m, m.text.index(target_char)))
    if not candidates:
        return None
    if prefer_height is not None:
        candidates.sort(key=lambda c: (abs(c[0].height_px() - prefer_height), -c[0].confidence))
    else:
        candidates.sort(key=lambda c: -c[0].confidence)
    return candidates[0]


def try_borrow_text_from_scan(
    target_text: str,
    all_matches: Sequence[OcrMatch],
    arr,
    target_height: int,
    min_borrow_ratio: float = 0.5,
) -> Optional[dict]:
    """Try to compose target_text by borrowing glyph patches from elsewhere
    in the same scan.

    Workflow:
    1. Для каждого char в target_text — `_find_char_in_scan()` с предпочтением
       к target_height (matching weight).
    2. Если найдено: `_extract_char_glyph()` дает pixel patch.
    3. Сборка patches в одну композицию с baseline alignment.
    4. Если borrowed < min_borrow_ratio × len(target_text) — return None,
       caller использует синтезированный рендер.

    Returns dict {
        'composed_rgb': HxWx3 array,
        'composed_alpha': HxW float 0..1,
        'text_offset': (offset_x, offset_y),  # для caller paste calculation
        'borrowed_chars': list[bool],         # какие позиции были borrowed
        'borrow_ratio': float
    } or None if insufficient borrowing possible.

    Option 4 (borrow glyphs). Лучше всего работает когда scan содержит
    repeat'ы тех же символов (tabular numbers, статичные labels). Для
    one-off bold вставок может вернуть None и caller fallback'нется на
    PSF-aware synthesized рендер.
    """
    import numpy as np

    # Step 1: try to find each char in scan
    char_sources: list[tuple] = []  # (char, patch, bbox, was_borrowed)
    borrowed_count = 0
    for ch in target_text:
        if ch.isspace():
            char_sources.append((ch, None, None, False))
            continue
        result = _find_char_in_scan(ch, all_matches, prefer_height=target_height)
        if result is None:
            char_sources.append((ch, None, None, False))
            continue
        match, pos = result
        patch, bbox = _extract_char_glyph(arr, match, pos)
        if patch is None:
            char_sources.append((ch, None, None, False))
            continue
        char_sources.append((ch, patch, bbox, True))
        borrowed_count += 1

    non_space_count = sum(1 for ch in target_text if not ch.isspace())
    if non_space_count == 0:
        return None
    borrow_ratio = borrowed_count / non_space_count
    if borrow_ratio < min_borrow_ratio:
        return None

    # Step 2: scale all borrowed patches to target_height and assemble
    composed_chars = []
    for ch, patch, bbox, was_borrowed in char_sources:
        if was_borrowed:
            from PIL import Image
            pil = Image.fromarray(patch).convert("RGBA")
            ratio = target_height / pil.height
            new_w = max(1, int(pil.width * ratio))
            scaled = pil.resize((new_w, target_height), Image.LANCZOS)
            # Convert to RGBA via alpha = 1 - (gray/255) — text is darker than bg
            arr_p = np.array(scaled).astype(np.float32)
            if arr_p.shape[2] == 4:
                arr_p = arr_p[:, :, :3]
            gray = arr_p.mean(axis=2)
            # text alpha = how dark pixel is, relative to bright background
            bg_estimate = float(np.percentile(gray, 90))
            alpha = (1 - gray / max(bg_estimate, 1)).clip(0, 1)
            composed_chars.append((ch, arr_p, alpha))
        else:
            # Spacer or unborrowed — caller will handle these via synthesized fallback
            # For simplicity, insert empty gap of ~half target_height for unborrowed
            gap_w = target_height // 3 if ch.isspace() else 0
            composed_chars.append((ch, None, gap_w))

    # If any unborrowed non-space char, signal caller to fall back (current
    # scope: only when ALL non-space chars borrowed)
    has_unborrowed_text = any(
        ch is not None and not ch[0].isspace() and ch[1] is None
        for ch in composed_chars
    )
    if has_unborrowed_text:
        # v1: только полная сборка из borrowed (для proof-of-concept)
        # v2 (future): mix borrowed + synthesized для отдельных букв
        return None

    # Step 3: concatenate horizontally
    total_w = sum(
        (entry[1].shape[1] if entry[1] is not None else entry[2])
        for entry in composed_chars
    )
    composed_rgb = np.full((target_height, total_w, 3), 255, dtype=np.float32)
    composed_alpha = np.zeros((target_height, total_w), dtype=np.float32)
    cursor = 0
    for ch, patch_rgb, patch_alpha in composed_chars:
        if patch_rgb is None:
            # Whitespace gap
            cursor += patch_alpha  # using last field as gap width
            continue
        w_p = patch_rgb.shape[1]
        composed_rgb[:, cursor:cursor + w_p] = patch_rgb
        composed_alpha[:, cursor:cursor + w_p] = patch_alpha
        cursor += w_p

    return {
        "composed_rgb": composed_rgb,
        "composed_alpha": composed_alpha,
        "text_offset": (0, 0),  # composed без padding
        "borrowed_chars": [src[3] for src in char_sources],
        "borrow_ratio": borrow_ratio,
    }


def _estimate_psf_sigma(arr, x: int, y: int, w: int, h: int) -> tuple[float, float]:
    """Estimate anisotropic Gaussian PSF (sigma_x, sigma_y) from text edges
    in the scan region.

    Идея: на сканированном тексте границы букв не идеальные ступеньки,
    а плавные переходы (бумага + тонер + scanner CCD blur). Ширина этого
    перехода = PSF sigma скана. Если рендерить новый текст с тем же
    sigma — он будет неотличим по «мягкости краёв».

    Метод:
    1. Sobel-вычисление сильных edges в bbox региона
    2. Sampling 5-pixel profile перпендикулярно edge
    3. Width of 80%→20% intensity transition ≈ 1.68 × sigma
    4. Median по сэмплам = robust PSF estimate

    Returns (sigma_x, sigma_y). Fallback (0.35, 0.35) если edges не найдены.

    Option 3 (PSF estimation) из roadmap 2026-05-19.
    """
    import cv2
    import numpy as np

    region = arr[max(y, 0):y + h, max(x, 0):x + w].astype(np.float32)
    if region.size == 0:
        return (0.35, 0.35)
    gray = region.mean(axis=2) if region.ndim == 3 else region

    # Vertical edges (Sobel x) → measure sigma_x
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    abs_sx = np.abs(sobel_x)
    thr_x = np.percentile(abs_sx, 90)
    sx_widths = []
    for ey in range(2, gray.shape[0] - 2):
        row_sobel = abs_sx[ey]
        if row_sobel.max() < thr_x:
            continue
        ex = int(np.argmax(row_sobel))
        if ex < 3 or ex > gray.shape[1] - 3:
            continue
        profile = gray[ey, ex - 2:ex + 3]
        if profile.max() - profile.min() < 30:
            continue
        # Normalize so profile goes from 1 (bright) to 0 (dark)
        norm = (profile - profile.min()) / (profile.max() - profile.min() + 1e-6)
        if profile[0] < profile[-1]:
            norm = 1.0 - norm
        try:
            idx80 = next(i for i, v in enumerate(norm) if v < 0.8)
            idx20 = next(i for i, v in enumerate(norm) if v < 0.2)
            width = max(0, idx20 - idx80)
            if 0 < width < 5:
                sx_widths.append(width / 1.68)
        except StopIteration:
            pass

    # Horizontal edges (Sobel y) → measure sigma_y
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    abs_sy = np.abs(sobel_y)
    thr_y = np.percentile(abs_sy, 90)
    sy_widths = []
    for ex in range(2, gray.shape[1] - 2):
        col_sobel = abs_sy[:, ex]
        if col_sobel.max() < thr_y:
            continue
        ey = int(np.argmax(col_sobel))
        if ey < 3 or ey > gray.shape[0] - 3:
            continue
        profile = gray[ey - 2:ey + 3, ex]
        if profile.max() - profile.min() < 30:
            continue
        norm = (profile - profile.min()) / (profile.max() - profile.min() + 1e-6)
        if profile[0] < profile[-1]:
            norm = 1.0 - norm
        try:
            idx80 = next(i for i, v in enumerate(norm) if v < 0.8)
            idx20 = next(i for i, v in enumerate(norm) if v < 0.2)
            width = max(0, idx20 - idx80)
            if 0 < width < 5:
                sy_widths.append(width / 1.68)
        except StopIteration:
            pass

    sigma_x = float(np.median(sx_widths)) if sx_widths else 0.35
    sigma_y = float(np.median(sy_widths)) if sy_widths else 0.35
    # Clip to reasonable range — too low gives no blur, too high blurs everything
    sigma_x = max(0.15, min(sigma_x, 1.5))
    sigma_y = max(0.15, min(sigma_y, 1.5))
    return (sigma_x, sigma_y)


def _sample_bg_noise_std(arr, x: int, y: int, w: int, h: int) -> float:
    """Estimate noise std of paper background near bbox. Fallback 5.0."""
    import numpy as np
    samples = []
    yy1, yy2 = max(0, y - h - 6), max(0, y - 3)
    if yy2 > yy1:
        samples.append(arr[yy1:yy2, x:x + w])
    xx1, xx2 = max(0, x - 40), max(0, x - 8)
    if xx2 > xx1:
        samples.append(arr[y:y + h, xx1:xx2])
    stds = []
    for s in samples:
        if s.size == 0:
            continue
        sf = s.astype(np.float32)
        g = sf.mean(axis=2)
        bg_mask = g > np.percentile(g, 70)
        if bg_mask.any():
            stds.append(float(sf[bg_mask].std()))
    return float(sum(stds) / len(stds)) if stds else 5.0


def _render_scan_realistic(
    font: "ImageFont.FreeTypeFont",
    font_size: int,
    text: str,
    text_color: tuple[int, int, int],
    noise_std: float,
    psf_sigma: tuple[float, float] = (0.35, 0.35),
    rng_seed: int = 11,
):
    """Render text at 2× scale → degrade to scan-style → return (rgb, alpha, text_offset).

    Returns:
        rgb (HxWx3 float32): rendered text RGB
        alpha_norm (HxW float32): alpha 0..1
        text_offset (tuple[int, int]): (offset_x, offset_y) от top-left
            возвращаемого canvas до top-left глифа текста. Caller должен
            считать paste_x = x - offset_x, paste_y = y - offset_y чтобы
            глиф приземлился в (x, y) на destination.

    Stack v0.4 (после фикса bug "съехало вверх, не жирный"):
    1. `anchor="lt"` для предсказуемого положения текста в canvas
    2. Render at 2× scale (без per-char jitter — он жрал жирность)
    3. 2× → 1× LANCZOS downsample → natural AA
    4. **Skipped motion blur** — в v0.3 [0.25,0.5,0.25] kernel
       размазывал bold штрихи → текст становился тоньше оригинала
    5. Мини Gaussian 0.25 px — лёгкое смягчение краёв
    6. Contrast × 1.05 (boost, не reduce) — компенсация LANCZOS-усреднения
    7. Edge noise на alpha 0.05..0.85 × bg_noise × 0.8

    Bug history v0.1→v0.4:
    - v0.1 crisp digital → "слишком цифровой"
    - v0.2 multi-pass + alpha jitter → "плотность падала, серый"
    - v0.3 motion blur + per-char jitter + contrast×0.95 → "съехал вверх,
      не жирный"
    - v0.4 (это): anchor="lt" для positioning + skip motion blur + skip
      per-char jitter + contrast×1.05 — preserve bold weight + точное
      положение.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import numpy as np
    import cv2

    font_2x = ImageFont.truetype(font.path, font_size * 2)
    # Measure bbox с anchor="lt" — top-left глифа в (0,0)
    m_img = Image.new("RGBA", (1, 1))
    m_draw = ImageDraw.Draw(m_img)
    m_bbox = m_draw.textbbox((0, 0), text, font=font_2x, anchor="lt")
    text_w_2x = m_bbox[2] - m_bbox[0]
    text_h_2x = m_bbox[3] - m_bbox[1]
    # Pad for blur margins + descender room
    pad_2x = 20
    canvas_w_2x = text_w_2x + 2 * pad_2x
    canvas_h_2x = text_h_2x + 2 * pad_2x

    canvas = Image.new("RGBA", (canvas_w_2x, canvas_h_2x), (0, 0, 0, 0))
    draw_c = ImageDraw.Draw(canvas)
    # Draw at (pad_2x, pad_2x) с anchor="lt" → текст top-left ровно в
    # (pad_2x, pad_2x). Без per-char jitter — экономим weight.
    draw_c.text((pad_2x, pad_2x), text, font=font_2x,
                fill=text_color + (255,), anchor="lt")

    # 2× → 1× LANCZOS downsample (natural AA)
    canvas_1x = canvas.resize((canvas_w_2x // 2, canvas_h_2x // 2), Image.LANCZOS)

    # v0.5 (Option 3 — PSF): анизотропный Gaussian blur с sigma'ми оценёнными
    # из реальных edges скана (`_estimate_psf_sigma`). Если PSF (0.35, 0.35)
    # default — это умеренный isotropic blur ~ v0.4 behavior.
    arr_text = np.array(canvas_1x).astype(np.float32)
    sigma_x, sigma_y = psf_sigma
    # cv2.GaussianBlur with separate ksize per axis = anisotropic
    # ksize must be odd; auto-compute from sigma
    def _ksize(sig):
        k = int(round(sig * 6)) | 1  # odd, ~6 sigma coverage
        return max(3, k)
    kx, ky = _ksize(sigma_x), _ksize(sigma_y)
    for c in range(4):
        arr_text[:, :, c] = cv2.GaussianBlur(
            arr_text[:, :, c],
            ksize=(kx, ky),
            sigmaX=sigma_x,
            sigmaY=sigma_y,
        )
    rgb = arr_text[:, :, :3]
    alpha_norm = arr_text[:, :, 3] / 255.0

    # Contrast BOOST (не reduce) — компенсация LANCZOS-усреднения которое
    # делает bold штрихи светлее. ×1.05 возвращает их к исходной плотности.
    rgb = ((rgb - 128) * 1.05 + 128).clip(0, 255)

    # Text offset within 1x canvas — это куда попал top-left глифа
    text_offset = (pad_2x // 2, pad_2x // 2)
    return rgb, alpha_norm, text_offset


def render_text(
    cleaned_path: str,
    original_path: str,
    matches: Sequence[OcrMatch],
    replacements: Sequence[tuple[str, str]],
    font_path: str,
    font_size: Optional[int],
    color: Optional[tuple[int, int, int]],
    output_path: str,
    scan_realistic_degrade: bool = True,
    prefer_borrow: bool = False,
    all_ocr_matches: Optional[Sequence[OcrMatch]] = None,
    apply_texture_transfer: bool = True,
    texture_weight: float = 0.5,
) -> None:
    """Draw `replacements` text onto the inpainted image at original bbox positions.

    Color auto-sampling reads dark pixels from `original_path` (pre-inpaint).

    `scan_realistic_degrade=True` (default v0.3+): применяет
    scan-style degradation чтобы текст не выглядел цифровой накладкой.
    Стек — см. _render_scan_realistic().

    `scan_realistic_degrade=False`: crisp digital render (v0.2 поведение,
    оставлен для отладки/case'ов где скан не нужен).
    """
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    img = Image.open(cleaned_path).convert("RGB")
    arr = np.array(img)
    original_arr = np.array(Image.open(original_path).convert("RGB"))

    for m in matches:
        new_text = None
        for find, repl in replacements:
            if find in m.text:
                new_text = m.text.replace(find, repl)
                break
        if new_text is None:
            continue

        x, y, w, h = m.bbox_rect()
        size = font_size or max(8, int(h * 0.85))
        font = ImageFont.truetype(font_path, size)

        text_color = color if color is not None else _sample_text_color(original_arr, x, y, w, h)

        if not scan_realistic_degrade:
            # Crisp digital render (v0.2 behavior)
            draw = ImageDraw.Draw(img)
            draw.text((x, y), new_text, font=font, fill=text_color)
            arr = np.array(img)
            continue

        # v0.6: PSF + optional glyph borrowing (Options 3+4)
        noise_std = _sample_bg_noise_std(original_arr, x, y, w, h)
        psf_sigma = _estimate_psf_sigma(original_arr, x, y, w, h)

        # Option 4 attempt — only if user enabled prefer_borrow AND OCR-matches passed
        borrowed = None
        if prefer_borrow and all_ocr_matches is not None:
            borrowed = try_borrow_text_from_scan(
                new_text, all_ocr_matches, original_arr, target_height=h
            )

        if borrowed is not None:
            print(f"      → Used borrowed glyphs (ratio={borrowed['borrow_ratio']:.2f})", flush=True)
            rgb_text = borrowed["composed_rgb"]
            alpha_text = borrowed["composed_alpha"]
            text_offset = borrowed["text_offset"]
        else:
            rgb_text, alpha_text, text_offset = _render_scan_realistic(
                font, size, new_text, text_color, noise_std,
                psf_sigma=psf_sigma,
                rng_seed=hash(new_text) & 0xFFFF,
            )
            # B2: apply texture residual from reference scan area
            if apply_texture_transfer:
                texture = _extract_texture_residual(original_arr, x, y, w, h)
                if texture is not None:
                    rgb_text = _apply_texture_residual(
                        rgb_text, alpha_text, texture, weight=texture_weight
                    )

        canvas_h, canvas_w = rgb_text.shape[:2]
        # Text top-left должен приземлиться в (x, y) на destination.
        # Canvas top-left -> destination paste_x/paste_y. Текст внутри
        # canvas сдвинут на text_offset → компенсируем.
        paste_x = x - text_offset[0]
        paste_y = y - text_offset[1]
        dst_y1 = max(0, paste_y); dst_y2 = min(arr.shape[0], paste_y + canvas_h)
        dst_x1 = max(0, paste_x); dst_x2 = min(arr.shape[1], paste_x + canvas_w)
        src_y1 = dst_y1 - paste_y; src_y2 = src_y1 + (dst_y2 - dst_y1)
        src_x1 = dst_x1 - paste_x; src_x2 = src_x1 + (dst_x2 - dst_x1)

        dst_patch = arr[dst_y1:dst_y2, dst_x1:dst_x2].astype(np.float32)
        src_rgb = rgb_text[src_y1:src_y2, src_x1:src_x2]
        src_a = alpha_text[src_y1:src_y2, src_x1:src_x2, np.newaxis]

        blended = src_rgb * src_a + dst_patch * (1 - src_a)

        # Edge noise — alpha in 0.05..0.85 = edge transition pixels
        edge_mask = ((src_a.squeeze() > 0.05) & (src_a.squeeze() < 0.85)).astype(np.float32)[:, :, np.newaxis]
        noise = np.random.normal(0, noise_std * 0.8, blended.shape).astype(np.float32)
        blended = blended + noise * edge_mask

        arr[dst_y1:dst_y2, dst_x1:dst_x2] = np.clip(blended, 0, 255).astype(np.uint8)

    Image.fromarray(arr).save(output_path)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def replace_text_in_image(
    input_path: str,
    replacements: Sequence[tuple[str, str]],
    font_path: str = "C:/Windows/Fonts/arial.ttf",
    mode: str = "lama",
    output_path: Optional[str] = None,
    use_regex: bool = False,
    font_size: Optional[int] = None,
    color: Optional[tuple[int, int, int]] = None,
    dilate_px: int = 4,
    ocr_langs: Sequence[str] = ("ru", "en"),
    min_confidence: float = 0.5,
    dry_run: bool = False,
    preloaded_matches: Optional[Sequence[OcrMatch]] = None,
    scan_realistic_degrade: bool = True,
    prefer_borrow: bool = False,
) -> dict:
    """Main public entry. Returns dict with summary.

    `preloaded_matches` — если уже сделали OCR заранее (например, для
    нескольких find/replace на одном изображении в разных шагах),
    можно передать готовый список и не делать OCR повторно.
    """
    from PIL import Image

    _ensure_deps(mode)

    input_path = str(Path(input_path).resolve())
    if output_path is None:
        p = Path(input_path)
        output_path = str(p.with_name(f"{p.stem}.replaced{p.suffix}"))

    if preloaded_matches is None:
        print(f"[1/5] OCR {input_path}...", flush=True)
        all_matches = run_ocr(input_path, langs=ocr_langs)
        print(f"      -> {len(all_matches)} text regions found", flush=True)
    else:
        all_matches = list(preloaded_matches)
        print(f"[1/5] Using {len(all_matches)} preloaded OCR matches", flush=True)

    selected: list[OcrMatch] = []
    summary_per_find = []
    for find, repl in replacements:
        hits = filter_matches(all_matches, find, use_regex=use_regex, min_confidence=min_confidence)
        summary_per_find.append({
            "find": find,
            "replace": repl,
            "matches": len(hits),
            "details": [{"text": h.text, "conf": round(h.confidence, 3), "bbox": h.bbox_rect()} for h in hits],
        })
        selected.extend(hits)

    if not selected:
        return {
            "status": "no_matches",
            "input": input_path,
            "output": None,
            "summary": summary_per_find,
            "message": "Ни один из find-паттернов не сматчился. Запусти с --dry-run и проверь OCR результаты.",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "input": input_path,
            "output": None,
            "summary": summary_per_find,
            "message": f"Dry run: найдено {len(selected)} регионов. Запустить без --dry-run чтобы применить.",
        }

    print(f"[2/5] Building mask ({len(selected)} regions, dilate={dilate_px}px)...", flush=True)
    pil_img = Image.open(input_path).convert("RGB")
    img_shape = (pil_img.height, pil_img.width, 3)
    mask = build_mask(img_shape, selected, dilate_px=dilate_px)

    cleaned_path = str(Path(output_path).with_name(f"{Path(output_path).stem}.cleaned{Path(output_path).suffix}"))

    if mode == "lama":
        print(f"[3/5] Inpainting with LaMa (CPU, ~5-30 сек)...", flush=True)
        inpaint_lama(input_path, mask, cleaned_path)
    elif mode == "fast":
        print(f"[3/5] Inpainting with cv2 TELEA (fast)...", flush=True)
        inpaint_fast(input_path, mask, cleaned_path)
    else:
        raise ValueError(f"Unknown mode: {mode}. Expected 'lama' or 'fast'.")

    print(f"[4/5] Rendering new text with Pillow (font: {font_path})...", flush=True)
    if not Path(font_path).exists():
        raise FileNotFoundError(f"Font not found: {font_path}")
    render_text(
        cleaned_path=cleaned_path,
        original_path=input_path,
        matches=selected,
        replacements=replacements,
        font_path=font_path,
        font_size=font_size,
        color=color,
        output_path=output_path,
        scan_realistic_degrade=scan_realistic_degrade,
        prefer_borrow=prefer_borrow,
        all_ocr_matches=all_matches,
    )

    print(f"[5/5] Saved: {output_path}", flush=True)
    Path(cleaned_path).unlink(missing_ok=True)

    return {
        "status": "ok",
        "input": input_path,
        "output": output_path,
        "summary": summary_per_find,
        "message": f"Replaced {len(selected)} regions, saved to {output_path}",
    }


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replace text on raster image via OCR + inpaint.")
    p.add_argument("--input", required=True)
    p.add_argument("--find", action="append", required=True, help="Text to find. Can repeat.")
    p.add_argument("--replace", action="append", required=True, help="Replacement. Pairs with --find by position.")
    p.add_argument("--regex", action="store_true")
    # v3.0 lesson: для сканированных финансовых документов (КП, акты)
    # шрифт обычно Times New Roman Bold (серифный bold), не Arial.
    # Калибровка через font-calibration sheet перед запуском обязательна.
    p.add_argument("--font", default="C:/Windows/Fonts/timesbd.ttf")
    p.add_argument("--font-size", type=int, default=None)
    p.add_argument("--color", default=None, help="Hex #RRGGBB or omit for auto")
    p.add_argument("--mode", choices=["lama", "fast"], default="lama")
    p.add_argument("--ocr-lang", default="ru,en")
    p.add_argument("--dilate", type=int, default=4)
    p.add_argument("--output", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--min-conf", type=float, default=0.5)
    p.add_argument("--no-scan-degrade", action="store_true",
                   help="Skip scan-realistic degradation, render crisp digital text (debug)")
    p.add_argument("--prefer-borrow", action="store_true",
                   help="Try to borrow glyphs from scan before falling back to synthesized (Option 4)")
    p.add_argument("--sd-refine", action="store_true",
                   help="v3.0: SD img2img на text region with strength=0.10 для scan-ify (требует SD model в C:/sd-cache)")
    p.add_argument("--sd-strength", type=float, default=0.10,
                   help="SD denoising strength. 0.05-0.15 safe. >0.20 risks hallucinated characters")
    args = p.parse_args()
    if len(args.find) != len(args.replace):
        p.error("--find and --replace must come in pairs")
    return args


def main() -> int:
    args = _parse_args()
    color = None
    if args.color:
        c = args.color.lstrip("#")
        color = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    result = replace_text_in_image(
        input_path=args.input,
        replacements=list(zip(args.find, args.replace)),
        font_path=args.font,
        mode=args.mode,
        output_path=args.output,
        use_regex=args.regex,
        font_size=args.font_size,
        color=color,
        dilate_px=args.dilate,
        ocr_langs=tuple(s.strip() for s in args.ocr_lang.split(",")),
        min_confidence=args.min_conf,
        dry_run=args.dry_run,
        scan_realistic_degrade=not args.no_scan_degrade,
        prefer_borrow=args.prefer_borrow,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] in ("ok", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
