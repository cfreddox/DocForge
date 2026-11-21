"""Regression suite for the 450 ms spring-style DocForge flower (1.5.1)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from docforge.appearance import DEFAULTS, config_file, load_settings, sanitize_settings, save_settings
from docforge.liquid_geometry import (
    REVEAL_MS, STAGGER_MS, RevealTimeline, petal_reveal, spring_step_dt, startup_reveal,
)


def test_requested_spring_profile_is_default():
    assert DEFAULTS['animation_style'] == 'spring'
    assert DEFAULTS['reveal_ms'] == 450
    assert DEFAULTS['bounce'] == .35
    assert DEFAULTS['hover_scale'] == .09
    assert REVEAL_MS == 450 and STAGGER_MS == 25


def test_reveal_finishes_at_450_ms_irrespective_of_frame_rate():
    for fps in (30, 60, 75, 120, 144):
        clock = RevealTimeline(duration_ms=450)
        clock.move_to(1.0, 20.0)
        measured = [clock.at(20.0 + index/fps) for index in range(1, round(fps*.45))]
        assert all(0 <= x <= 1 for x in measured)
        assert measured == sorted(measured)
        assert clock.at(20.0 + .45) == 1.0
        assert clock.finished(20.0 + .45)
        assert clock.at(20.0 + .60) == 1.0


def test_reversal_during_opening_never_snaps():
    timeline = RevealTimeline(duration_ms=450)
    timeline.move_to(1.0, 10.0)
    before = timeline.at(10.190)
    after = timeline.move_to(0.0, 10.190)
    assert after == pytest.approx(before, abs=1e-12)
    assert timeline.at(10.190) == pytest.approx(before, abs=1e-12)
    assert timeline.at(10.190 + .45 * before) == 0.0
    assert timeline.finished(10.190 + .45 * before)
    # Dragging a file back in while the flower is closing reverses cleanly.
    timeline.move_to(1.0, 10.220)
    reversed_value = timeline.at(10.220)
    assert 0 <= reversed_value <= before
    assert timeline.at(10.220 + .45 * (1.0-reversed_value)) == 1.0


def test_stagger_and_spring_overshoot_are_gentle():
    for count in (3, 5, 8):
        for i in range(count):
            assert petal_reveal(0.0, i, count) == 0.0
            assert petal_reveal(1.0, i, count) == 1.0
        assert petal_reveal(.43, 0, count) > petal_reveal(.43, count-1, count)
        if count > 1:
            assert petal_reveal(24/450, 1, count) == 0.0
            assert petal_reveal(26/450, 1, count) > 0.0
        readings = [petal_reveal(i/1000, 0, count) for i in range(1001)]
        assert 1.0 < max(readings) < 1.07  # visible but restrained spring recoil
        assert min(readings) >= 0.0
        soft = [petal_reveal(i/1000, 0, count, style='soft') for i in range(1001)]
        assert max(soft) == 1.0  # softness does not accidentally bounce


def test_hover_9_percent_same_across_30_60_120_fps():
    terminals = []
    for fps in (30, 60, 120):
        position, velocity = 1.0, 0.0
        peak = position
        for index in range(fps):
            position, velocity = spring_step_dt(position, velocity, 1.09, 1.0/fps, .35)
            peak = max(peak, position)
        assert 1.09 < peak < 1.11
        assert position == pytest.approx(1.09, abs=.001)
        terminals.append(position)
    assert max(terminals)-min(terminals) < .0001


def test_spring_returns_to_rest_and_handles_frame_stalls():
    x, speed = 1.0, 0.0
    for _ in range(20):
        x, speed = spring_step_dt(x, speed, 1.09, .016, .35)
    for _ in range(25):
        x, speed = spring_step_dt(x, speed, 1.0, .016, .35)
    assert x == pytest.approx(1.0, abs=.002)
    x2, v2 = spring_step_dt(x, speed, 1.0, .25, .35)
    assert math.isfinite(x2) and math.isfinite(v2)
    assert abs(x2-1.0) <= abs(x-1.0)


def test_animation_prefs_persist_and_old_configs_migrate(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    config = config_file()
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        'theme': 'liquid_dark', 'accent': 'mint', 'bounce': 1.0,
        'hover_scale': .10, 'petal_animation': True,
        'window_behavior_version': 2, 'liquid_renderer_version': 1,
    }), encoding='utf-8')
    migrated = load_settings()
    assert migrated['theme'] == 'liquid_dark'
    assert migrated['accent'] == 'mint'
    assert migrated['bounce'] == .35
    assert migrated['hover_scale'] == .09
    assert migrated['reveal_ms'] == 450
    save_settings({**migrated, 'reveal_ms': 575, 'hover_scale': .14, 'animation_style': 'soft'})
    assert load_settings()['reveal_ms'] == 575
    assert load_settings()['hover_scale'] == .14
    assert load_settings()['animation_style'] == 'soft'
    assert 'animation_profile_version' in config.read_text(encoding='utf-8')
    invalid = sanitize_settings({'reveal_ms': 12, 'animation_style': 'unknown'})
    assert invalid['reveal_ms'] == 450
    assert invalid['animation_style'] == 'spring'


def test_qt_code_has_single_source_of_position_for_paint_and_drop():
    script = (Path(__file__).parent.parent / 'docforge' / 'liquid_qt.py').read_text()
    assert script.count('self._petal_geometry(') >= 2
    assert '_index_at(event.position())' in script
    assert 'if chosen is None and self._hover is not None' not in script
    assert 'time.monotonic()' in script
    assert 'QTimer.singleShot(340' in script
    assert 'self._drag_sequence' in script
    assert "self.config['reveal_ms']" in script


def test_startup_capsule_fade_is_smooth_and_250_ms():
    a0, z0 = startup_reveal(0)
    amid, zmid = startup_reveal(.125)
    afinal, zfinal = startup_reveal(.25)
    assert (a0, z0) == (0, .94)
    assert 0 < amid < 1 and .94 < zmid < 1
    assert (afinal, zfinal) == (1.0, 1.0)
    assert startup_reveal(.70) == (1.0, 1.0)


def test_live_duration_setting_does_not_jolt_in_progress_animation():
    clock = RevealTimeline(duration_ms=450)
    clock.move_to(1., 100.)
    before = clock.at(100.2)
    clock.retime(700, 100.2)
    assert clock.at(100.2) == pytest.approx(before)
    assert clock.at(100.2 + .7 * (1-before)) == 1.0
