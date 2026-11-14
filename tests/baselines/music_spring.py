"""Frozen pre-migration Python oracle; tests/benchmarks only. GPL-3.0-only."""
import math

class MusicSpring:
    """Beat impulses plus a softly driven spring, with visible overshoot.

    The fast/slow envelope difference detects musical attacks. An adaptive peak
    keeps quieter tracks lively; a noise gate prevents movement during silence.
    Physics uses small time steps so motion is stable across rendering rates.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.position = 0.0
        self.velocity = 0.0
        self._fast = 0.0
        self._slow = 0.0
        self._reference = 0.08
        self._cooldown = 0.0

    def step(self, peak: float, dt: float) -> float:
        if not math.isfinite(dt) or dt <= 0:
            return self.position
        dt = min(dt, 0.1)
        peak = max(0.0, min(1.0, peak)) if math.isfinite(peak) else 0.0
        if peak < 0.003:
            peak = 0.0
        self._reference = max(0.08, peak, self._reference * math.exp(-dt / 2.0))
        level = min(1.0, peak / self._reference)
        self._fast += (level - self._fast) * (1.0 - math.exp(-dt / 0.025))
        self._slow += (level - self._slow) * (1.0 - math.exp(-dt / 0.22))
        self._cooldown = max(0.0, self._cooldown - dt)
        attack = self._fast - self._slow
        if peak and attack > 0.075 and self._cooldown <= 0.0:
            self.velocity -= 4.0 + min(1.0, attack * 3.0) * 6.0
            self._cooldown = 0.18
        target = -0.32 * self._fast
        steps = max(1, math.ceil(dt * 240))
        h = dt / steps
        for _ in range(steps):
            # omega=15 rad/s, damping ratio=0.23: a springy ~0.43 s cycle.
            self.velocity += (-225.0 * (self.position - target) - 6.9 * self.velocity) * h
            self.position += self.velocity * h
        self.position = max(-1.6, min(0.9, self.position))
        if peak == 0 and abs(self.position) < 0.001 and abs(self.velocity) < 0.01:
            self.position = self.velocity = 0.0
        return self.position
