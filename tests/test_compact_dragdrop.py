"""Regression checks for the compact, non-resizing native DnD zone (1.5.2)."""
from __future__ import annotations

import ast
import importlib.util
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docforge.liquid_geometry import (
    CENTER_H, CENTER_W, DESIGN_H, DESIGN_W, PETAL_H, PETAL_W,
    draw_scale, petal_at, positions, size_for, spring_step_dt,
)
from docforge.zone_interaction import DropSession


def test_smaller_zone_and_more_compact_petals():
    assert DESIGN_W <= 520 and DESIGN_H <= 480
    assert CENTER_W <= 180 and CENTER_H <= 180
    assert PETAL_W <= 150 and PETAL_H <= 90
    for mode in ('compact', 'standard', 'large'):
        w, h = size_for(mode, 1920, 1080, True)
        assert w < 600 and h < 550
        idle = size_for(mode, 1920, 1080, False)
        assert idle[0] < 240 and idle[1] < 240


def test_petals_centered_symmetrically_and_selectable_at_release():
    for screen in ((1920, 1080), (1366, 768), (960, 640)):
        for mode in ('compact', 'standard', 'large'):
            w, h = size_for(mode, *screen, expanded=True)
            for count in (3, 4, 5, 6, 8):
                leaves = positions(count, w, h)
                scale = draw_scale(w, h)
                for index, leaf in enumerate(leaves):
                    assert petal_at(leaf.x, leaf.y, count, w, h) == index
                    # All leaves and a 10% hover enlargement fit inside the window.
                    longest = max(PETAL_W, PETAL_H) * scale * .55
                    assert longest < leaf.x < w - longest
                    assert longest < leaf.y < h - longest
                assert petal_at(w/2, h/2, count, w, h) is None
                if count % 2 == 0:
                    top = leaves[0]
                    bottom = leaves[count // 2]
                    assert top.x == pytest.approx(bottom.x)
                    assert top.y + bottom.y == pytest.approx(h)


def test_hover_spring_nine_percent_reverts_without_drift():
    value, velocity = 1.0, 0.0
    samples = []
    for _ in range(45):
        value, velocity = spring_step_dt(value, velocity, 1.09, 1/120, .35)
        samples.append(value)
    assert max(samples) > 1.09
    for _ in range(120):
        value, velocity = spring_step_dt(value, velocity, 1.0, 1/120, .35)
    assert value == pytest.approx(1.0, abs=.001)


def test_drag_reentry_exit_and_release_are_separate():
    session = DropSession()
    session.enter()
    token = session.leave(20.0)
    session.enter()  # synthetic leave caused by window-manager input shape
    assert not session.should_collapse(token, 21.0, False)
    session.leave(22.0)
    assert session.should_collapse(session.generation, 22.34, False)
    session.enter()
    token = session.leave(23.0)
    session.drop()
    assert not session.should_collapse(token, 24.0, False)


def test_native_window_has_no_geometry_change_during_dnd():
    source = (Path(__file__).parent.parent / 'docforge/liquid_qt.py').read_text(encoding='utf-8')
    klass = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'LiquidZone')
    methods = {node.name: ast.get_source_segment(source, node) for node in klass.body if isinstance(node, ast.FunctionDef)}
    for method in ('_show_paths', '_collapse', '_animate', 'dragEnterEvent', 'dragMoveEvent', 'dragLeaveEvent', 'dropEvent'):
        assert 'self._set_geometry(' not in methods[method], method
    assert 'QTimer.singleShot(0, self._expand_hit_region)' in methods['_show_paths']
    assert 'self._set_hover(event.position())' in methods['dragMoveEvent']
    assert 'self._index_at(event.position(), final_targets=True)' in methods['dropEvent']
    assert 'self._update_input_mask(False)' in methods['_animate']
    assert 'self.setMask(region)' in methods['_update_input_mask']


@pytest.mark.skipif(importlib.util.find_spec('PySide6') is None,
                    reason='PySide6 not installed in this build environment')
def test_qt_injected_native_drag_selects_petal(tmp_path):
    """Qt-native event simulation; does not prove real GNOME Wayland DnD."""
    code = r'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, QPointF, QMimeData, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from docforge.liquid_qt import LiquidZone
from docforge.liquid_geometry import positions
app=QApplication([])
zone=LiquidZone()
source=Path('sample.md').resolve()
source.write_text('# Heading\n',encoding='utf-8')
mime=QMimeData()
mime.setUrls([QUrl.fromLocalFile(str(source))])
c=QPoint(zone.width()//2,zone.height()//2)
enter=QDragEnterEvent(c, Qt.CopyAction, mime, Qt.NoButton, Qt.NoModifier)
zone.dragEnterEvent(enter)
app.processEvents()
assert enter.isAccepted() and zone._visible
assert zone._mask_expanded
assert zone._actions
ix=next(i for i,a in enumerate(zone._actions) if a.key=='pdf')
pt=positions(len(zone._actions),zone.width(),zone.height())[ix]
point=QPoint(round(pt.x),round(pt.y))
move=QDragMoveEvent(point,Qt.CopyAction,mime,Qt.NoButton,Qt.NoModifier)
zone.dragMoveEvent(move)
assert move.isAccepted() and zone._hover==ix
selected=[]
zone._run_action=lambda action: selected.append(action.key)
drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.NoButton,Qt.NoModifier)
zone.dropEvent(drop)
assert drop.isAccepted() and selected==['pdf'], selected
zone.close()
'''
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['XDG_CONFIG_HOME'] = str(tmp_path/'config')
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env={**env,'PYTHONPATH':str(Path(__file__).parent.parent)},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
