"""Packaging regressions for the 1.10 release: no runtime dependencies are downloaded here."""
from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_version_and_icons():
    from docforge import __version__
    assert __version__ == '1.11.0'
    for name in ('docforge', 'docforge-zone'):
        svg = ROOT / 'assets' / (name + '.svg')
        png = ROOT / 'assets' / (name + '.png')
        ico = ROOT / 'windows' / (name + '.ico')
        assert svg.exists() and png.exists() and ico.exists()
        ET.parse(svg)
        with Image.open(png) as im:
            assert im.size == (512,512) and im.mode == 'RGBA'
            assert im.getpixel((0,0))[3] == 0


def test_zone_window_uses_dedicated_icon():
    src = (ROOT / 'docforge/liquid_qt.py').read_text()
    assert 'docforge-zone.png' in src
    assert 'setWindowIcon' in src


def test_old_shell_indicator_is_removed_and_not_reinstalled():
    assert not (ROOT/'gnome-extension').exists()
    assert not (ROOT/'install-quick-settings.sh').exists()
    cleanup=(ROOT/'remove-gnome-panel.sh').read_text()
    assert 'docforge-quick@local' in cleanup
    assert 'gnome-extensions disable' in cleanup
    for installer in ('install.sh','update.sh'):
        source=(ROOT/installer).read_text()
        assert 'remove-gnome-panel.sh' in source
        assert 'install-quick-settings.sh' not in source
        assert 'docforge-dropzone.desktop' in source


def test_win_gui_bootstrap_is_xml_and_powershell5_compatible():
    setup=(ROOT/'windows/Setup-DocForge.ps1').read_bytes()
    assert setup.startswith(b'\xef\xbb\xbf')
    source=setup.decode('utf-8-sig')
    xaml=source.split("[xml]$xaml = @'",1)[1].split("'@",1)[0].strip()
    ET.fromstring(xaml)
    assert 'install.ps1' in source and 'installer-stdout.log' in source
    assert 'DocForge Zone' in (ROOT/'windows/install.ps1').read_text(encoding='ascii')
    assert 'Setup-DocForge.ps1' in (ROOT/'windows/START-HERE.cmd').read_text(encoding='ascii')


def test_publication_files():
    for file in ('LICENSE','RELEASE_NOTES.md','RELEASE_CHECKLIST.md','PRIVACY.md',
                 'THIRD_PARTY_NOTICES.md','PUBLISHING.md','README.md','CHANGELOG.md'):
        assert (ROOT/file).is_file()
    assert (ROOT/'.github/workflows/build-windows.yml').is_file()
    assert (ROOT/'windows/inno/DocForge.iss').is_file()
    assert 'UninstallDisplayIcon' in (ROOT/'windows/inno/DocForge.iss').read_text()


def test_clean_gnome_extension_without_touching_other_extensions(tmp_path):
    data=tmp_path/'share'
    mine=data/'gnome-shell/extensions/docforge-quick@local'
    other=data/'gnome-shell/extensions/clipboard-example@local'
    mine.mkdir(parents=True)
    other.mkdir(parents=True)
    (mine/'metadata.json').write_text('installed')
    (other/'metadata.json').write_text('keep')
    env=os.environ.copy()
    env['XDG_DATA_HOME']=str(data)
    env['PATH']='/usr/bin:/bin'
    res=subprocess.run(['bash',str(ROOT/'remove-gnome-panel.sh'),'--quiet'],env=env,
                       text=True,capture_output=True,timeout=10)
    assert res.returncode == 0, res.stderr
    assert not mine.exists()
    assert (other/'metadata.json').read_text() == 'keep'


def test_shell_syntax():
    for file in ('install.sh','update.sh','uninstall.sh','install-gui.sh','remove-gnome-panel.sh'):
        result=subprocess.run(['bash','-n',str(ROOT/file)],capture_output=True,text=True)
        assert result.returncode == 0, (file,result.stderr)
