"""Interactive radial file targets and custom-drawn, frameless glass drop zone.

All geometry/target choices are pure functions for reliable unit tests.  Rendering
is an approximation of translucent textured glass; compositors control real blur.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import cos, sin, radians
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .core import common_targets, source_ext

BASE_W, BASE_H = 720, 620
CENTER_SIZE = (234, 224)
PETAL_SIZE = (230, 126)
RADIUS = 190

COLORS = {
    "pdf": "#FF8B2B", "md": "#8B62EB", "docx": "#6181EE",
    "txt": "#37A77A", "png": "#30BAAF", "jpg": "#ED6794",
    "html": "#DF9B3B", "odt": "#6796C8", "epub": "#9861D6",
    "split": "#F0AD3B", "compress": "#6189D0", "merge": "#DA65BA",
    "rotate": "#57B8B3", "edit": "#E9AD4C", "other": "#929DC5",
}

LABELS = {
    "pdf": "В PDF", "md": "В Markdown", "docx": "В DOCX", "txt": "В TXT",
    "png": "В PNG", "jpg": "В JPG", "html": "В HTML",
    "odt": "В ODT", "epub": "В EPUB", "split": "Разделить PDF",
    "compress": "Сжать PDF", "merge": "Объединить PDF", "rotate": "Повернуть PDF", "edit": "Редактировать",
}


@dataclass(frozen=True)
class Action:
    """One radial target; operation is never inferred from a displayed label."""
    key: str
    target: str
    operation: str = "convert"

    @property
    def label(self) -> str:
        return LABELS.get(self.key, "В " + self.key.upper())

    @property
    def color(self) -> str:
        return COLORS.get(self.key, COLORS["other"])


def actions_for(paths: list[Path]) -> list[Action]:
    """Show only supported conversions, plus operations valid for PDF inputs."""
    if not paths:
        return []
    targets = common_targets(paths)
    priority = ["pdf", "docx", "md", "png", "jpg", "txt", "html", "odt", "epub"]
    actions = [Action(fmt, fmt) for fmt in priority if fmt in targets]
    actions += [Action(fmt, fmt) for fmt in targets if fmt not in priority]
    if all(source_ext(p) == "pdf" for p in paths):
        extras = [("edit", "edit"), ("split", "split"), ("compress", "compress"), ("rotate", "rotate")]
        if len(paths) >= 2:
            extras.insert(0, ("merge", "merge"))
        actions.extend(Action(key, key, op) for key, op in extras)
    return actions[:8]


def angles_for(n: int) -> list[float]:
    """Radial layout from the top, clockwise."""
    if n < 1:
        return []
    return [-90.0 + i * 360.0 / n for i in range(n)]


def petal_centers(n: int, width: int, height: int, scale: float = 1.0, progress: float = 1.0):
    radius = RADIUS * scale * (0.33 + 0.67 * max(0, min(1, progress)))
    cx, cy = width / 2, height / 2
    return [(cx + cos(radians(a)) * radius, cy + sin(radians(a)) * radius, a)
            for a in angles_for(n)]


def hit_test(x: float, y: float, n: int, width: int, height: int,
             scale: float = 1.0, magnifications: list[float] | None = None) -> int | None:
    """Find target within a rotated elliptical capsule; center is not a petal."""
    if not n:
        return None
    if abs(x - width / 2) < CENTER_SIZE[0] * scale * .46 and abs(y - height / 2) < CENTER_SIZE[1] * scale * .46:
        return None
    results = []
    for idx, (cx, cy, angle) in enumerate(petal_centers(n, width, height, scale)):
        theta = radians(angle)
        dx, dy = x - cx, y - cy
        along = dx * cos(theta) + dy * sin(theta)
        across = -dx * sin(theta) + dy * cos(theta)
        mag = magnifications[idx] if magnifications else 1.0
        metric = (along / (PETAL_SIZE[0] * scale * mag * .47))**2 + (across / (PETAL_SIZE[1] * scale * mag * .45))**2
        if metric <= 1.0:
            results.append((metric, idx))
    return min(results)[1] if results else None


def spring_step(value: float, velocity: float, target: float, intensity: float = 1.0) -> tuple[float, float]:
    """Damped spring: slightly overshoots the 9% hover magnification, then settles."""
    if intensity <= 0:
        return value + (target-value)*.24, 0.0
    k = 0.24 * max(0.15, min(intensity, 1.6))
    velocity = (velocity + (target - value) * k) * 0.74
    value += velocity
    if abs(target - value) < 0.0003 and abs(velocity) < 0.0003:
        return target, 0.0
    return value, velocity


def _font(size: int, bold: bool = True):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _hex(hexcode):
    return tuple(bytes.fromhex(hexcode.lstrip("#")))


def _shadowed_text(draw, pos, text, font, color, *, anchor="mm"):
    x, y = pos
    draw.text((x, y + 2), text, font=font, fill=(35, 20, 35, 115), anchor=anchor,
              stroke_width=0)
    draw.text((x, y), text, font=font, fill=color, anchor=anchor)


@lru_cache(maxsize=100)
def _petal_sprite(color: str, style: str, width: int = 232, height: int = 126) -> Image.Image:
    pad = 20
    w, h = width + 2*pad, height + 2*pad
    rim = Image.new("L", (w, h))
    d = ImageDraw.Draw(rim)
    d.ellipse((pad, pad, w-pad-1, h-pad-1), fill=255)
    shadow = Image.new("RGBA", (w, h), (0,0,0,0))
    shadow.paste((50, 20, 65, 100), (0, 7, w, h+7), rim.filter(ImageFilter.GaussianBlur(11)))
    fill = Image.new("RGBA", (w, h), (0,0,0,0))
    pix = fill.load()
    r,g,b = _hex(color)
    for y in range(h):
        # Translucent upper highlight and saturated lower contour (no tinted window backdrop).
        ry = (y - pad) / max(1, height)
        opacity = (140 if style == "fuzzy" else 108) if style != "matte" else 215
        for x in range(w):
            if 0 <= ry <= 1:
                light = max(0, int(70*(1-ry)))
                pix[x,y] = (min(255, r+light), min(255, g+light), min(255, b+light), opacity)
    fill.putalpha(Image.composite(fill.getchannel("A"), Image.new("L",(w,h),0), rim))
    shadow = Image.alpha_composite(shadow, fill)
    d = ImageDraw.Draw(shadow, "RGBA")
    d.arc((pad+2,pad+2,w-pad-3,h-pad-3), 180, 360, fill=(255,255,255,230), width=3)
    d.arc((pad+5,pad+5,w-pad-6,h-pad-6), 10, 175, fill=(255,255,255,90), width=2)
    return shadow



@lru_cache(maxsize=168)
def _rotated_petal(color: str, style: str, scale_pct: int, angle: float) -> Image.Image:
    """Pre-rasterize the expensive rotation for smooth motion in Tk."""
    scale = scale_pct / 100
    sw, sh = round(PETAL_SIZE[0] * scale), round(PETAL_SIZE[1] * scale)
    sprite = _petal_sprite(color, style).resize((sw + round(40*scale), sh + round(40*scale)), Image.Resampling.LANCZOS)
    return sprite.rotate(-angle, expand=True, resample=Image.Resampling.BICUBIC)

def _texture_file() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "fiber-orange.webp"


@lru_cache(maxsize=8)
def _fiber_texture(dim: int, style: str, accent: str) -> Image.Image:
    try:
        image = Image.open(_texture_file()).convert("RGB")
        image = ImageOps.fit(image, (dim, dim), method=Image.Resampling.LANCZOS)
    except OSError:
        image = Image.new("RGB", (dim,dim), "#f78931")
    if style == "clear":
        # Neutral clear glass can be chosen from settings; no orange tint.
        return Image.new("RGBA", (dim, dim), (234,238,245,186))
    if style == "matte":
        image = image.filter(ImageFilter.GaussianBlur(8))
    # Keep the original source texture's warm orange color; accent affects rim.
    return image.convert("RGBA")


def _center_sprite(dim: int, style: str, accent: str, *, status: str = "") -> Image.Image:
    pad = 16
    w = dim + pad*2
    img = Image.new("RGBA", (w,w), (0,0,0,0))
    mask = Image.new("L", (dim,dim), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((2,2,dim-3,dim-3), radius=int(dim*.27), fill=255)
    glass = _fiber_texture(dim, style, accent).copy()
    glass.putalpha(Image.composite(glass.getchannel("A"), Image.new("L",(dim,dim),0), mask))
    halo = Image.new("RGBA", (w,w), (0,0,0,0))
    rim_mask = Image.new("L",(w,w),0)
    rd = ImageDraw.Draw(rim_mask)
    rd.rounded_rectangle((pad,pad,w-pad-1,w-pad-1), radius=int(dim*.27), fill=235)
    halo.paste((*_hex(accent), 120), (0,0,w,w), rim_mask.filter(ImageFilter.GaussianBlur(12)))
    img = Image.alpha_composite(img, halo)
    img.alpha_composite(glass,(pad,pad))
    d = ImageDraw.Draw(img,"RGBA")
    d.rounded_rectangle((pad+1,pad+1,w-pad-2,w-pad-2), radius=int(dim*.27),outline=(255,255,255,230),width=4)
    d.arc((pad+6,pad+6,w-pad-7, w-pad-7),190,320,fill=(255,255,255,145),width=3)
    return img



def render_zone(width: int, height: int, *, style: str = "fuzzy", accent: str = "#FF922B",
                actions: tuple[Action, ...] = (), progress: float = 0.0,
                magnifications: tuple[float, ...] = (), selected: int | None = None,
                status: str = "", hint: str | None = None) -> Image.Image:
    """Render RGBA image with no rectangular frame/background.

    The host window may use XShape for pixel-perfect mouse/visual boundaries on X11.
    """
    result = Image.new("RGBA", (width, height), (0,0,0,0))
    scale = min(width / BASE_W, height / BASE_H) if width > 360 else min(width/256, height/240)
    # In expanded geometry scale is pinned to actual overall canvas size.
    if actions and progress > 0.001:
        positions = petal_centers(len(actions), width, height, scale, progress)
        for idx, (px,py,angle) in enumerate(positions):
            mag = magnifications[idx] if idx < len(magnifications) else 1.0
            mag = max(0.97,min(1.19,mag))
            # Make colorful liquid capsules while keeping their labels horizontal.
            sprite = _rotated_petal(actions[idx].color, style,
                                    max(20, round(scale*mag*100)), round(angle, 2)).copy()
            if progress < .99:
                alpha = sprite.getchannel("A").point(lambda v: round(v*progress))
                sprite.putalpha(alpha)
            x0,y0 = round(px-sprite.width/2), round(py-sprite.height/2)
            result.alpha_composite(sprite, (x0,y0))
        # Labels are drawn after the petals but before the center, so overlap looks fluid.
        d = ImageDraw.Draw(result,"RGBA")
        for idx,(px,py,angle) in enumerate(positions):
            if progress < 0.48:
                continue
            action = actions[idx]
            mag = magnifications[idx] if idx < len(magnifications) else 1.0
            sz = max(11, round(15*scale*mag))
            text = action.label
            if len(text) > 11:
                font = _font(max(10, sz-2))
            else:
                font = _font(sz)
            tint = (255,255,255,255)
            # Petal labels always horizontal and visible while the capsule bounces.
            _shadowed_text(d,(px, py-5*scale),text,font,tint)
            if selected == idx:
                d.ellipse((px+55*scale,py-38*scale,px+69*scale,py-24*scale),fill=(255,255,255,230))
    core = round(min(CENTER_SIZE)*scale)
    center = _center_sprite(core,style,accent)
    cx,cy=width//2,height//2
    result.alpha_composite(center,(cx-center.width//2,cy-center.height//2))
    d=ImageDraw.Draw(result,"RGBA")
    # Text contains only brief labels to keep the zone clean, with no title bar/controls.
    core_text = (34, 45, 65, 255) if style == "clear" else (255,255,255,255)
    if status:
        top = status[:48]
        _shadowed_text(d,(cx,cy-6*scale),top,_font(max(11,round(16*scale))), core_text)
    else:
        _shadowed_text(d,(cx,cy-23*scale),"+",_font(max(20,round(43*scale))), core_text)
        label = hint or "Перетащите файл"
        _shadowed_text(d,(cx,cy+22*scale),label,_font(max(11,round(15*scale))), core_text)
        _shadowed_text(d,(cx,cy+45*scale),"сюда",_font(max(11,round(15*scale))), core_text)
    return result
