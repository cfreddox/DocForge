"""1.5.3 regression tests: half-size, optical sliders and uncropped Qt capsule."""
from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docforge.appearance import (
    DEFAULTS, SLIDER_SETTINGS, glass_opacity_strength, load_settings,
    save_settings, setting_from_slider, slider_from_setting,
)
from docforge.liquid_geometry import (
    CENTER_H, CENTER_W, DESIGN_H, DESIGN_W, IDLE_H, IDLE_W,
    PETAL_H, PETAL_W, positions, size_for,
)


def test_exact_half_size_and_smaller_petal_geometry():
    assert (DESIGN_W, DESIGN_H) == (250, 230)
    assert (IDLE_W, IDLE_H) == (92, 90)
    assert (CENTER_W, CENTER_H) == (85, 83)
    assert (PETAL_W, PETAL_H) == (72, 42)
    assert size_for('standard', 1920, 1080, True) == (250, 230)
    assert size_for('standard', 1920, 1080, False) == (92, 90)
    for mode in ('compact', 'standard', 'large'):
        w, h = size_for(mode, 1366, 768, True)
        for leaf in positions(8, w, h):
            assert 0 < leaf.x < w and 0 < leaf.y < h


def test_every_slider_maps_correctly_and_can_save(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    for _, key, minimum, maximum, scale, _ in SLIDER_SETTINGS:
        for raw in (minimum, (minimum + maximum) // 2, maximum):
            transformed = setting_from_slider(key, raw)
            assert slider_from_setting(key, transformed) == raw
            saved = {**DEFAULTS, key: transformed}
            save_settings(saved)
            assert load_settings()[key] == transformed
        assert setting_from_slider(key, minimum - 1000) == setting_from_slider(key, minimum)
        assert setting_from_slider(key, maximum + 1000) == setting_from_slider(key, maximum)


def test_material_transparency_slider_actually_reduces_density():
    assert glass_opacity_strength(.10) > glass_opacity_strength(.50)
    assert glass_opacity_strength(.50) > glass_opacity_strength(.98)
    assert glass_opacity_strength(.10) > 1.0
    assert glass_opacity_strength(.98) < .6


def test_qt_uses_rectangular_input_mask_to_prevent_corner_cutoff():
    text = (Path(__file__).parents[1] / 'docforge' / 'liquid_qt.py').read_text()
    klass = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == 'LiquidZone')
    methods = {n.name: ast.get_source_segment(text, n) for n in klass.body if isinstance(n, ast.FunctionDef)}
    mask = methods['_update_input_mask']
    assert 'QRegion(self.rect())' in mask
    assert 'QRegion.RegionType.Ellipse' not in mask
    assert 'self.setMask(region)' in mask
    assert 'compact_w * .86' in methods['_core_dimensions']
    assert 'glass_opacity_strength' in methods['paintEvent']
    assert 'wall = max(1.5' in text and 'refraction' in text


def test_settings_have_larger_window_preview_and_direct_slider_controls():
    text = (Path(__file__).parents[1] / 'docforge' / 'liquid_qt.py').read_text()
    assert 'self.resize(min(620' in text
    assert 'class DirectSlider(QSlider)' in text
    assert 'class GlassSample(QWidget)' in text
    assert 'setting_from_slider(key, raw)' in text
    assert 'self.preview.update()' in text


@pytest.mark.skipif(importlib.util.find_spec('PySide6') is None,
                    reason='PySide6 unavailable in offline test environment')
def test_real_qt_settings_sliders_and_border_render(tmp_path):
    code = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from docforge.liquid_qt import LiquidZone, LiquidSettings
from docforge.appearance import load_settings
app = QApplication([])
zone = LiquidZone()
settings = LiquidSettings(zone)
settings.show()
app.processEvents()
assert settings.width() >= 480
assert len(settings.sliders) == 5
for key, slider in settings.sliders.items():
    slider.setValue(slider.minimum())
    app.processEvents()
    assert settings.slider_labels[key].text()
    assert settings.settings[key] == load_settings()[key]
    slider.setValue(slider.maximum())
    app.processEvents()
    assert settings.settings[key] == load_settings()[key]
settings.preview.grab().save('preview.png')
assert Path('preview.png').stat().st_size > 500
settings.close(); zone.close()
'''
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
           'XDG_CONFIG_HOME': str(tmp_path / 'cfg'),
           'PYTHONPATH': str(Path(__file__).parents[1])}
    proc = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                          capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0, proc.stderr


def test_legacy_100_percent_transparency_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    config = {**DEFAULTS, 'opacity': 1.0}
    save_settings(config)
    assert load_settings()['opacity'] == 1.0
    assert slider_from_setting('opacity', 1.0) == 98
    assert glass_opacity_strength(1.0) == glass_opacity_strength(.98)
