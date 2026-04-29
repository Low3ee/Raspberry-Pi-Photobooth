from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photobooth.config import LayoutSettings
from photobooth.layouts import create_print_layout


class LayoutTests(unittest.TestCase):
    def test_create_print_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            photos = []
            for index in range(4):
                path = tmp_path / f"photo-{index}.jpg"
                Image.new("RGB", (640, 480), (index * 40, 100, 160)).save(path)
                photos.append(path)

            output = create_print_layout(
                photos,
                tmp_path / "print.jpg",
                LayoutSettings(width_px=600, height_px=900, margin_px=30, gap_px=20),
                "Photo Booth",
            )

            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (600, 900))


if __name__ == "__main__":
    unittest.main()

