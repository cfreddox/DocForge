"""Cached antialiased glossy panel illustration; Tk window alpha gives translucency.

This is a visual approximation of frosted glass, not a compositor backdrop blur.
"""
from __future__ import annotations

from functools import lru_cache
from PIL import Image, ImageDraw, ImageFilter


def _rgb(hex_color: str):
    return tuple(bytes.fromhex(hex_color.strip('#')))


@lru_cache(maxsize=48)
def glass_panel(width: int, height: int, theme: str, accent: str) -> Image.Image:
    """Return a high-quality RGBA background, with rounded corners and highlights."""
    scale = 2
    w, h = width * scale, height * scale
    light = theme == "liquid_light"
    solid = theme == "midnight"
    base = (224, 235, 250) if light else ((14, 23, 39) if solid else (25, 40, 61))
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((2, 2, w - 3, h - 3), radius=35 * scale, fill=255)
    layer = Image.new('RGBA', (w, h), base + (255,))
    d = ImageDraw.Draw(layer, 'RGBA')
    # Long, low-contrast gradients and colored diffuse highlights.
    for y in range(h):
        amt = int(26 * (1 - y / max(1, h)))
        if light:
            c = tuple(min(255, p + amt) for p in base)
        else:
            c = tuple(min(255, p + amt) for p in base)
        d.line((0, y, w, y), fill=c + (255,))
    glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, 'RGBA')
    r, g, b = _rgb(accent)
    gd.ellipse((-w // 3, -h // 2, w * 3 // 5, h), fill=(r, g, b, 60 if light else 52))
    gd.ellipse((w // 2, h // 3, w + w // 4, h + h // 2), fill=(132, 211, 255, 54))
    glow = glow.filter(ImageFilter.GaussianBlur(38 * scale))
    layer = Image.alpha_composite(layer, glow)
    lines = ImageDraw.Draw(layer, 'RGBA')
    stroke = (255, 255, 255, 150 if light else 120)
    lines.rounded_rectangle((3, 3, w - 4, h - 4), 35 * scale, outline=stroke, width=2 * scale)
    # Restrained specular rim; avoid a large distracting arc through the content.
    lines.arc((9 * scale, 8 * scale, 115 * scale, 82 * scale),
              185, 260, fill=(255, 255, 255, 65), width=scale)
    lines.line((46 * scale, 19 * scale, (width - 46) * scale, 19 * scale),
               fill=(255, 255, 255, 50), width=1 * scale)
    layer.putalpha(mask)
    img = Image.alpha_composite(img, layer)
    return img.resize((width, height), Image.Resampling.LANCZOS)
