from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

from .config import LayoutSettings


def create_print_layout(
    photo_paths: Iterable[Path],
    output_path: Path,
    settings: LayoutSettings,
    title: str,
) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required to create print layouts") from exc

    paths = [Path(path) for path in photo_paths]
    if not paths:
        raise ValueError("At least one photo is required")

    canvas = Image.new("RGB", (settings.width_px, settings.height_px), settings.background)
    draw = ImageDraw.Draw(canvas)

    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 52)
        caption_font = ImageFont.truetype("DejaVuSans.ttf", 28)
    except OSError:
        title_font = ImageFont.load_default()
        caption_font = ImageFont.load_default()

    top_text_height = 92
    bottom_text_height = 88
    grid_top = settings.margin_px + top_text_height
    grid_bottom = settings.height_px - settings.margin_px - bottom_text_height
    grid_height = grid_bottom - grid_top
    grid_width = settings.width_px - (settings.margin_px * 2)

    cols, rows = _grid_for_count(len(paths))
    cell_w = int((grid_width - settings.gap_px * (cols - 1)) / cols)
    cell_h = int((grid_height - settings.gap_px * (rows - 1)) / rows)

    for index, path in enumerate(paths):
        row = index // cols
        col = index % cols
        x = settings.margin_px + col * (cell_w + settings.gap_px)
        y = grid_top + row * (cell_h + settings.gap_px)
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            fitted = _cover(img, (cell_w, cell_h))
            canvas.paste(fitted, (x, y))
        draw.rectangle((x, y, x + cell_w, y + cell_h), outline=settings.accent, width=4)

    _center_text(draw, title, settings.width_px, settings.margin_px, title_font, settings.accent)
    caption = settings.caption.strip()
    if caption:
        _center_text(
            draw,
            caption,
            settings.width_px,
            settings.height_px - settings.margin_px - 62,
            caption_font,
            settings.accent,
        )
    date_text = datetime.now().strftime("%Y-%m-%d")
    _center_text(
        draw,
        date_text,
        settings.width_px,
        settings.height_px - settings.margin_px - 28,
        caption_font,
        settings.accent,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "JPEG", quality=95, dpi=(settings.dpi, settings.dpi))
    return output_path


def _grid_for_count(count: int) -> Tuple[int, int]:
    if count <= 2:
        return 1, count
    cols = 2
    rows = int(math.ceil(count / cols))
    return cols, rows


def _cover(image, size):
    from PIL import ImageOps

    return ImageOps.fit(image, size, method=3, centering=(0.5, 0.5))


def _center_text(draw, text: str, width: int, y: int, font, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    draw.text(((width - text_w) // 2, y), text, font=font, fill=fill)

