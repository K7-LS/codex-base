#!/usr/bin/env python
"""Font calibration sheet — render same text in multiple fonts to
visually pick the one matching a scanned document.

Lesson from КП <организация> АХП case: 8 итераций потрачены на tuning Arial когда
реальный font scan'a был Times Bold. **ALWAYS run calibration first**
для нового типа документа.

CLI:
    python calibration.py \\
        --input scan.png \\
        --bbox 1114,686,96,26 \\
        --text "16 877,50" \\
        --output font-sheet.png

Откройте font-sheet.png — first строка REAL SCAN, далее candidates
с подписями. Выберите визуально matching, передайте font path
в pipeline.py --font.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np


DEFAULT_FONTS = [
    ("Arial Regular", "C:/Windows/Fonts/arial.ttf"),
    ("Arial Bold", "C:/Windows/Fonts/arialbd.ttf"),
    ("Times New Roman", "C:/Windows/Fonts/times.ttf"),
    ("Times Bold", "C:/Windows/Fonts/timesbd.ttf"),
    ("Calibri", "C:/Windows/Fonts/calibri.ttf"),
    ("Calibri Bold", "C:/Windows/Fonts/calibrib.ttf"),
    ("Verdana", "C:/Windows/Fonts/verdana.ttf"),
    ("Tahoma", "C:/Windows/Fonts/tahoma.ttf"),
    ("Georgia", "C:/Windows/Fonts/georgia.ttf"),
    ("Courier New", "C:/Windows/Fonts/cour.ttf"),
    ("Consolas", "C:/Windows/Fonts/consola.ttf"),
    ("Cambria", "C:/Windows/Fonts/cambria.ttc"),
]


def _find_font_size_for_height(font_path: str, target_h: int,
                                test_char: str = "H") -> int:
    """Find font_size such that test_char renders with given cap height."""
    for size in range(8, 80):
        try:
            font = ImageFont.truetype(font_path, size)
        except OSError:
            return 24
        img = Image.new("RGB", (80, 100), "white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), test_char, font=font, fill="black", anchor="lt")
        arr = np.array(img).mean(axis=2)
        dark = arr < 100
        if dark.any():
            rows = np.where(dark.any(axis=1))[0]
            h = rows[-1] - rows[0]
            if h >= target_h:
                return size
    return 24


def render_calibration_sheet(
    input_path: str,
    bbox: tuple[int, int, int, int],
    text: str,
    output_path: str,
    fonts: list[tuple[str, str]] = None,
    target_height: int | None = None,
):
    """Render comparison sheet with real scan + N font variants."""
    if fonts is None:
        fonts = DEFAULT_FONTS

    x, y, w, h = bbox
    scan = Image.open(input_path).convert("RGB")
    real_crop = scan.crop((x, y, x + w, y + h))

    if target_height is None:
        # Estimate cap height from scan (smart detection: row with >30% dark pixels)
        arr = np.array(real_crop).mean(axis=2)
        dark = arr < 150
        core_rows = np.where(dark.sum(axis=1) > w * 0.3)[0]
        target_height = int(core_rows[-1] - core_rows[0]) if len(core_rows) > 0 else h

    print(f"Real scan bbox: ({x},{y},{w},{h}), target cap height: {target_height}px")
    print(f"Available fonts: {len([f for _, f in fonts if Path(f).exists()])}/{len(fonts)}")

    # Layout: real on top row, then N candidate rows
    W = max(300, w + 200)
    H_each = max(40, h + 10)
    combined = Image.new("RGB", (W, H_each * (len(fonts) + 1)), "white")
    combined.paste(real_crop, (0, 0))
    draw = ImageDraw.Draw(combined)
    draw.text((w + 10, 5), "REAL SCAN", fill="red")

    for i, (name, path) in enumerate(fonts):
        row_y = H_each * (i + 1)
        if not Path(path).exists():
            label_draw = ImageDraw.Draw(combined)
            label_draw.text((10, row_y + 5),
                             f"(not installed) {name}", fill=(150, 150, 150))
            continue
        size = _find_font_size_for_height(path, target_height)
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            continue
        img = Image.new("RGB", (w + 5, H_each), "white")
        draw_i = ImageDraw.Draw(img)
        draw_i.text((5, 4), text, font=font, fill=(3, 3, 3), anchor="lt")
        combined.paste(img, (0, row_y))
        label_draw = ImageDraw.Draw(combined)
        label_draw.text((w + 10, row_y + 5), name, fill="red")

    # 2x upscale for easier viewing
    combined_up = combined.resize((combined.width * 2, combined.height * 2), Image.LANCZOS)
    combined_up.save(output_path)
    print(f"Saved: {output_path}")
    return output_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Font calibration sheet for scan matching")
    p.add_argument("--input", required=True, help="Scan PNG file")
    p.add_argument("--bbox", required=True,
                   help="Reference text bbox: x,y,w,h (numeric cell)")
    p.add_argument("--text", required=True,
                   help='Text to render in candidates (e.g. "16 877,50")')
    p.add_argument("--output", default="font-calibration.png",
                   help="Output sheet PNG")
    p.add_argument("--target-height", type=int, default=None,
                   help="Override auto-detected cap height")
    args = p.parse_args()
    args.bbox = tuple(int(v) for v in args.bbox.split(","))
    if len(args.bbox) != 4:
        p.error("--bbox must be x,y,w,h")
    return args


def main() -> int:
    args = _parse_args()
    render_calibration_sheet(
        input_path=args.input,
        bbox=args.bbox,
        text=args.text,
        output_path=args.output,
        target_height=args.target_height,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
