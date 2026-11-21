"""DocForge 1.5 frameless *real-alpha* desktop zone (PySide6 / Qt 6).

Uses native Qt URI Drag & Drop, a transparent ARGB surface and fully vector
painted optical contours. It does NOT read the desktop pixels: the GNOME
compositor decides whether backdrop blur is available on a given Wayland
session. No screenshots or desktop permissions are requested.
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QSize,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QLinearGradient,
                           QIcon, QPainter, QPainterPath, QPen, QRadialGradient, QRegion,
                           QTransform)
from .zone_interaction import DropSession

from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMenu, QPushButton,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from .appearance import (ACCENTS, ANIMATION_STYLES, DEFAULTS, SIZES, THEMES, ZONE_STYLES,
                         SLIDER_SETTINGS, setting_from_slider, slider_from_setting,
                         glass_opacity_strength,
                         config_file, load_settings, save_settings)
from .core import (ConversionError, compress_pdf, convert, merge_pdfs,
                   rotate_pdf, source_ext, split_pdf)
from .liquid_geometry import (CENTER_H, CENTER_W, DESIGN_H, DESIGN_W,
                              IDLE_H, IDLE_W, PETAL_H, PETAL_W, draw_scale,
                              RevealTimeline, petal_reveal, positions, size_for,
                              spring_step_dt, startup_reveal)
from .petals import Action, actions_for


def _color(hex_value: str, alpha: int = 255) -> QColor:
    color = QColor(hex_value)
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


def _filename_paths(urls) -> list[Path]:
    paths: list[Path] = []
    for url in urls:
        if url.isLocalFile():
            path = Path(url.toLocalFile())
            if path.is_file() and path not in paths:
                paths.append(path)
    return paths


def _hue_for(action: Action) -> QColor:
    return QColor(action.color)


def _draw_glass(p: QPainter, shape: QPainterPath, bounds: QRectF, color: QColor,
                *, strength: float = 1.0, selected: bool = False,
                style: str = 'clear', refraction: float = .8) -> None:
    """Multilayer transparent liquid-glass edge, not a solid colored sprite.

    We preserve the destination desktop through ARGB transparency. Colored
    Fresnel edges, layered gradients, caustic bands and specular arcs convey
    lens curvature without pretending we can sample Wayland desktop pixels.
    """
    p.save()
    rect = bounds
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cc = QColor(color)
    matte = style == 'matte'
    crystal = style == 'crystal'
    body_alpha = round((70 if matte else 25 if crystal else 35) * strength)

    # Soft outer optical halo, built from thin paths (fast, no raster blur).
    for spread in (10, 6, 3):
        halo = QPen(_color(cc.name(), round((7 + 18 * refraction) * (1.6 if selected else 1.0))))
        halo.setWidthF(spread)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(halo)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)

    # Desktop is visible through the center. Low-alpha layers add depth.
    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0, QColor(255,255,255,min(150, body_alpha + 33)))
    base.setColorAt(.28, QColor(cc.red(),cc.green(),cc.blue(),body_alpha))
    base.setColorAt(.66, QColor(42,69,108,min(255,round(body_alpha*.9))))
    base.setColorAt(1, QColor(cc.red(),cc.green(),cc.blue(),min(160,body_alpha+31)))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(base))
    p.drawPath(shape)

    # Subtle internal bright caustic and shadow underneath the curved wall.
    p.save()
    p.setClipPath(shape)
    sheen = QLinearGradient(rect.left(),rect.top(),rect.right(),rect.bottom())
    sheen.setColorAt(0, QColor(255,255,255, 113 if not matte else 45))
    sheen.setColorAt(.31, QColor(255,255,255,0))
    sheen.setColorAt(.74, QColor(cc.red(),cc.green(),cc.blue(),0))
    sheen.setColorAt(1, QColor(cc.red(),cc.green(),cc.blue(),min(125,round(80*refraction))))
    p.fillRect(rect, QBrush(sheen))
    # Reflected ribbon in upper quarter; only translucent material is painted.
    spec = QPainterPath()
    spec.moveTo(rect.left()+rect.width()*.11,rect.top()+rect.height()*.25)
    spec.cubicTo(rect.left()+rect.width()*.26,rect.top()+rect.height()*.02,
                 rect.left()+rect.width()*.66,rect.top()+rect.height()*.02,
                 rect.right()-rect.width()*.08,rect.top()+rect.height()*.27)
    ribbon = QPen(QColor(255,255,255,round(86*refraction)))
    ribbon.setWidthF(max(1.5,rect.width()*.027))
    ribbon.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(ribbon)
    p.drawPath(spec)
    p.restore()

    # Lens wall: wide inner rim + smaller chromatic bands. Varying the
    # refraction slider now changes the wall thickness AND intensity, not just
    # one nearly invisible one-pixel stroke. This is a visual approximation;
    # pixels underneath the window are never captured or displaced on Wayland.
    p.save()
    p.setClipPath(shape)
    wall = max(1.5, min(bounds.width(), bounds.height()) * (.05 + .10 * refraction))
    wall_tint = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
    wall_tint.setColorAt(0, QColor(255, 255, 255, round(40 + 130 * refraction)))
    wall_tint.setColorAt(.28, QColor(255, 255, 255, round(15 + 40 * refraction)))
    wall_tint.setColorAt(.65, QColor(cc.red(), cc.green(), cc.blue(), round(30 + 100 * refraction)))
    wall_tint.setColorAt(1, QColor(13, 43, 91, round(40 + 110 * refraction)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    rim = QPen(QBrush(wall_tint), wall)
    rim.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    rim.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(rim)
    p.drawPath(shape)
    p.restore()

    # Outside chromatic fringes and a bright catchlight on the curved surface.
    p.setBrush(Qt.BrushStyle.NoBrush)
    spectral = QPen(QColor(cc.red(), cc.green(), cc.blue(),
                           round((70 if selected else 45) + 135 * refraction)))
    spectral.setWidthF(2.2 if selected else 1.25 + 1.15 * refraction)
    spectral.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(spectral)
    p.drawPath(shape)
    white = QPen(QColor(255, 255, 255, round(55 + 175 * refraction)))
    white.setWidthF(.75 + 1.25 * refraction)
    white.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(white)
    p.drawPath(shape)
    p.restore()


def _petal_path(w: float, h: float) -> QPainterPath:
    """Balanced liquid petal with a soft neck and rounded outer bulb.

    The path is centered so vertical petals no longer appear pinched or skewed.
    """
    path = QPainterPath()
    tip_x = -w * 0.43
    shoulder_x = -w * 0.20
    body_x = w * 0.16
    outer_x = w * 0.43
    top_y = -h * 0.47
    low_y = h * 0.47
    path.moveTo(tip_x, 0)
    path.cubicTo(-w * 0.37, -h * 0.20,
                 shoulder_x, top_y,
                 body_x, top_y)
    path.cubicTo(outer_x, -h * 0.44,
                 outer_x, h * 0.44,
                 body_x, low_y)
    path.cubicTo(shoulder_x, low_y,
                 -w * 0.37, h * 0.20,
                 tip_x, 0)
    path.closeSubpath()
    return path


def _core_path(w: float, h: float, progress: float = 0.) -> QPainterPath:
    # Compact state is a soft square; expanded hub becomes nearly spherical.
    roundness = .27 + .23*max(0.,min(1.,progress))
    path = QPainterPath()
    path.addRoundedRect(QRectF(-w/2,-h/2,w,h), w*roundness,h*roundness)
    return path


def _text(p: QPainter, x: float, y: float, value: str, size: float,
          *, bold: bool = True, alpha: int = 255, width: float = 245) -> None:
    font = QFont('DejaVu Sans')
    font.setPointSizeF(max(7.,size))
    font.setBold(bold)
    p.setFont(font)
    rect = QRectF(x-width/2,y-24,width,48)
    # Glass needs a tiny soft shadow for contrast against light wallpapers.
    p.setPen(QColor(15,32,66,150))
    p.drawText(rect.translated(0,1.5),Qt.AlignmentFlag.AlignCenter,value)
    p.setPen(QColor(255,255,255,alpha))
    p.drawText(rect,Qt.AlignmentFlag.AlignCenter,value)


class _WorkerEvents(QObject):
    done = Signal(object)
    failed = Signal(str)


class LiquidZone(QWidget):
    """Borderless desktop widget: compact when idle, flower while dragging."""

    def __init__(self, *, temporary: bool = False, initial: list[Path] | None = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName('docforgeLiquidZone')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setWindowTitle('DocForge — стеклянная зона')
        icon_file = (Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
                     / 'assets' / 'docforge-zone.png')
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))
        self.temporary = temporary
        self.config = load_settings()
        self._paths = list(initial or [])
        self._actions: list[Action] = []
        self._visible = False
        self._progress = 0.
        self._timeline = RevealTimeline(duration_ms=self.config['reveal_ms'])
        self._last_animation_tick = time.monotonic()
        # The native rectangle remains the same size from startup through drop.
        # Only its hit region changes, never its window geometry during DnD.
        self._surface_expanded = True
        self._mask_expanded = False
        self._drag_sequence = 0
        self._drop_session = DropSession()
        self._startup_started_at = time.monotonic()
        self._startup_alpha = 0.0 if self.config['petal_animation'] else 1.0
        self._startup_zoom = .94 if self.config['petal_animation'] else 1.0
        self._hover: int | None = None
        self._scales: list[float] = []
        self._velocities: list[float] = []
        self._busy = False
        self._status = ''
        self._dragged_file = False
        self._mouse_origin = None
        self._window_origin = None
        self._moved = False
        self._worker_events = _WorkerEvents(self)
        self._worker_events.done.connect(self._on_finished)
        self._worker_events.failed.connect(self._on_failed)
        self._settings_dialog = None
        self._animation = QTimer(self)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._animate)
        self._config_timer = QTimer(self)
        self._config_timer.setInterval(700)
        self._config_timer.timeout.connect(self._poll_settings)
        self._config_stamp = self._settings_stamp()
        self._config_timer.start()
        self._primary = QApplication.primaryScreen()
        # Qt refreshRate() uses the active monitor, so the animation can run
        # at 60–120 Hz without changing its wall-clock duration.
        hz = float(self._primary.refreshRate() or 60.0)
        self._animation.setInterval(round(1000.0 / max(60.0, min(120.0, hz))))
        area = self._primary.availableGeometry()
        self._monitor = area
        # Leave space for the expanded flower *before* showing the compact zone.
        # Otherwise expansion physically moves the drop target under the cursor.
        ew, eh = size_for(self.config['zone_size'], area.width(), area.height(), True)
        cx = area.x() + round(area.width() * .72)
        cy = area.y() + round(area.height() * .53)
        self._center_point = QPoint(
            max(area.x() + ew // 2 + 4, min(cx, area.right() - ew // 2 - 4)),
            max(area.y() + eh // 2 + 4, min(cy, area.bottom() - eh // 2 - 4)))
        self._set_geometry(True)
        # Always-on-top is a conscious preference, not the default.
        if self.config['always_on_top']:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,True)
        if initial:
            self._show_paths(self._paths)
        self.show()
        self._update_input_mask(bool(initial))
        self.raise_()
        # Animate the initial compact glass capsule even when no file exists.
        self._animation.start()

    @staticmethod
    def _settings_stamp() -> tuple[int,int] | None:
        try:
            st = config_file().stat()
            return st.st_mtime_ns, st.st_size
        except OSError:
            return None

    def _poll_settings(self) -> None:
        stamp = self._settings_stamp()
        if stamp != self._config_stamp:
            self._config_stamp = stamp
            self.apply_preferences(load_settings())

    def apply_preferences(self, value: dict) -> None:
        before = self.config
        now = time.monotonic()
        self._progress = self._timeline.at(now)
        self._timeline.retime(value['reveal_ms'], now)
        self.config = dict(value)
        if bool(before['always_on_top']) != bool(value['always_on_top']):
            # Changing window flags may recreate a native surface.
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,
                               bool(value['always_on_top']))
            self.show()
        # Setting changes may resize the stationary compact canvas, but never
        # while a native drag is in progress. Keep the current drag coordinates.
        if not self._dragged_file:
            self._set_geometry(True)
            self._update_input_mask(self._visible or self._progress > .0001)
        if not self._animation.isActive():
            self._last_animation_tick = time.monotonic()
        self._animation.start()
        self.update()

    def _set_geometry(self, expanded: bool = True) -> None:
        """Allocate one stable, small native surface for both idle and petals.

        In the old design, resizing this QWidget in dragEnterEvent cancelled the
        ongoing drag on some Wayland/X11 compositors. Never do that again.
        """
        area = self._monitor
        w, h = size_for(self.config['zone_size'], area.width(), area.height(), True)
        cx = max(area.x()+w//2+5, min(self._center_point.x(), area.right()-w//2-5))
        cy = max(area.y()+h//2+5, min(self._center_point.y(), area.bottom()-h//2-5))
        self._center_point = QPoint(cx, cy)
        self.setGeometry(cx-w//2, cy-h//2, w, h)
        self._surface_expanded = True

    def _update_input_mask(self, expanded: bool) -> None:
        """Keep a generous, rectangular *input* region without clipping glass.

        Elliptical QRegion masks clipped the rounded central capsule and its
        antialiased edge into an octagon. Qt recommends alpha painting, rather
        than a shaped QRegion, for smooth translucent window corners.
        """
        cx, cy = self.width() // 2, self.height() // 2
        if expanded:
            # Accept drops anywhere around the visible flower. The outer Qt
            # surface is transparent, so the desktop remains visible behind it.
            region = QRegion(self.rect())
        else:
            w, h = self._core_dimensions()
            pad = max(12, round(12 * draw_scale(self.width(), self.height())))
            region = QRegion(QRect(round(cx - w / 2) - pad,
                                   round(cy - h / 2) - pad,
                                   round(w) + 2 * pad, round(h) + 2 * pad))
        self._mask_expanded = expanded
        self.setMask(region)

    def _show_paths(self, paths: list[Path]) -> None:
        if self._busy:
            return
        allowed = actions_for(paths)
        if not allowed:
            self._status = 'Нет подходящих форматов'
            self.update()
            return
        now = time.monotonic()
        old_actions = [(a.key, a.operation) for a in self._actions]
        new_actions = [(a.key, a.operation) for a in allowed]
        if old_actions != new_actions:
            self._actions = allowed
            self._scales = [1.0] * len(allowed)
            self._velocities = [0.0] * len(allowed)
            self._hover = None
        self._paths = list(paths)
        self._status = 'Выберите формат'
        was_opening = self._visible and self._timeline.target == 1.0
        self._visible = True
        self._drag_sequence += 1  # cancel a pending dragLeave collapse
        if not self._mask_expanded:
            # Defer the native input-region change until dragEnterEvent returns.
            # Changing the compositor's region inside the event can synthesize
            # DragLeave (particularly on fractional-scale Wayland desktops).
            QTimer.singleShot(0, self._expand_hit_region)
        # A compositor may emit another dragEnter after the transparent native
        # window resizes. Never restart the same opening animation on re-entry.
        if was_opening:
            self._progress = self._timeline.at(now)
        else:
            self._progress = self._timeline.move_to(1.0, now)
        self._last_animation_tick = now
        self._animation.start()
        self.update()

    def _expand_hit_region(self) -> None:
        if self._visible and not self._mask_expanded and not self._busy:
            self._update_input_mask(True)

    def _collapse(self) -> None:
        if self._busy:
            return
        now = time.monotonic()
        self._visible = False
        self._hover = None
        self._dragged_file = False
        self._drop_session.drop()
        self._paths = []
        self._status = ''
        self._drag_sequence += 1
        self._progress = self._timeline.move_to(0.0, now)
        self._last_animation_tick = now
        self._animation.start()
        self.update()

    def _animate(self) -> None:
        now = time.monotonic()
        dt = max(0.0, now - self._last_animation_tick)
        self._last_animation_tick = now
        active = bool(self.config['petal_animation'])
        self._startup_alpha, self._startup_zoom = (
            startup_reveal(now - self._startup_started_at) if active else (1.0, 1.0))
        goal = 1.0 if self._visible else 0.0
        if active:
            self._progress = self._timeline.at(now)
        else:
            self._timeline.start = goal
            self._timeline.target = goal
            self._timeline.started_at = now
            self._progress = goal
        for idx in range(len(self._scales)):
            target = 1.0 + self.config['hover_scale'] if idx == self._hover else 1.0
            if active:
                self._scales[idx], self._velocities[idx] = spring_step_dt(
                    self._scales[idx], self._velocities[idx], target,
                    dt, self.config['bounce'] if self.config['animation_style'] == 'spring' else 0.0)
            else:
                self._scales[idx], self._velocities[idx] = target, 0.0
        self.update()
        settled = (self._startup_alpha == 1.0 and self._progress == goal and
                   all(abs(value-(1.0 + self.config['hover_scale'] if i == self._hover else 1.0)) < .001
                       and abs(speed) < .02 for i, (value, speed)
                       in enumerate(zip(self._scales, self._velocities))))
        if settled:
            self._animation.stop()
            if goal == 0.0 and self._mask_expanded:
                self._actions.clear()
                self._scales.clear()
                self._velocities.clear()
                self._update_input_mask(False)
                self.update()

    def _core_dimensions(self) -> tuple[float, float]:
        compact_w, compact_h = size_for(self.config['zone_size'],
                                        self._monitor.width(), self._monitor.height(), False)
        initial_w = compact_w * .86
        initial_h = compact_h * .86
        scale = draw_scale(self.width(), self.height())
        target_w, target_h = CENTER_W * scale, CENTER_H * scale
        ease = self._progress * self._progress * (3.0 - 2.0 * self._progress)
        return (initial_w + (target_w-initial_w) * ease,
                initial_h + (target_h-initial_h) * ease)

    def _petal_geometry(self, *, final_targets: bool = False):
        """Consistent transforms for rendering and selecting actual leaf outlines.

        During native DnD we keep the *final* hit targets fixed while petals
        travel to them, avoiding moving targets that cannot be dropped onto.
        """
        if not self._actions or not self._surface_expanded:
            return []
        scale = draw_scale(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        placements = []
        for idx, petal in enumerate(positions(len(self._actions), self.width(), self.height())):
            value = petal_reveal(
                1.0 if final_targets else self._progress, idx, len(self._actions),
                duration_ms=self.config['reveal_ms'],
                bounce=self.config['bounce'],
                style=self.config['animation_style'])
            position = .18 + .82 * value
            x = cx + (petal.x-cx)*position
            y = cy + (petal.y-cy)*position
            # A petal emerges from beneath the glass center rather than
            # suddenly existing at full size on its final orbit.
            appear = max(0.0, min(1.0, value))
            factor = (.72 + .28 * appear) * scale
            if idx < len(self._scales):
                factor *= self._scales[idx]
            alpha = min(1.0, max(0.0, appear * 2.0))
            placements.append((x, y, petal.angle, PETAL_W*factor, PETAL_H*factor, alpha))
        return placements

    def _index_at(self, pos, *, final_targets: bool = False) -> int | None:
        if (self._progress < .36 and not final_targets) or not self._actions:
            return None
        cx, cy = self.width()/2, self.height()/2
        cw, ch = self._core_dimensions()
        if _core_path(cw, ch, self._progress).contains(QPointF(pos.x()-cx, pos.y()-cy)):
            return None
        # Test the exact rotated organic glass silhouette, not the ellipse
        # previously used by the hover hit test.
        for i, (x, y, angle, w, h, alpha) in reversed(list(enumerate(
                self._petal_geometry(final_targets=final_targets)))):
            if alpha < .45:
                continue
            dx, dy = pos.x()-x, pos.y()-y
            theta = math.radians(angle)
            local = QPointF(dx*math.cos(theta)+dy*math.sin(theta),
                            -dx*math.sin(theta)+dy*math.cos(theta))
            if _petal_path(w, h).contains(local):
                return i
            # The liquid outline is narrower at the neck. A small tolerance
            # keeps native file drops selectable along its luminous edge.
            if final_targets and (local.x()/(w*.49))**2 + (local.y()/(h*.53))**2 < 1.0:
                return i
        return None

    def _set_hover(self, pos) -> None:
        index = self._index_at(pos, final_targets=self._dragged_file)
        if index != self._hover:
            self._hover = index
            if not self._animation.isActive():
                self._last_animation_tick = time.monotonic()
            self._animation.start()
        self.setCursor(Qt.CursorShape.PointingHandCursor if index is not None
                       else Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing,True)
        center = QPoint(self.width()//2,self.height()//2)
        glass_factor = glass_opacity_strength(self.config['opacity'])
        if self._surface_expanded and (self._visible or self._progress > 0.0001):
            for idx, (px, py, angle, w, h, alpha) in enumerate(self._petal_geometry()):
                if alpha <= 0.001:
                    continue
                p.save()
                p.setOpacity(alpha)
                p.translate(px, py)
                p.rotate(angle)
                path = _petal_path(w, h)
                bounds = path.boundingRect()
                tint = _hue_for(self._actions[idx])
                strength = glass_factor
                if idx == self._hover:
                    strength = min(1.75, strength * 1.18)
                _draw_glass(p, path, bounds, tint, strength=strength,
                            selected=(idx == self._hover), style=self.config['zone_style'],
                            refraction=self.config.get('refraction', .8))
                p.restore()
                # Text stays horizontally aligned while petals stretch and rotate.
                if alpha > .20:
                    p.save()
                    p.setOpacity(min(1.0, alpha))
                    label = {
                        'md': 'MD', 'split': 'Раздел.', 'compress': 'Сжать',
                        'merge': 'Объед.', 'rotate': 'Поверн.', 'edit': 'EDIT'
                    }.get(self._actions[idx].key, self._actions[idx].label)
                    if label.startswith('В '):
                        label = label[2:]
                    scale = draw_scale(self.width(), self.height())
                    size = (8.5 if len(label) > 6 else 10.0) * scale * (1.05 if idx == self._hover else 1.0)
                    _text(p, px, py, label, size, width=160*scale)
                    p.restore()
        # An expanded Qt surface is transparent outside the drawn shapes;
        # the center remains visually compact until the animation expands it.
        cw, ch = self._core_dimensions()
        p.save()
        p.setOpacity(self._startup_alpha)
        p.translate(center)
        shape=_core_path(cw*self._startup_zoom,ch*self._startup_zoom,self._progress)
        hue=QColor(ACCENTS[self.config['accent']][1])
        # The center must be readable against both bright and dark wallpapers.
        _draw_glass(p,shape,shape.boundingRect(),hue,
                    strength=(1.0 if self._progress<.2 else 1.15)*glass_factor,
                    style=self.config['zone_style'],
                    refraction=self.config.get('refraction',.8))
        # Dark translucent tint is weak, purpose: contrast not fake wallpaper.
        gl=QLinearGradient(-cw*.4,-ch*.4,cw*.4,ch*.4)
        is_dark=self.config['theme'] in ('liquid_dark','midnight')
        gl.setColorAt(0,QColor(8,21,50,round((56 if is_dark else 16)*(1.10-self.config['opacity']*.60))))
        gl.setColorAt(1,QColor(11,22,46,round((108 if is_dark else 44)*(1.10-self.config['opacity']*.60))))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(shape,QBrush(gl))
        p.restore()
        compact_scale = min(*[a/b for a,b in zip(size_for(self.config['zone_size'],
                            self._monitor.width(),self._monitor.height(),False), (IDLE_W,IDLE_H))])
        expanded_scale = draw_scale(self.width(), self.height()) if self._surface_expanded else compact_scale
        scale = max(.72, compact_scale + (expanded_scale-compact_scale)*self._progress)
        x,y=center.x(),center.y()
        p.save()
        p.setOpacity(self._startup_alpha)
        _text(p, x, y, '+', 32*scale, width=cw*.96)
        p.restore()
        p.end()

    # Native Qt drag/drop gets the files on dragEnter, unlike TkinterDnD.
    def dragEnterEvent(self,event) -> None:
        if self._busy or not event.mimeData().hasUrls():
            event.ignore();return
        paths=_filename_paths(event.mimeData().urls())
        if paths and actions_for(paths):
            self._dragged_file=True
            self._drop_session.enter()
            self._show_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self,event) -> None:
        if self._busy or not event.mimeData().hasUrls():
            event.ignore()
            return
        # Some compositors resume with DragMove after a transient DragLeave.
        # Preserve the same actions and elapsed animation, then highlight the
        # target at the file cursor rather than waiting for mouseMoveEvent.
        if not self._dragged_file:
            self._dragged_file = True
            self._drop_session.enter()
        self._set_hover(event.position())
        event.acceptProposedAction()

    def dragLeaveEvent(self,event) -> None:
        self._dragged_file = False
        token = self._drop_session.leave(time.monotonic())
        self._drag_sequence += 1
        # Native resize/transparent regions can generate spurious Leave events.
        # Wait for a genuine exit before folding and clearing selected paths.
        QTimer.singleShot(340, lambda token=token: self._after_drag_leave(token))
        event.accept()

    def _after_drag_leave(self, token: int) -> None:
        if self._busy:
            return
        # Test the actual input shape, not the invisible rectangle around it.
        # A cursor outside the flower but still inside that rectangle counts as
        # a genuine leave, so the petals fold without getting stuck open.
        pointer_in_window = self.mask().contains(self.mapFromGlobal(QCursor.pos()))
        if self._drop_session.should_collapse(token, time.monotonic(), pointer_in_window):
            self._collapse()
        elif (token == self._drop_session.generation and
              not self._drop_session.inside and
              self._drop_session.leave_deadline is not None):
            QTimer.singleShot(140, lambda token=token: self._after_drag_leave(token))

    def dropEvent(self,event) -> None:
        paths=_filename_paths(event.mimeData().urls())
        self._dragged_file=False
        self._drop_session.drop()
        if not paths or not actions_for(paths):
            event.ignore();return
        # Use the current RELEASE coordinates. A previously highlighted petal
        # must never be chosen if the cursor moved away just before dropping.
        self._animate()
        chosen = self._index_at(event.position(), final_targets=True)
        # The same action list was built at dragEnter, but revalidate exact
        # paths before dispatch to guard against unsupported selections.
        valid=actions_for(paths)
        self._paths=paths
        if chosen is not None and chosen<len(self._actions):
            target=self._actions[chosen]
            match=next((a for a in valid if (a.key,a.operation)==(target.key,target.operation)),None)
            if match:
                self._run_action(match)
                event.acceptProposedAction()
                return
        # Dropping on the central capsule keeps choices on screen: the user can
        # click a petal if a native compositor delivered the drop too early.
        self._show_paths(paths)
        self._status = 'Нажмите на формат'
        event.acceptProposedAction()

    def mousePressEvent(self,event) -> None:
        if event.button()==Qt.MouseButton.LeftButton:
            self._mouse_origin=event.globalPosition().toPoint()
            self._window_origin=self.pos()
            self._moved=False
            event.accept()

    def mouseMoveEvent(self,event) -> None:
        if (self._mouse_origin is not None and
                bool(event.buttons() & Qt.MouseButton.LeftButton)):
            delta=event.globalPosition().toPoint()-self._mouse_origin
            if abs(delta.x())+abs(delta.y())>9:
                self._moved=True
                new=self._window_origin+delta
                a=self._monitor
                new.setX(max(a.left(),min(new.x(),a.right()-self.width())))
                new.setY(max(a.top(),min(new.y(),a.bottom()-self.height())))
                self.move(new)
                self._center_point=QPoint(new.x()+self.width()//2,new.y()+self.height()//2)
                return
        self._set_hover(event.position())

    def mouseReleaseEvent(self,event) -> None:
        if event.button()!=Qt.MouseButton.LeftButton:
            return
        self._mouse_origin=None
        if self._moved:
            return
        idx=self._index_at(event.position())
        if idx is not None and self._paths:
            self._run_action(self._actions[idx]);return
        if not self._visible:
            self.open_file()
        elif not self._busy:
            # Clicking center after selecting files keeps petals open.
            if not self._paths:
                self.open_file()

    def mouseDoubleClickEvent(self,event) -> None:
        if event.button()==Qt.MouseButton.LeftButton:
            self.open_file()

    def leaveEvent(self,event) -> None:
        if self._hover is not None:
            self._hover=None
            if not self._animation.isActive():
                self._last_animation_tick = time.monotonic()
            self._animation.start()

    def contextMenuEvent(self,event) -> None:
        menu=QMenu(self)
        menu.addAction('Выбрать файлы…',self.open_file)
        menu.addAction('Настройки стекла…',self.open_settings)
        if self._visible:
            menu.addAction('Свернуть лепестки',self._collapse)
        menu.addSeparator()
        menu.addAction('Закрыть зону',self.close)
        menu.exec(event.globalPos())

    def keyPressEvent(self,event) -> None:
        if event.key()==Qt.Key.Key_Escape:
            self._collapse() if self._visible else self.close()
        elif event.key()==Qt.Key.Key_O and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.open_file()
        else:
            super().keyPressEvent(event)

    def open_file(self) -> None:
        if self._busy:
            return
        files,_=QFileDialog.getOpenFileNames(self,'Выберите файлы для преобразования')
        if files:
            self._show_paths([Path(f) for f in files])

    def open_settings(self) -> None:
        if self._settings_dialog is None or not self._settings_dialog.isVisible():
            self._settings_dialog=LiquidSettings(self)
            self._settings_dialog.show()
            self._settings_dialog.raise_()

    def _run_action(self,action: Action) -> None:
        if self._busy or not self._paths:
            return
        paths=list(self._paths)
        self._busy=True
        self._status='Преобразование…'
        self._hover=None
        self.update()
        def job():
            try:
                if action.operation=='edit':
                    command = ([sys.executable] if getattr(sys, 'frozen', False)
                               else [sys.executable, '-m', 'docforge'])
                    subprocess.Popen(command + ['edit', str(paths[0])],
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    results = [paths[0]]
                elif action.operation=='convert':
                    results=[convert(path,action.target) for path in paths]
                elif action.operation=='split':
                    results=[split_pdf(path,'all') for path in paths]
                elif action.operation=='compress':
                    results=[compress_pdf(path,'ebook') for path in paths]
                elif action.operation=='merge':
                    results=[merge_pdfs(paths)]
                elif action.operation=='rotate':
                    results=[rotate_pdf(path,90) for path in paths]
                else:
                    raise ConversionError('Неподдерживаемая операция')
                self._worker_events.done.emit(results)
            except Exception as exc:
                self._worker_events.failed.emit(str(exc))
        threading.Thread(target=job,daemon=True).start()

    def _on_finished(self,results) -> None:
        self._busy=False
        self._status='Готово ✓'
        self.update()
        try:
            subprocess.Popen(['notify-send','--app-name=DocForge','DocForge: готово',
                              str(results[-1])],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError:
            pass
        # Nautilus opens a persistent zone. Conversion folds the petals, not the window.
        QTimer.singleShot(1500,self._collapse)

    def _on_failed(self,reason: str) -> None:
        self._busy=False
        self._status='Ошибка преобразования'
        self.update()
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self,'Ошибка DocForge',reason)
        self._status='Выберите формат'


class DirectSlider(QSlider):
    """Allow accurate click-to-position AND dragging anywhere on the track."""

    def _value_from_mouse(self, event) -> int:
        from PySide6.QtWidgets import QStyle
        usable_width = max(1, self.width() - 16)
        pos = round(event.position().x()) - 8
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              max(0, min(usable_width, pos)),
                                              usable_width, self.invertedAppearance())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_from_mouse(event))
            self.setSliderDown(True)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isSliderDown():
            self.setValue(self._value_from_mouse(event))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setValue(self._value_from_mouse(event))
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class GlassSample(QWidget):
    """Interactive preview of border optics; no desktop capture or pixel sampling."""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.setMinimumHeight(112)
        self.setMaximumHeight(112)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(3, 3, self.width()-6, self.height()-6)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, QColor('#25364C'))
        bg.setColorAt(.50, QColor('#5E7897'))
        bg.setColorAt(1, QColor('#15283D'))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 15, 15)
        for index in range(5):
            p.setPen(QPen(QColor(240,249,255,70), 4))
            x = 24 + index*max(16, self.width()//5)
            p.drawLine(x, 14, x-11, self.height()-14)
        zone = QPainterPath()
        sample = QRectF(self.width()*.30, 16, self.width()*.40, self.height()-32)
        zone.addRoundedRect(sample, 28, 28)
        tint = QColor(ACCENTS[self.settings['accent']][1])
        _draw_glass(p, zone, zone.boundingRect(), tint,
                    strength=glass_opacity_strength(self.settings['opacity']),
                    style=self.settings['zone_style'],
                    refraction=self.settings['refraction'])
        p.end()


class LiquidSettings(QDialog):
    """Editable live Qt controls. Settings persist and sync to Tk main window."""
    def __init__(self,zone: LiquidZone):
        # An independent non-modal top-level: moving the floating zone cannot
        # move this window, and it never grabs focus/modal control from it.
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.zone=zone
        self._drag_origin = None
        self._window_origin = None
        self.settings=dict(zone.config)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle('DocForge — Оформление')
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(620, max(390, area.width() - 32)),
                    min(830, max(450, area.height() - 36)))
        self.setMinimumSize(min(480, self.width()), min(570, self.height()))
        self._build()
        area = QApplication.primaryScreen().availableGeometry()
        width, height = self.width(), self.height()
        x = min(max(area.left() + 12, zone.x() - width - 24), area.right() - width - 12)
        y = min(max(area.top() + 12, zone.y()), area.bottom() - height - 12)
        self.move(x, y)

    def paintEvent(self,event) -> None:
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape=QPainterPath()
        shape.addRoundedRect(QRectF(5,5,self.width()-10,self.height()-10),27,27)
        _draw_glass(painter,shape,shape.boundingRect(),QColor('#7A9DCA'),
                    strength=1.4,style='matte',refraction=.7)
        # A darker nearly opaque scrim keeps controls readable above all
        # wallpapers: it must not show zone labels through form fields.
        painter.fillPath(shape,QColor(34,47,68,239))
        painter.end()

    def _build(self) -> None:
        self.setStyleSheet('''
            QWidget {font-family: "DejaVu Sans"; color: #FFFFFF; background: transparent;}
            QLabel {background: transparent; font-size: 12px;}
            QComboBox {background: rgba(255,255,255,35); border:1px solid rgba(255,255,255,90); border-radius:12px; padding:9px; color:white;}
            QComboBox QAbstractItemView {background: #24334C; color: white; selection-background-color: #506B9F;}
            QPushButton {background: rgba(255,255,255,30); border: 1px solid rgba(255,255,255,95); border-radius: 12px; padding: 9px; color: white;}
            QPushButton:hover {background: rgba(255,255,255,65);}
            QCheckBox {background: transparent; spacing:10px;}
            QSlider::groove:horizontal {border:1px solid rgba(255,255,255,75); height:9px; border-radius:5px; background:rgba(225,235,250,70);}
            QSlider::sub-page:horizontal {background:rgba(104,171,255,210); border-radius:5px;}
            QSlider::handle:horizontal {background:#E5F4FF; width:22px; height:22px; margin:-8px 0; border:2px solid #81C7FF; border-radius:11px;}
            QSlider::handle:horizontal:hover {background:#FFFFFF; border:2px solid #4CB9FF;}
        ''')
        outer=QVBoxLayout(self)
        outer.setContentsMargins(31,25,31,26)
        outer.setSpacing(14)
        head=QHBoxLayout()
        heading=QLabel('Оформление')
        heading.setStyleSheet('font-size:22px;font-weight:bold;')
        heading.setCursor(Qt.CursorShape.OpenHandCursor)
        heading.installEventFilter(self)
        self._heading = heading
        head.addWidget(heading)
        head.addStretch()
        close=QPushButton('×')
        close.setFixedWidth(34)
        close.clicked.connect(self.close)
        head.addWidget(close)
        outer.addLayout(head)
        note=QLabel('Параметры применяются сразу и сохраняются.')
        note.setStyleSheet('color:#D0DAEA;')
        outer.addWidget(note)
        self.preview = GlassSample(self.settings, self)
        outer.addWidget(self.preview)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea {background: transparent; border: 0;} QScrollArea > QWidget > QWidget {background: transparent;}')
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 5, 9, 8)
        body_layout.setSpacing(9)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        form=QFormLayout()
        form.setSpacing(15)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.theme=QComboBox()
        for key,value in THEMES.items():self.theme.addItem(value,key)
        self.theme.setCurrentIndex(list(THEMES).index(self.settings['theme']))
        self.theme.currentIndexChanged.connect(lambda: self._set('theme',self.theme.currentData()))
        form.addRow('Тема',self.theme)
        self.style=QComboBox()
        for key,value in ZONE_STYLES.items():self.style.addItem(value,key)
        self.style.setCurrentIndex(list(ZONE_STYLES).index(self.settings['zone_style']))
        self.style.currentIndexChanged.connect(lambda: self._set('zone_style',self.style.currentData()))
        form.addRow('Вид стекла',self.style)
        self.size=QComboBox()
        for key,label in [('compact','Компактный'),('standard','Обычный'),('large','Большой')]:
            self.size.addItem(label,key)
        self.size.setCurrentIndex(['compact','standard','large'].index(self.settings['zone_size']))
        self.size.currentIndexChanged.connect(lambda: self._set('zone_size',self.size.currentData()))
        form.addRow('Размер зоны',self.size)
        self.animation_style = QComboBox()
        for key, label in ANIMATION_STYLES.items():
            self.animation_style.addItem(label, key)
        self.animation_style.setCurrentIndex(list(ANIMATION_STYLES).index(self.settings['animation_style']))
        self.animation_style.currentIndexChanged.connect(
            lambda: self._set('animation_style', self.animation_style.currentData()))
        form.addRow('Стиль анимации', self.animation_style)
        body_layout.addLayout(form)
        body_layout.addWidget(QLabel('Цвет акцента'))
        colors=QGridLayout()
        colors.setHorizontalSpacing(13)
        colors.setVerticalSpacing(11)
        from PySide6.QtWidgets import QButtonGroup
        self.color_group=QButtonGroup(self)
        self.color_group.setExclusive(True)
        for i,(key,(_,hexcolor)) in enumerate(ACCENTS.items()):
            button=QPushButton('●')
            button.setFixedSize(48,43)
            button.setToolTip(key)
            button.setCheckable(True)
            button.setChecked(self.settings['accent']==key)
            self.color_group.addButton(button)
            button.setStyleSheet(f'QPushButton {{color:{hexcolor}; font-size:23px; border-radius:12px; background:rgba(255,255,255,25); border:1px solid rgba(255,255,255,50);}} '
                                 'QPushButton:checked {border:2px solid white; background:rgba(255,255,255,55);}')
            button.clicked.connect(lambda _=False,k=key:self._set('accent',k))
            colors.addWidget(button,i//4,i%4)
        body_layout.addLayout(colors)
        self.sliders = {}
        self.slider_labels = {}
        for title, key, low, high, step, suffix in SLIDER_SETTINGS:
            row = QHBoxLayout()
            name = QLabel(title)
            row.addWidget(name)
            row.addStretch()
            shown = QLabel('')
            shown.setMinimumWidth(72)
            shown.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            shown.setStyleSheet('font-weight: 600; color: #D5E9FF;')
            row.addWidget(shown)
            body_layout.addLayout(row)
            slider = DirectSlider(Qt.Orientation.Horizontal)
            slider.setObjectName(f'glass-slider-{key}')
            slider.setRange(low, high)
            slider.setMinimumHeight(32)
            slider.setPageStep(max(1, (high-low)//20))
            slider.setSingleStep(1)
            slider.setValue(slider_from_setting(key, self.settings[key]))
            shown.setText(f'{slider.value()}{suffix}')
            slider.valueChanged.connect(
                lambda n, k=key, label=shown, u=suffix: self._change_slider(k, n, label, u))
            body_layout.addWidget(slider)
            self.sliders[key] = slider
            self.slider_labels[key] = shown
        self.anim=QCheckBox('Анимировать раскрытие и увеличение лепестков')
        self.anim.setChecked(self.settings['petal_animation'])
        self.anim.toggled.connect(lambda flag:self._set('petal_animation',flag))
        body_layout.addWidget(self.anim)
        self.pin=QCheckBox('Закреплять поверх всех окон')
        self.pin.setChecked(self.settings['always_on_top'])
        self.pin.toggled.connect(lambda flag:self._set('always_on_top',flag))
        body_layout.addWidget(self.pin)
        actions=QHBoxLayout()
        reset=QPushButton('По умолчанию')
        reset.clicked.connect(self._reset)
        actions.addWidget(reset)
        actions.addStretch()
        ok=QPushButton('Готово')
        ok.clicked.connect(self.close)
        actions.addWidget(ok)
        outer.addLayout(actions)

    def eventFilter(self, watched, event) -> bool:
        # Drag the undecorated settings window by its heading independently
        # from the zone. startSystemMove is Wayland-safe; mouse move is an X11
        # fallback for compositors that do not expose system-move support.
        if getattr(self, '_heading', None) is watched:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = event.globalPosition().toPoint()
                self._window_origin = self.pos()
                handle = self.windowHandle()
                self._system_moving = bool(handle and handle.startSystemMove())
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_origin is not None:
                if not getattr(self, '_system_moving', False):
                    self.move(self._window_origin + event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
                self._window_origin = None
                self._system_moving = False
                return True
        return super().eventFilter(watched, event)

    def _change_slider(self, key: str, raw: int, label: QLabel, suffix: str) -> None:
        label.setText(f'{raw}{suffix}')
        self._set(key, setting_from_slider(key, raw))

    def _set(self,key,value) -> None:
        self.settings[key]=value
        try:
            save_settings(self.settings)
        except OSError as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self,'Не удалось сохранить настройки',str(exc))
            return
        self.zone.apply_preferences(self.settings)
        self.zone._config_stamp=self.zone._settings_stamp()
        self.preview.settings = dict(self.settings)
        self.preview.update()

    def _reset(self) -> None:
        self.settings=DEFAULTS.copy()
        save_settings(self.settings)
        self.zone.apply_preferences(self.settings)
        self.close()
        self.zone.open_settings()


def show_liquid_zone(mode: str = 'dropzone', initial: list[Path] | None = None) -> None:
    app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(True)
    icon_file = (Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
                 / 'assets' / 'docforge-zone.png')
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    zone=LiquidZone(temporary=False,initial=initial)
    # Hold a Python reference for the complete application lifetime.
    app._docforge_zone=zone
    app.exec()
