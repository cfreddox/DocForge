"""Regression coverage for DocForge 1.3's frameless liquid petals."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from docforge.appearance import DEFAULTS, sanitize_settings
from docforge.petals import (BASE_H, BASE_W, Action, actions_for, hit_test,
                              petal_centers, render_zone, spring_step)


def test_actions_only_reachable_valid_destinations(tmp_path):
    md = tmp_path / "пример.md"
    md.write_text("# Test", encoding="utf-8")
    word = tmp_path / "report.docx"
    word.write_bytes(b"fake document")
    names = [a.key for a in actions_for([md])]
    assert "pdf" in names and "docx" in names and "md" not in names
    names2 = [a.key for a in actions_for([word])]
    assert "md" in names2 and "pdf" in names2 and "docx" not in names2
    assert all(a.key in names and a.operation == "convert" for a in actions_for([md]))
    both = [a.key for a in actions_for([md, word])]
    assert "pdf" in both
    assert "md" not in both
    assert actions_for([]) == []


def test_pdf_petals_offer_contextual_operations(tmp_path):
    pdf = tmp_path / "input.pdf"
    pdf.touch()
    names = [a.key for a in actions_for([pdf])]
    assert "split" in names and "compress" in names
    assert "merge" not in names
    names2 = [a.key for a in actions_for([pdf, pdf])]
    assert "merge" in names2
    assert len(names2) <= 8


def test_hover_zone_hit_test_selects_one_petal():
    for n in (3, 5, 8):
        centers = petal_centers(n, BASE_W, BASE_H)
        for i, (x,y,a) in enumerate(centers):
            assert hit_test(x,y,n,BASE_W,BASE_H) == i
        assert hit_test(BASE_W/2,BASE_H/2,n,BASE_W,BASE_H) is None
    assert hit_test(999,999,8,BASE_W,BASE_H) is None
    assert hit_test(0,0,0,BASE_W,BASE_H) is None


def test_hover_spring_overshoots_then_settles():
    value, velocity = 1.0, 0.0
    seen = []
    for _ in range(70):
        value, velocity = spring_step(value,velocity,1.09)
        seen.append(value)
    assert max(seen) > 1.09, "Expected a subtle overshoot"
    assert abs(seen[-1] - 1.09) < 0.005
    for _ in range(70):
        value, velocity = spring_step(value,velocity,1.0)
    assert abs(value - 1.0) < 0.005


def test_appearance_settings_validate_new_options():
    assert DEFAULTS["zone_style"] == "clear"
    data = sanitize_settings({"zone_style":"clear", "petal_animation": False, "bounce": 0.4})
    assert data["zone_style"] == "clear" and data["petal_animation"] is False
    assert data["bounce"] == .4
    bad = sanitize_settings({"zone_style":"bad", "petal_animation":"no", "bounce": 5000})
    assert bad["zone_style"] == DEFAULTS["zone_style"]
    assert bad["petal_animation"] is True
    assert bad["bounce"] == DEFAULTS["bounce"]


def test_render_transparent_frameless_zone(tmp_path):
    image = render_zone(256,240,style="fuzzy",accent="#FF922B")
    assert image.mode == "RGBA"
    assert image.getpixel((0,0))[3] == 0
    assert image.getpixel((128,120))[3] > 0
    targets=tuple([Action(key,key) for key in ("pdf","md","docx","png")])
    expanded = render_zone(BASE_W,BASE_H,style="fuzzy",accent="#FF922B",
                           actions=targets,progress=1.0,magnifications=(1,1.09,1,1),selected=1)
    assert expanded.getpixel((0,0))[3] == 0
    assert expanded.getbbox() is not None
    expanded.save(tmp_path / "petals.png")


def test_click_and_drop_route_to_petal_under_virtual_display(tmp_path):
    if not __import__("shutil").which("xvfb-run"):
        pytest.skip("No virtual display")
    script = r'''
from pathlib import Path
from types import SimpleNamespace
from docforge.gui import AppHost, DropZone, RootClass, select_appearance, setup_style
from docforge.appearance import load_settings
from docforge.petals import petal_centers
root=RootClass(); root.withdraw();select_appearance(load_settings()); setup_style(root)
host=AppHost(root);zone=DropZone(host)
p=Path('example.md')
zone._show_petals([p])
root.update()
assert zone._expanded and len(zone._actions)>=2
ix = next(i for i,a in enumerate(zone._actions) if a.key=='pdf')
pt=petal_centers(len(zone._actions),zone.width,zone.height,
  min(zone.width/720,zone.height/620))[ix]
seen=[]
zone._run_action=lambda action: seen.append(action.target)
event=SimpleNamespace(x_root=zone.winfo_rootx()+round(pt[0]),y_root=zone.winfo_rooty()+round(pt[1]))
zone._drop_or_choose([p],event)
assert seen == ['pdf'], seen
assert zone._borderless or not zone.overrideredirect()
zone._close()
'''
    env=os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    run=subprocess.run(["xvfb-run","-a",sys.executable,"-c",script],
                       capture_output=True,text=True,timeout=25,env=env)
    assert run.returncode == 0, run.stderr
