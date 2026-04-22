import ctypes
import math
import random
import time
from collections import deque

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QEasingCurve,
    pyqtSignal,
    QTimer,
)
from PyQt6.QtGui import (
    QPainter,
    QColor,
    QRadialGradient,
    QLinearGradient,
    QPen,
    QPainterPath,
    QTransform,
)

# ── Palette ──────────────────────────────────────────────────────────────────
PINK_HOT   = QColor(236,  72, 153)
PINK_SOFT  = QColor(244, 114, 182)
ROSE       = QColor(251, 113, 133)
RED        = QColor(239,  68,  68)
VIOLET     = QColor(167, 139, 250)
BLUE       = QColor( 96, 165, 250)
MINT       = QColor( 52, 211, 153)
AMBER      = QColor(251, 191,  36)
WHITE_HOT  = QColor(255, 255, 255)

# Pointing-mode body colors — cool cyan → indigo so mode is unmistakable
POINT_BODY_START = QColor(125, 211, 252)   # sky-300
POINT_BODY_MID   = QColor( 59, 130, 246)   # blue-500
POINT_BODY_END   = QColor( 79,  70, 229)   # indigo-600

_STATE_RINGS = {
    "idle":      (VIOLET, BLUE),
    "thinking":  (VIOLET, PINK_HOT),
    "listening": (PINK_HOT, ROSE),
    "speaking":  (MINT, BLUE),
    "error":     (RED, AMBER),
}

SIZE = 110
FOLLOW_OFFSET_X = 28
FOLLOW_OFFSET_Y = 24
SPRING = 0.14
BOB_Y_AMP = 4.5
BOB_X_AMP = 2.8
BOB_Y_FREQ = 2.6
BOB_X_FREQ = 1.9
IDLE_BORED_AFTER_S = 3.0
SPARKLE_COUNT = 3
SPARKLE_COUNT_BURST = 8   # extra sparkles during mode flash

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020


