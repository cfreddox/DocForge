"""Compact, isotropic radial layout and time-based spring animation.

The surface is deliberately small and its rectangle never changes during DnD.
This prevents Wayland/X11 from releasing a file drag when petals appear.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians, sin

DESIGN_W, DESIGN_H = 250, 230
IDLE_W, IDLE_H = 92, 90
CENTER_W, CENTER_H = 85, 83
PETAL_W, PETAL_H = 72, 42


@dataclass(frozen=True)
class Petal:
    x: float
    y: float
    angle: float


def draw_scale(width: int, height: int) -> float:
    return max(.15, min(width / DESIGN_W, height / DESIGN_H))


def positions(count: int, width: int = DESIGN_W, height: int = DESIGN_H) -> list[Petal]:
    """A symmetrical flower around the exact visual center of the window."""
    if count < 1:
        return []
    scale = draw_scale(width, height)
    cx, cy = width / 2, height / 2
    rx, ry = 79 * scale, 72 * scale
    return [Petal(cx + cos(radians(a)) * rx,
                  cy + sin(radians(a)) * ry, a)
            for a in (-90 + 360*i/count for i in range(count))]


def petal_at(x: float, y: float, count: int, width: int, height: int,
             sizes: list[float] | None = None) -> int | None:
    """Return nearest painted petal, never select the central drop capsule."""
    scale = draw_scale(width, height)
    if abs(x-width/2) < CENTER_W*scale*.48 and abs(y-height/2) < CENTER_H*scale*.48:
        return None
    near: list[tuple[float,int]] = []
    for i, p in enumerate(positions(count, width, height)):
        th = radians(p.angle)
        dx, dy = x-p.x, y-p.y
        along = dx*cos(th)+dy*sin(th)
        across = -dx*sin(th)+dy*cos(th)
        zoom = sizes[i] if sizes and i < len(sizes) else 1.0
        metric = (along / (PETAL_W*scale*zoom*.49))**2 + (across/(PETAL_H*scale*zoom*.49))**2
        if metric < 1.0:
            near.append((metric,i))
    return min(near)[1] if near else None


def spring(value: float, velocity: float, target: float,
           bounce: float = 1.0) -> tuple[float, float]:
    """Stable damped spring at roughly 60 FPS, with a subtle overshoot."""
    if bounce <= 0:
        return value + (target-value)*.35, 0.0
    stiffness = .20 + min(bounce, 1.6)*.055
    velocity = (velocity + (target-value)*stiffness)*.74
    value += velocity
    if abs(value-target) < .0005 and abs(velocity) < .0005:
        return target, 0.0
    return value, velocity


def size_for(mode: str, available_width: int, available_height: int,
             expanded: bool = False) -> tuple[int, int]:
    """Whole-window scale, not a second scale of its child graphics."""
    ratios = {'compact': .82, 'standard': 1., 'large': 1.12}
    factor = ratios.get(mode, 1.)
    base_w, base_h = (DESIGN_W, DESIGN_H) if expanded else (IDLE_W, IDLE_H)
    limit = min((available_width-32)/(DESIGN_W*factor),
                (available_height-32)/(DESIGN_H*factor), 1.0)
    # The available-space cap is shared by BOTH states to ensure identical sizes.
    final = factor*max(.36,limit)
    return round(base_w*final), round(base_h*final)


# Spring animation profile. Times refer to wall-clock milliseconds, not frames.
REVEAL_MS = 450
STAGGER_MS = 25


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _smoothstep(value: float) -> float:
    t = _clamp01(value)
    return t * t * (3.0 - 2.0 * t)


@dataclass
class RevealTimeline:
    """Reversible, monotonic 0..1 expansion driven by elapsed real time.

    Reversal is continuous at arbitrary progress and takes proportionally less
    time, e.g. reverting at 50% takes 225 ms of a 450 ms full animation.
    """

    duration_ms: int = REVEAL_MS
    start: float = 0.0
    target: float = 0.0
    started_at: float = 0.0

    def at(self, now: float) -> float:
        distance = abs(self.target - self.start)
        if distance < 1e-8:
            return self.target
        duration = self.duration_ms * distance / 1000.0
        elapsed = max(0.0, now - self.started_at)
        if elapsed >= duration - 1e-9:
            return self.target
        # Keep the shared timeline linear: each petal applies its own easing
        # and exact 25 ms stagger in REAL time, independent of frame pacing.
        fraction = elapsed / duration
        return self.start + (self.target - self.start) * fraction

    def move_to(self, target: float, now: float) -> float:
        current = self.at(now)
        self.start = current
        self.target = _clamp01(target)
        self.started_at = now
        return current

    def finished(self, now: float) -> bool:
        return abs(self.at(now) - self.target) < 1e-8

    def retime(self, duration_ms: int, now: float) -> None:
        """Apply a new duration without jumping to a new animation position."""
        current = self.at(now)
        self.start = current
        self.started_at = now
        self.duration_ms = duration_ms


def petal_reveal(progress: float, index: int, count: int,
                 duration_ms: int = REVEAL_MS, bounce: float = .35,
                 style: str = "spring") -> float:
    """One petal's relative position for a complete 450-ms flower transition.

    Petals are staggered by 25 ms but all reach their final locations at the
    requested deadline. Spring style can overshoot position by a few percent;
    35% bounce is a user-control intensity, NOT 35% overshoot of distance.
    """
    if count <= 0 or index < 0 or index >= count:
        return 0.0
    duration_ms = max(1, int(duration_ms))
    delay = min(index * STAGGER_MS, max(0, duration_ms - 60))
    local = _clamp01((progress * duration_ms - delay) / (duration_ms - delay))
    if style == "soft" or bounce <= 0:
        return _smoothstep(local)
    # A quintic curve provides zero velocity at both ends. A small positive
    # pulse near the end creates a spring-like travel overshoot; unlike classic
    # ease-out-back it does NOT start with a sudden high initial velocity.
    if style == "spring":
        smooth = local**3 * (10.0 + local * (-15.0 + 6.0 * local))
        pulse = 12.0 * min(1.6, max(0.0, bounce)) * local**4 * (1.0-local)**2
        return smooth + pulse
    return 1.0 - (1.0 - local)**3


def spring_step_dt(value: float, velocity: float, target: float,
                   dt_seconds: float, bounce: float = .35) -> tuple[float, float]:
    """Damped analytic spring. Independent of the monitor refresh rate.

    `velocity` is in units/second. An analytic integration step avoids FPS-
    specific spring constants and remains stable after timer stalls.
    """
    from math import exp, sqrt

    dt = max(0.0, min(0.5, dt_seconds))
    if dt == 0.0:
        return value, velocity
    omega = 32.0
    damping = max(.25, min(1.0, 1.0 - .9 * max(0.0, bounce)))
    displacement = value - target
    if damping >= .999999:
        blend = velocity + omega * displacement
        decay = exp(-omega * dt)
        new_value = target + (displacement + blend * dt) * decay
        new_velocity = (velocity - omega * blend * dt) * decay
    else:
        from math import cos as _cos, sin as _sin
        natural = omega * sqrt(1.0 - damping * damping)
        phase = natural * dt
        cosine, sine = _cos(phase), _sin(phase)
        decay = exp(-damping * omega * dt)
        new_value = target + decay * (
            displacement * cosine + (velocity + damping * omega * displacement) / natural * sine
        )
        new_velocity = decay * (
            velocity * cosine - (damping * omega * velocity + omega * omega * displacement) / natural * sine
        )
    if abs(new_value-target) < .00005 and abs(new_velocity) < .001:
        return target, 0.0
    return new_value, new_velocity


def startup_reveal(elapsed_seconds: float, duration_ms: int = 250) -> tuple[float, float]:
    """Frameless glass capsule fades in at 94% size before reaching 100%."""
    fraction = _smoothstep(elapsed_seconds * 1000.0 / max(1, duration_ms))
    return fraction, .94 + .06 * fraction
