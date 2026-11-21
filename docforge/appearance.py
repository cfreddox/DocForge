"""Persistent user appearance preferences and primary-monitor geometry."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

DEFAULTS = {
    "theme": "liquid_light",
    "accent": "blue",
    "opacity": 0.78,
    "scale": 1.0,
    "zone_size": "standard",
    "always_on_top": False,
    "zone_style": "clear",
    "refraction": 0.80,
    "hover_scale": 0.09,
    "petal_animation": True,
    "animation_style": "spring",
    "reveal_ms": 450,
    "bounce": 0.35,
}
THEMES = {
    "liquid_dark": "Жидкое стекло · тёмное",
    "liquid_light": "Жидкое стекло · светлое",
    "midnight": "Классическая тёмная",
}
ACCENTS = {
    "blue": ("Синий", "#5C9CFF"),
    "violet": ("Фиолетовый", "#A78BFA"),
    "mint": ("Мятный", "#4ED9B6"),
    "pink": ("Розовый", "#FF87BD"),
    "amber": ("Янтарный", "#FF922B"),
    "orange": ("Оранжевый", "#FA6D17"),
    "cyan": ("Бирюзовый", "#16B8DA"),
    "green": ("Зелёный", "#38BE80"),
}
SIZES = {"compact": (224, 210), "standard": (256, 240), "large": (296, 276)}
ZONE_STYLES = {"clear": "Жидкое прозрачное стекло", "crystal": "Кристальное стекло", "matte": "Матовое стекло"}
ANIMATION_STYLES = {"spring": "Пружинное", "soft": "Мягкое", "liquid": "Жидкое"}


def config_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "docforge" / "settings.json"


def sanitize_settings(value: object) -> dict:
    settings = DEFAULTS.copy()
    if not isinstance(value, dict):
        return settings
    for key in ("theme", "accent", "zone_size", "zone_style", "animation_style"):
        choices = {"theme": THEMES, "accent": ACCENTS, "zone_size": SIZES, "zone_style": ZONE_STYLES, "animation_style": ANIMATION_STYLES}[key]
        raw = value.get(key)
        if isinstance(raw, str) and raw in choices:
            settings[key] = raw
    for key, lower, upper in (("opacity", 0.10, 1.0), ("scale", 0.8, 1.5), ("bounce", 0.0, 1.6), ("refraction", 0.0, 1.0),
                              ("hover_scale", 0.05, 0.16)):
        entry = value.get(key)
        if type(entry) in (float, int) and lower <= entry <= upper:
            settings[key] = float(entry)
    duration = value.get("reveal_ms")
    if type(duration) is int and 250 <= duration <= 800:
        settings["reveal_ms"] = duration
    for toggle in ("always_on_top", "petal_animation"):
        if type(value.get(toggle)) is bool:
            settings[toggle] = value[toggle]
    return settings


SLIDER_SETTINGS = (
    ("Прозрачность стекла", "opacity", 10, 98, 100, "%"),
    ("Преломление по краям", "refraction", 0, 100, 100, "%"),
    ("Раскрытие", "reveal_ms", 250, 800, 1, " мс"),
    ("Увеличение лепестка", "hover_scale", 5, 16, 100, "%"),
    ("Отскок анимации", "bounce", 0, 160, 100, "%"),
)


def setting_from_slider(key: str, raw: int) -> int | float:
    """Map Qt integer slider values to preferences without unit confusion."""
    spec = next((item for item in SLIDER_SETTINGS if item[1] == key), None)
    if spec is None:
        raise KeyError(key)
    _, _, low, high, scale, _ = spec
    value = max(low, min(high, int(raw)))
    return value if key == "reveal_ms" else value / scale


def slider_from_setting(key: str, value: float | int) -> int:
    spec = next((item for item in SLIDER_SETTINGS if item[1] == key), None)
    if spec is None:
        raise KeyError(key)
    _, _, low, high, scale, _ = spec
    return max(low, min(high, round(float(value) * scale)))


def glass_opacity_strength(transparency: float) -> float:
    """Material density: 100% transparency exposes more desktop, not less."""
    normalized = max(.10, min(.98, float(transparency)))
    return 1.35 - .82 * normalized


WINDOW_BEHAVIOR_VERSION = 2
LIQUID_RENDERER_VERSION = 1
ANIMATION_PROFILE_VERSION = 2


def load_settings() -> dict:
    try:
        raw = json.loads(config_file().read_text(encoding="utf-8"))
        settings = sanitize_settings(raw)
        # Old 1.3 used a baked-in orange fabric texture, which was explicitly
        # rejected. Transparently migrate that option to true ARGB glass.
        if isinstance(raw,dict) and raw.get("liquid_renderer_version") != LIQUID_RENDERER_VERSION:
            if raw.get("zone_style") == "fuzzy":
                settings["zone_style"] = "clear"
        # Apply the explicitly requested 1.5 spring motion to existing installs
        # once, without discarding the user's theme, colors or window position.
        if isinstance(raw, dict) and raw.get("animation_profile_version") != ANIMATION_PROFILE_VERSION:
            for key in ("animation_style", "reveal_ms", "bounce", "hover_scale"):
                settings[key] = DEFAULTS[key]
        # Pre-1.2.1 releases defaulted to a permanently-on-top unmanaged window.
        # Migrate only that behavior, preserving all existing visual preferences.
        # Saving from the settings dialog marks an explicit new topmost choice.
        if isinstance(raw, dict) and raw.get("window_behavior_version") != WINDOW_BEHAVIOR_VERSION:
            settings["always_on_top"] = False
        return settings
    except (OSError, ValueError, UnicodeError):
        return DEFAULTS.copy()


def save_settings(value: dict) -> Path:
    path = config_file()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe = sanitize_settings(value)
    # Atomic replacement; do not leave a truncated settings file on failure.
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".settings-", suffix=".tmp", delete=False) as output:
        temp_path = Path(output.name)
        json.dump({**safe, "window_behavior_version": WINDOW_BEHAVIOR_VERSION,
                           "liquid_renderer_version": LIQUID_RENDERER_VERSION,
                           "animation_profile_version": ANIMATION_PROFILE_VERSION},
                  output, ensure_ascii=False, indent=2)
        output.write("\n")
    try:
        os.chmod(temp_path, 0o600)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def palette(settings: dict) -> dict:
    settings = sanitize_settings(settings)
    light = settings["theme"] == "liquid_light"
    solid = settings["theme"] == "midnight"
    accent = ACCENTS[settings["accent"]][1]
    return {
        "bg": "#F0F4FB" if light else "#0B1425",
        "panel": "#FFFFFF" if light else ("#111E31" if solid else "#192941"),
        "panel2": "#E5EDFA" if light else "#263B55",
        "line": "#BBC8DB" if light else "#557393",
        "fg": "#14213B" if light else "#F6F9FF",
        "muted": "#465A73" if light else "#D0DEF0",
        "accent": accent,
        "accent_fg": "#102036" if settings["accent"] in {"mint", "amber", "orange", "cyan", "green"} else "#FFFFFF",
        "success": "#15866F" if light else "#82E6BE",
        "error": "#A82B45" if light else "#FFB0C2",
        "light": light,
        "solid": solid,
    }


def primary_monitor(root) -> tuple[int, int, int, int]:
    """Best-effort physical primary display via XRandR; Tk virtual-screen fallback.

    Works on X11 and some XWayland sessions. GNOME Wayland can restrict
    monitor management to the compositor, so manual verification is advised.
    """
    fallback = (0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
    if not os.environ.get("DISPLAY"):
        return fallback
    try:
        result = subprocess.run(["xrandr", "--listmonitors"], text=True,
                                capture_output=True, check=False, timeout=2)
        if result.returncode != 0:
            return fallback
        monitors = []
        for line in result.stdout.splitlines()[1:]:
            # ' 0: +*DP-1 1920/521x1080/293+0+0  DP-1'
            match = re.search(r"^\s*\d+:\s+(\S+)\s+(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)", line)
            if match:
                flags, w, h, x, y = match.groups()
                monitors.append(("*" in flags, int(x), int(y), int(w), int(h)))
        if monitors:
            chosen = next((m for m in monitors if m[0]), monitors[0])
            return chosen[1:]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return fallback


def on_primary(root, width: int, height: int, *, corner: bool = False) -> str:
    x, y, w, h = primary_monitor(root)
    if corner:
        left = x + max(8, w - width - 30)
        top = y + 76
    else:
        left = x + max(0, (w - width) // 2)
        top = y + max(0, (h - height) // 2)
    return f"{width}x{height}{left:+d}{top:+d}"


def clamp_primary(root, x: int, y: int, width: int, height: int) -> tuple[int, int]:
    px, py, pw, ph = primary_monitor(root)
    return max(px, min(x, px + pw - width)), max(py, min(y, py + ph - height))
