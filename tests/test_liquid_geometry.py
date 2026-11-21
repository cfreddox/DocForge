"""Regression tests for the 1.4 Qt layout and native-alpha design contracts."""
from __future__ import annotations

import ast
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from docforge.appearance import DEFAULTS, config_file, load_settings, save_settings
from docforge.liquid_geometry import (CENTER_H, CENTER_W, DESIGN_H,
                                      DESIGN_W, IDLE_W, IDLE_H, petal_at, positions, size_for,
                                      spring)


def test_radial_petals_never_go_out_of_window_at_laptop_resolutions():
    for screen in ((1920,1080),(1366,768),(1280,720),(960,640),(800,600)):
        for choice in ('compact','standard','large'):
            w,h=size_for(choice,*screen,expanded=True)
            # Shapes + colored bevels fit inside the Qt window boundary.
            for n in (3,5,8):
                for petal in positions(n,w,h):
                    assert 0 < petal.x < w and 0 < petal.y < h
                    # A conservative rotated-ellipse bound, proportional to screen.
                    assert petal_at(petal.x,petal.y,n,w,h)==positions(n,w,h).index(petal)
            assert w <= screen[0] and h <= screen[1]


def test_idle_and_expanded_use_exact_same_scale():
    for resolution in ((1920,1080),(1280,720),(850,600)):
        for size in ('compact','standard','large'):
            compact=size_for(size,*resolution,False)
            expanded=size_for(size,*resolution,True)
            assert abs(compact[0]/IDLE_W-expanded[0]/DESIGN_W)<.007
            assert abs(compact[1]/IDLE_H-expanded[1]/DESIGN_H)<.007


def test_spring_grows_then_gently_bounces_back():
    value,velocity=1.,0.
    samples=[]
    for _ in range(90):
        value,velocity=spring(value,velocity,1.10)
        samples.append(value)
    assert 1.1 < max(samples) < 1.16
    assert abs(samples[-1]-1.10)<.003
    for _ in range(90):
        value,velocity=spring(value,velocity,1.)
    assert abs(value-1.)<.003


def test_settings_migrate_orange_fiber_to_clear_glass(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    p=config_file()
    p.parent.mkdir(parents=True)
    p.write_text('{"zone_style":"fuzzy","accent":"orange", "theme":"liquid_dark"}')
    previous=load_settings()
    assert previous['zone_style']=='clear'
    assert previous['theme']=='liquid_dark'
    assert previous['always_on_top'] is False
    assert DEFAULTS['zone_style']=='clear'
    assert DEFAULTS['always_on_top'] is False
    saved=save_settings({**previous,'hover_scale':.13,'refraction':.85})
    assert load_settings()['hover_scale']==.13
    assert load_settings()['refraction']==.85
    assert 'liquid_renderer_version' in saved.read_text()


def test_qt_window_is_frameless_transparent_native_and_has_file_dnd():
    path=Path(__file__).parent.parent/'docforge/liquid_qt.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    classes={node.name for node in tree.body if isinstance(node,ast.ClassDef)}
    assert {'LiquidZone','LiquidSettings'}.issubset(classes)
    text=path.read_text(encoding='utf-8')
    for key in ('WA_TranslucentBackground','FramelessWindowHint','dragEnterEvent',
                'dragMoveEvent','dropEvent','setAcceptDrops(True)','mouseMoveEvent',
                'setGeometry','_set_hover','spring_step_dt('):
        assert key in text
    assert 'screenshot' not in text.lower().split('class liquidzone')[1], 'Never read desktop pixels silently'


def test_qt_dependency_and_command_dispatch():
    root=Path(__file__).parent.parent
    assert 'PySide6-Essentials' in (root/'requirements.txt').read_text()
    assert 'PySide6-Essentials' in (root/'update.sh').read_text()
    assert 'show_liquid_zone' in (root/'docforge/cli.py').read_text()
    assert "command + ['--dropzone']" in (root/'docforge/gui.py').read_text()
    p=subprocess.run([sys.executable,'-m','docforge','--version'],capture_output=True,text=True)
    assert p.returncode==0 and '1.11.0' in p.stdout


@pytest.mark.skipif(__import__('importlib').util.find_spec('PySide6') is None,
                    reason='PySide6 unavailable in offline build environment')
def test_qt_real_window_offscreen(tmp_path):
    # When Qt 6 is installed, test both the window flags and an actual render.
    script='''
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication
from docforge.liquid_qt import LiquidZone
app=QApplication([])
w=LiquidZone()
assert bool(w.windowFlags() & Qt.FramelessWindowHint)
assert w.testAttribute(Qt.WA_TranslucentBackground)
assert not bool(w.windowFlags() & Qt.WindowStaysOnTopHint)
app.processEvents()
image_path = os.environ["DOCFORGE_TEST_SCREENSHOT"]
assert w.grab().save(image_path, "PNG")
reader = QImageReader(image_path)
assert reader.canRead(), reader.errorString()
image = reader.read()
assert not image.isNull(), reader.errorString()
assert image.width() == w.width()
assert image.height() == w.height()
w.close()
'''
    import os
    env=os.environ.copy()
    env['QT_QPA_PLATFORM']='offscreen'
    env['XDG_CONFIG_HOME']=str(tmp_path/'config')
    env['DOCFORGE_TEST_SCREENSHOT']=str(tmp_path/'qt.png')
    run=subprocess.run([sys.executable,'-c',script],env=env,capture_output=True,text=True,timeout=20)
    assert run.returncode==0,run.stderr
    assert (tmp_path/'qt.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