class GhostCursor(QWidget):
    arrived = pyqtSignal()

    MODE_FOLLOW = "follow"
    MODE_POINTING = "pointing"

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(SIZE, SIZE)

        self._t0 = time.time()
        self._mode = self.MODE_FOLLOW
        self._state = "idle"

        # Where the user's real cursor is (always tracked, even in pointing mode)
        self._real_user_x = 0.0
        self._real_user_y = 0.0
        self._last_move_t = time.time()

        # Where the ghost wants to be (user cursor + offset, in follow mode)
        self._target_x = 0.0
        self._target_y = 0.0
        # Where the ghost currently is (painted position, after spring+bob)
        self._smoothed_x = 0.0
        self._smoothed_y = 0.0

        self._sparkles = [_Sparkle() for _ in range(SPARKLE_COUNT)]
        self._burst_sparkles: list[_Sparkle] = []

        self._mode_change_t = 0.0

        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(16)

    # ── Follow mode ──────────────────────────────────────────────────────────

    def follow(self, x: int, y: int):
        # Detect if the user actually moved — reset boredom clock only then
        moved = abs(x - self._real_user_x) > 0.5 or abs(y - self._real_user_y) > 0.5
        self._real_user_x = float(x)
        self._real_user_y = float(y)
        self._target_x = float(x + FOLLOW_OFFSET_X)
        self._target_y = float(y + FOLLOW_OFFSET_Y)
        if moved:
            self._last_move_t = time.time()
        if not self.isVisible():
            self._smoothed_x = self._target_x
            self._smoothed_y = self._target_y
            self._place(self._smoothed_x, self._smoothed_y)
            self.show()

    def set_state(self, state: str):
        if state in _STATE_RINGS and state != self._state:
            self._state = state

    # ── Guidance mode ────────────────────────────────────────────────────────

    def show_at(self, x: int, y: int):
        self._mode_change_t = time.time()
        self._mode = self.MODE_POINTING
        self._emit_burst()
        self._place(x, y)
        self._smoothed_x, self._smoothed_y = float(x), float(y)
        if not self.isVisible():
            self.show()

    def animate_to(self, x: int, y: int, ms: int = 900):
        """Start every pointing animation from the user's REAL cursor position,
        regardless of where the ghost was. Gives a clear 'from here to there' sweep
        on every step."""
        was_following = self._mode == self.MODE_FOLLOW
        self._mode = self.MODE_POINTING
        if was_following:
            self._mode_change_t = time.time()
            self._emit_burst()

        # Snap to user's cursor (with offset) as the starting point
        start_x = self._real_user_x + FOLLOW_OFFSET_X
        start_y = self._real_user_y + FOLLOW_OFFSET_Y
        start_x, start_y = self._clamp_to_screens(start_x, start_y)
        self._place(start_x, start_y)
        self._smoothed_x = start_x
        self._smoothed_y = start_y

        if not self.isVisible():
            self.show()
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

        end_x, end_y = self._clamp_to_screens(float(x), float(y))
        start_top = QPoint(int(start_x - SIZE / 2), int(start_y - SIZE / 2))
        end_top   = QPoint(int(end_x   - SIZE / 2), int(end_y   - SIZE / 2))
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(ms)
        anim.setStartValue(start_top)
        anim.setEndValue(end_top)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        def _on_done():
            self._smoothed_x, self._smoothed_y = end_x, end_y
            self.arrived.emit()

        anim.finished.connect(_on_done)
        self._anim = anim
        anim.start()

    def release(self):
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        if self._mode != self.MODE_FOLLOW:
            self._mode_change_t = time.time()
            self._emit_burst()
        self._mode = self.MODE_FOLLOW

    # ── Multi-monitor clamp ──────────────────────────────────────────────────

    def _clamp_to_screens(self, cx: float, cy: float) -> tuple[float, float]:
        """Keep the widget box inside the virtual desktop (union of all monitors)."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return cx, cy
        virt = screen.virtualGeometry()
        half = SIZE / 2
        cx = max(virt.left() + half, min(cx, virt.right() - half))
        cy = max(virt.top() + half, min(cy, virt.bottom() - half))
        return cx, cy

    # ── Tick ─────────────────────────────────────────────────────────────────

    def _tick(self):
        now = time.time()
        if self._mode == self.MODE_FOLLOW:
            self._smoothed_x += (self._target_x - self._smoothed_x) * SPRING
            self._smoothed_y += (self._target_y - self._smoothed_y) * SPRING
            elapsed = now - self._t0
            bob_y = BOB_Y_AMP * math.sin(elapsed * BOB_Y_FREQ)
            bob_x = BOB_X_AMP * math.sin(elapsed * BOB_X_FREQ + 0.7)
            wob_y = 1.3 * math.sin(elapsed * 5.5)

            # Idle-long: if user hasn't moved for a while, add lazy floating
            idle_s = now - self._last_move_t
            if idle_s > IDLE_BORED_AFTER_S:
                f = min(1.0, (idle_s - IDLE_BORED_AFTER_S) / 2.0)
                bob_x += f * 4.0 * math.sin(elapsed * 0.8)
                bob_y += f * 3.0 * math.sin(elapsed * 1.1 + 1.3)

            px = self._smoothed_x + bob_x
            py = self._smoothed_y + bob_y + wob_y
            px, py = self._clamp_to_screens(px, py)
            self._place(px, py)

        # Sparkles always tick
        for s in self._sparkles:
            s.step()
        self._burst_sparkles = [s for s in self._burst_sparkles if not s.dead]
        for s in self._burst_sparkles:
            s.step()

        self.update()

    def _place(self, cx: float, cy: float):
        self.move(int(cx - SIZE / 2), int(cy - SIZE / 2))

    def _emit_burst(self):
        """Spawn a quick burst of sparkles when the mode changes."""
        self._burst_sparkles.extend(_Sparkle(burst=True) for _ in range(SPARKLE_COUNT_BURST))

    # ── Paint ────────────────────────────────────────────────────────────────

    def _swoosh_path(self, cx: float, cy: float) -> QPainterPath:
        path = QPainterPath()
        tip  = QPointF(cx, cy)
        tail = QPointF(cx - 28, cy - 18)
        path.moveTo(tail)
        path.cubicTo(QPointF(cx - 18, cy + 6), QPointF(cx - 4, cy + 10), tip)
        path.cubicTo(QPointF(cx - 6, cy - 2), QPointF(cx - 18, cy - 10), tail)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2
        now = time.time()
        elapsed = now - self._t0

        ring_a, ring_b = _STATE_RINGS.get(self._state, _STATE_RINGS["idle"])
        is_pointing = self._mode == self.MODE_POINTING
        is_thinking = self._state == "thinking"

        # Sparkles behind everything
        for s in self._sparkles:
            s.paint(p, cx, cy)
        for s in self._burst_sparkles:
            s.paint(p, cx, cy)

        # Sonar rings
        ring_speed = 1.1 if is_pointing or is_thinking else 0.6
        ring_max = 36 if is_pointing or is_thinking else 22
        ring_base_r = 16 if is_pointing or is_thinking else 10
        ring_alpha_peak = 190 if is_pointing or is_thinking else 110
        for phase_offset, ring_color in ((0.0, ring_a), (0.5, ring_b)):
            phase = ((elapsed * ring_speed) + phase_offset) % 1.0
            r = ring_base_r + ring_max * phase
            alpha = int(ring_alpha_peak * (1.0 - phase) ** 1.4)
            c = QColor(ring_color); c.setAlpha(alpha)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Halo — color depends on mode
        if is_pointing:
            halo_a = QColor(POINT_BODY_MID);   halo_a.setAlpha(140)
            halo_b = QColor(POINT_BODY_START); halo_b.setAlpha(70)
        else:
            halo_a = QColor(PINK_HOT); halo_a.setAlpha(130 if is_thinking else 80)
            halo_b = QColor(ROSE);     halo_b.setAlpha(70 if is_thinking else 45)
        halo_edge = QColor(0, 0, 0, 0)
        halo = QRadialGradient(cx - 4, cy - 2, 42)
        halo.setColorAt(0.0, halo_a)
        halo.setColorAt(0.55, halo_b)
        halo.setColorAt(1.0, halo_edge)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 4, cy - 2), 42, 42)

        # Body colors
        if is_thinking:
            hue = int((elapsed * 140) % 360)
            body_start = QColor.fromHsl(hue, 220, 200)
            body_mid   = QColor.fromHsl((hue + 25) % 360, 240, 170)
            body_end   = QColor.fromHsl((hue + 50) % 360, 240, 130)
            rim_start  = QColor(255, 255, 255, 160)
            rim_end    = QColor.fromHsl((hue + 180) % 360, 255, 80, 200)
        elif is_pointing:
            body_start = POINT_BODY_START
            body_mid   = POINT_BODY_MID
            body_end   = POINT_BODY_END
            rim_start  = QColor(210, 235, 255, 180)
            rim_end    = QColor( 20,  50, 140, 200)
        else:
            body_start = PINK_SOFT
            body_mid   = PINK_HOT
            body_end   = RED
            rim_start  = QColor(255, 200, 220, 160)
            rim_end    = QColor(180,  20,  60, 200)

        # Rotation — thinking spins, pointing leans slightly forward, follow is steady
        rotation = 0.0
        if is_thinking:
            rotation = (elapsed * 180.0) % 360.0
        elif is_pointing:
            rotation = 8.0 * math.sin(elapsed * 2.1)  # gentle lean

        p.save()
        p.translate(cx, cy)
        p.rotate(rotation)
        p.translate(-cx, -cy)

        path = self._swoosh_path(cx, cy)
        body_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        body_grad.setColorAt(0.0, body_start)
        body_grad.setColorAt(0.55, body_mid)
        body_grad.setColorAt(1.0, body_end)
        p.setBrush(body_grad)

        rim_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        rim_grad.setColorAt(0.0, rim_start)
        rim_grad.setColorAt(1.0, rim_end)
        rim_pen = QPen(); rim_pen.setBrush(rim_grad); rim_pen.setWidthF(1.3)
        p.setPen(rim_pen)
        p.drawPath(path)

        # Highlight sliver
        hl = QPainterPath()
        hl.moveTo(cx - 22, cy - 14)
        hl.cubicTo(
            QPointF(cx - 14, cy - 8),
            QPointF(cx - 6, cy - 5),
            QPointF(cx - 2, cy - 2),
        )
        shimmer = 120 + int(70 * (math.sin(elapsed * 3.0) + 1) / 2)
        p.setPen(QPen(QColor(255, 255, 255, shimmer), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hl)

        p.restore()

        # Tip glow (unrotated, stays centered at tip for clear target read)
        tip_glow = QRadialGradient(cx, cy, 8)
        tip_glow.setColorAt(0.0, WHITE_HOT)
        tip_glow.setColorAt(0.5, QColor(255, 210, 220, 230))
        tip_edge = QColor(PINK_HOT); tip_edge.setAlpha(0)
        tip_glow.setColorAt(1.0, tip_edge)
        p.setBrush(tip_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)

        # Mode-change flash — brief white ring expanding from center
        flash_age = now - self._mode_change_t if self._mode_change_t > 0 else 1.0
        if 0.0 <= flash_age <= 0.45:
            t = flash_age / 0.45
            flash_r = 12 + 42 * t
            flash_alpha = int(220 * (1 - t))
            p.setPen(QPen(QColor(255, 255, 255, flash_alpha), 2.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), flash_r, flash_r)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass


class _Sparkle:
    """A tiny drifting particle that orbits the cursor tip.

    burst=True variant is used for mode-change flourishes — short-lived, faster,
    more numerous.
    """

    def __init__(self, burst: bool = False):
        self.burst = burst
        self.dead = False
        self.reset()

    def reset(self):
        if self.burst:
            self.life = random.uniform(0.35, 0.65)
            self.radius = random.uniform(2, 8)
            self.radial_vel = random.uniform(45, 80)
            self.angular_vel = random.uniform(-3.5, 3.5)
            self.size = random.uniform(1.6, 2.8)
            self.hue = random.choice([WHITE_HOT, PINK_SOFT, POINT_BODY_START])
        else:
            self.life = random.uniform(1.2, 2.6)
            self.radius = random.uniform(6, 26)
            self.radial_vel = random.uniform(8, 16)
            self.angular_vel = random.uniform(-0.8, 0.8)
            self.size = random.uniform(1.3, 2.4)
            self.hue = random.choice([PINK_SOFT, VIOLET, WHITE_HOT])
        self.age = 0.0 if self.burst else random.uniform(0.0, self.life)
        self.angle = random.uniform(0, math.tau)

    def step(self):
        self.age += 0.016
        if self.age >= self.life:
            if self.burst:
                self.dead = True
            else:
                self.reset()
                self.age = 0.0
        self.angle += self.angular_vel * 0.016
        self.radius += self.radial_vel * 0.016

    def paint(self, p: QPainter, cx: float, cy: float):
        if self.dead or self.age >= self.life:
            return
        t = self.age / self.life
        alpha_curve = 4 * t * (1 - t)
        x = cx + math.cos(self.angle) * self.radius
        y = cy + math.sin(self.angle) * self.radius
        c = QColor(self.hue); c.setAlpha(int(230 * alpha_curve))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        r = self.size * (0.6 + 0.4 * alpha_curve)
        p.drawEllipse(QPointF(x, y), r, r)
