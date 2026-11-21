"""Regression checks for the silent-start problem on Windows."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def test_windows_gui_does_not_require_linux_display(monkeypatch):
    from docforge import gui
    class FakeRoot:
        def __init__(self):
            self.tk = self
            self.mainloop_called = False
        def call(self, *args):
            return None
        def mainloop(self):
            self.mainloop_called = True
    root = FakeRoot()
    monkeypatch.setattr(gui, 'os', SimpleNamespace(name='nt', environ={}))
    monkeypatch.setattr(gui, 'RootClass', lambda: root)
    monkeypatch.setattr(gui, 'load_settings', lambda: {'scale': 1})
    monkeypatch.setattr(gui, 'select_appearance', lambda cfg: None)
    monkeypatch.setattr(gui, 'setup_style', lambda x: None)
    constructed=[]
    monkeypatch.setattr(gui, 'MainWindow', lambda r, files: constructed.append(r))
    gui.show_gui('main')
    assert root.mainloop_called and constructed == [root]


def test_installer_and_repair_scripts_exist():
    root = Path(__file__).resolve().parents[1]
    installer = (root/'windows/install.ps1').read_text(encoding='utf-8')
    assert 'Diagnose-DocForge.cmd' in installer
    assert (root/'windows/Repair-DocForge.cmd').is_file()
    assert (root/'windows/Diagnose-DocForge.cmd').is_file()
    launcher = (root/'windows/launcher.py').read_text(encoding='utf-8')
    assert 'last-launch.log' in launcher
    assert 'redirect_stderr' in launcher


def test_windows_show_gui_logic_source():
    root = Path(__file__).resolve().parents[1]
    gui = (root/'docforge/gui.py').read_text(encoding='utf-8')
    assert 'os.name != "nt" and not os.environ.get("DISPLAY")' in gui
