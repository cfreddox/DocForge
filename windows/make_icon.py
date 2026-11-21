"""Create a local Windows icon without external image downloads."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw


def make_icon(destination: str | Path):
    image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((14, 14, 242, 242), radius=60, fill=(30, 54, 98, 255))
    for points, color in [
        ([(128, 38), (213, 100), (128, 155), (43, 100)], (101, 190, 253, 255)),
        ([(128, 82), (210, 143), (128, 205), (46, 143)], (138, 104, 251, 255)),
        ([(128, 116), (182, 155), (128, 192), (73, 155)], (208, 198, 255, 255)),
    ]:
        draw.polygon(points, fill=color)
    image.save(str(destination), format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])


if __name__ == '__main__':
    make_icon(Path(__file__).resolve().parent / 'docforge.ico')
