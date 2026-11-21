"""Regression checks for draggable settings, stable petal targets and dashboard."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from docforge.dashboard import dashboard_colors, panel_texture
from docforge.zone_interaction import DropSession


def test_transient_drag_leave_is_cancelled_by_reentry():
    session = DropSession()
    session.enter()
    leave_token = session.leave(100.0)
    session.enter()
    assert not session.should_collapse(leave_token, 101.0, False)
    assert session.inside


def test_real_drag_leave_folds_outside_and_not_during_false_leave_inside():
    session = DropSession()
    session.enter()
    token = session.leave(10.0)
    assert not session.should_collapse(token, 10.10, False)
    assert session.should_collapse(token, 10.33, False)
    session.enter()
    token = session.leave(20.0)
    assert not session.should_collapse(token, 20.36, True)
    assert not session.should_collapse(token, 20.70, True)
    assert session.should_collapse(token, 20.70, False)


def test_drop_invalidates_old_leave_callback():
    session = DropSession()
    session.enter()
    token = session.leave(0.0)
    session.drop()
    assert not session.should_collapse(token, 50.0, False)


def test_qt_petal_target_stays_fixed_and_reentry_does_not_restart_time():
    source = (Path(__file__).parent.parent / 'docforge' / 'liquid_qt.py').read_text()
    assert 'if was_opening:' in source
    assert 'self._timeline.at(now)' in source
    assert 'final_targets=self._dragged_file' in source
    assert 'chosen = self._index_at(event.position(), final_targets=True)' in source
    assert 'self._drop_session.should_collapse(' in source
    assert 'self._after_drag_leave(token)' in source


def test_settings_window_is_independent_and_can_move_via_wayland():
    source = (Path(__file__).parent.parent / 'docforge' / 'liquid_qt.py').read_text()
    section = source.split('class LiquidSettings(QDialog):', 1)[1]
    assert 'super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)' in section
    assert 'Qt.WindowModality.NonModal' in section
    assert 'handle.startSystemMove()' in section
    assert 'self._heading = heading' in section
    assert 'QColor(34,47,68,239)' in section


def test_dark_dashboard_palette_and_rounded_panels():
    for theme in ('liquid_light', 'liquid_dark', 'midnight'):
        colors = dashboard_colors({'theme': theme, 'accent': 'violet'})
        assert colors['text'] == '#f6f8fe'
        assert colors['accent'] == '#A78BFA'
        image = panel_texture(420, 300, colors['card'])
        assert image.mode == 'RGBA'
        assert image.getpixel((0, 0))[3] == 0
        assert image.getpixel((200, 150))[3] == 255


def test_main_window_dashboard_smoke_x11(tmp_path):
    if not shutil.which('xvfb-run'):
        import pytest
        pytest.skip('Xvfb unavailable')
    code = '''
from docforge.gui import RootClass, MainWindow, setup_style, select_appearance
from docforge.appearance import load_settings
from docforge.dashboard import DashboardCard, DashboardButton
root = RootClass(); select_appearance(load_settings()); setup_style(root)
main = MainWindow(root)
root.update_idletasks()
assert len([w for w in root.winfo_children() if w.winfo_class() == 'Frame']) >= 2
assert main.dashboard_colors['text'] == '#f6f8fe'
assert main.convert_btn.winfo_exists()
assert isinstance(main.convert_btn, DashboardButton)
assert main.combo.winfo_exists()
main.add_files([])
assert main.format_var.get() == ''
main.convert_btn.configure(state='disabled')
assert str(main.convert_btn.cget('state')) == 'disabled'
root.destroy()
'''
    env = os.environ.copy()
    env['XDG_CONFIG_HOME'] = str(tmp_path / 'cfg')
    run = subprocess.run(['xvfb-run', '-a', sys.executable, '-c', code],
                         cwd=Path(__file__).parent.parent, env=env,
                         text=True, capture_output=True, timeout=25)
    assert run.returncode == 0, run.stderr


def test_refreshed_dashboard_still_converts_real_document(tmp_path):
    if not shutil.which('xvfb-run'):
        import pytest
        pytest.skip('Xvfb unavailable')
    source = tmp_path / 'Русский документ.md'
    source.write_text('# Заголовок\n\nТест конвертации через кнопку интерфейса.\n', encoding='utf-8')
    script = '''
import sys, time
from pathlib import Path
from docforge.gui import RootClass, MainWindow, setup_style, select_appearance
from docforge.appearance import load_settings
root=RootClass();select_appearance(load_settings());setup_style(root)
app=MainWindow(root)
file=Path(sys.argv[1]); app.add_files([file])
assert 'PDF' in app.combo['values']
app.format_var.set('PDF')
app.convert_selected()
limit=time.monotonic()+15
while app.busy and time.monotonic()<limit:
    root.update()
    time.sleep(.05)
assert not app.busy
assert app.last_output is not None and app.last_output.is_file()
assert app.last_output.suffix == '.pdf'
root.destroy()
'''
    env = os.environ.copy()
    env['XDG_CONFIG_HOME'] = str(tmp_path / 'cfg')
    proc = subprocess.run(['xvfb-run', '-a', sys.executable, '-c', script, str(source)],
                          env=env, cwd=Path(__file__).parent.parent,
                          capture_output=True, text=True, timeout=28)
    assert proc.returncode == 0, proc.stderr
