#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multi-view 9-tile multi-scale препроцессинг PDF (приём из ClaudeCAD-методологии).

Зачем: модель не разглядит мелочь (штамп, рамка, размерные подписи) на одном
общем рендере подложки. Нарезаем на: overview (вся страница ~1920px) + 2x2
квадранты (с 10% overlap) + 4 угловых deep-zoom (под штамп/рамку/экспликацию).
Каждый tile читается отдельно через Read tool — глаз модели «приближается».

Бэкенд — pypdfium2 (без poppler/внешних бинарей). Картинки к ezdxf отношения
не имеют — это чистый Python-препроцессинг на нашей стороне.

Использование:
    python pdf_multiview.py <pdf> <out_dir> [page_1based] [overview_px]
Вывод: <out_dir>/{overview,q_TL,q_TR,q_BL,q_BR,c_TL,c_TR,c_BL,c_BR}.png
"""
import sys
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    sys.exit("Нужен pypdfium2: pip install pypdfium2")
from PIL import Image


def render_page(pdf_path: str, page_idx: int, target_px: int) -> Image.Image:
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[page_idx]
    w_pt, h_pt = page.get_size()
    scale = target_px / max(w_pt, h_pt)
    return page.render(scale=scale).to_pil()


def crop(img: Image.Image, l: float, t: float, r: float, b: float) -> Image.Image:
    W, H = img.size
    return img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))


def multiview(pdf_path: str, out_dir: str, page_1based: int = 1, overview_px: int = 1920):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    idx = page_1based - 1

    # overview — вся страница
    ov = render_page(pdf_path, idx, overview_px)
    ov.save(out / "overview.png")

    # детальный рендер для нарезки (крупнее, чтобы tiles были чёткими)
    hi = render_page(pdf_path, idx, overview_px * 2)

    ov_lap = 0.10  # 10% overlap у квадрантов
    quads = {
        "q_TL": (0, 0, 0.5 + ov_lap, 0.5 + ov_lap),
        "q_TR": (0.5 - ov_lap, 0, 1, 0.5 + ov_lap),
        "q_BL": (0, 0.5 - ov_lap, 0.5 + ov_lap, 1),
        "q_BR": (0.5 - ov_lap, 0.5 - ov_lap, 1, 1),
    }
    # угловые deep-zoom (штамп обычно в правом нижнем; рамка/экспликация по углам)
    cs = 0.28  # размер углового окна
    corners = {
        "c_TL": (0, 0, cs, cs),
        "c_TR": (1 - cs, 0, 1, cs),
        "c_BL": (0, 1 - cs, cs, 1),
        "c_BR": (1 - cs, 1 - cs, 1, 1),   # ← штамп/основная надпись
    }
    saved = ["overview.png"]
    for name, box in {**quads, **corners}.items():
        crop(hi, *box).save(out / f"{name}.png")
        saved.append(f"{name}.png")
    return saved


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pdf_path, out_dir = sys.argv[1], sys.argv[2]
    page = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    opx = int(sys.argv[4]) if len(sys.argv) > 4 else 1920
    files = multiview(pdf_path, out_dir, page, opx)
    print("Сохранено:", ", ".join(files))
    print("Совет: c_BR.png — зона штампа/основной надписи; q_* — квадранты с overlap.")
