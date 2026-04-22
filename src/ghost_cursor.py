import ctypes
import math
import random
import time

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
)

# ── Palette ──────────────────────────────────────────────────────────────────
PINK_HOT    = QColor(236,  72, 153)
PINK_SOFT   = QColor(244, 114, 182)
ROSE        = QColor(251, 113, 133)
FUCHSIA     = QColor(217,  70, 239)
RED         = QColor(239,  68,  68)
VIOLET      = QColor(167, 139, 250)
BLUE        = QColor( 96, 165, 250)
MINT        = QColor( 52, 211, 153)
GOLD        = QColor(253, 224,  71)
AMBER       = QColor(251, 191,  36)
WHITE_HOT   = QColor(255, 255, 255)

POINT_BODY_START = QColor(125, 211, 252)
POINT_BODY_MID   = QColor( 59, 130, 246)
POINT_BODY_END   = QColor( 79,  70, 229)

# Curated warm palette for listening state (cycles through these — no rainbow)
LISTEN_PALETTE = [PINK_HOT, FUCHSIA, PINK_SOFT, ROSE]

_STATE_RINGS = {
    "idle":      (VIOLET, BLUE),
    "thinking":  (AMBER, GOLD),
    "listening": (PINK_HOT, ROSE),
    "speaking":  (MINT, BLUE),
    "error":     (RED, AMBER),
}

SIZE = 120
FOLLOW_OFFSET_X = 30
FOLLOW_OFFSET_Y = 26
SPRING = 0.14

BOB_Y_AMP = 9.0
BOB_X_AMP = 6.0
BOB_Y_FREQ = 2.9
BOB_X_FREQ = 2.0
WOB_AMP = 2.6
WOB_FREQ = 6.0

IDLE_BORED_AFTER_S = 0.9

SPARKLE_COUNT = 4
SPARKLE_COUNT_BURST = 10

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

        self._real_user_x = 0.0
        self._real_user_y = 0.0
        self._last_move_t = time.time()

        self._target_x = 0.0
        self._target_y = 0.0
        self._smoothed_x = 0.0
        self._smoothed_y = 0.0

        self._sparkles = [_Sparkle() for _ in range(SPARKLE_COUNT)]
        self._burst_sparkles: list[_Sparkle] = []
        self._mode_change_t = 0.0

        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(16)

    # ── Public API ───────────────────────────────────────────────────────────

    def follow(self, x: int, y: int):
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

    def show_at(self, x: int, y: int):
        self._mode_change_t = time.time()
        self._mode = self.MODE_POINTING
        self._emit_burst()
        self._place(x, y)
        self._smoothed_x, self._smoothed_y = float(x), float(y)
        if not self.isVisible():
            self.show()

    def animate_to(self, x: int, y: int, ms: int = 950):
        was_following = self._mode == self.MODE_FOLLOW
        self._mode = self.MODE_POINTING
        if was_following:
            self._mode_change_t = time.time()
            self._emit_burst()

        start_x = self._real_user_x + FOLLOW_OFFSET_X
        start_y = self._real_user_y + FOLLOW_OFFSET_Y
        start_x, start_y = self._clamp_to_screens(start_x, start_y)
        self._place(start_x, start_y)
        self._smoothed_x, self._smoothed_y = start_x, start_y

        if not self.isVisible():
            self.show()
        self._cancel_anim()

        end_x, end_y = self._clamp_to_screens(float(x), float(y))
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(ms)
        anim.setStartValue(QPoint(int(start_x - SIZE / 2), int(start_y - SIZE / 2)))
        anim.setEndValue(QPoint(int(end_x - SIZE / 2), int(end_y - SIZE / 2)))
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)

        def _on_done():
            self._smoothed_x, self._smoothed_y = end_x, end_y
            self.arrived.emit()

        anim.finished.connect(_on_done)
        self._anim = anim
        anim.start()

    def release(self):
        self._cancel_anim()
        if self._mode != self.MODE_FOLLOW:
            self._mode_change_t = time.time()
            self._emit_burst()
        self._mode = self.MODE_FOLLOW

    def _cancel_anim(self):
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None

    # ── Multi-monitor clamp ──────────────────────────────────────────────────

    def _clamp_to_screens(self, cx: float, cy: float) -> tuple[float, float]:
        probe = QPoint(int(self._real_user_x), int(self._real_user_y))
        screen = QApplication.screenAt(probe) or QApplication.primaryScreen()
        if screen is None:
            return cx, cy
        geom = screen.availableGeometry()
        half = SIZE / 2
        cx = max(geom.left() + half, min(cx, geom.right() - half))
        cy = max(geom.top() + half, min(cy, geom.bottom() - half))
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
            wob_y = WOB_AMP * math.sin(elapsed * WOB_FREQ)

            idle_s = now - self._last_move_t
            if idle_s > IDLE_BORED_AFTER_S:
                f = min(1.0, (idle_s - IDLE_BORED_AFTER_S) / 1.2)
                bob_x += f * 5.0 * math.sin(elapsed * 0.9)
                bob_y += f * 4.0 * math.sin(elapsed * 1.2 + 1.3)

            px = self._smoothed_x + bob_x
            py = self._smoothed_y + bob_y + wob_y
            px, py = self._clamp_to_screens(px, py)
            self._place(px, py)

        for s in self._sparkles:
            s.step()
        self._burst_sparkles = [s for s in self._burst_sparkles if not s.dead]
        for s in self._burst_sparkles:
            s.step()

        if int(now * 2) % 4 == 0:
            self.raise_()

        self.update()

    def _place(self, cx: float, cy: float):
        self.move(int(cx - SIZE / 2), int(cy - SIZE / 2))

    def _emit_burst(self):
        self._burst_sparkles.extend(_Sparkle(burst=True) for _ in range(SPARKLE_COUNT_BURST))

    # ── Paint helpers ────────────────────────────────────────────────────────

    def _swoosh_path(self, cx: float, cy: float) -> QPainterPath:
        path = QPainterPath()
        tip  = QPointF(cx, cy)
        tail = QPointF(cx - 30, cy - 20)
        path.moveTo(tail)
        path.cubicTo(QPointF(cx - 20, cy + 6), QPointF(cx - 4, cy + 12), tip)
        path.cubicTo(QPointF(cx - 6, cy - 2), QPointF(cx - 20, cy - 10), tail)
        path.closeSubpath()
        return path

    def _paint_ripples(self, p: QPainter, cx: int, cy: int, elapsed: float,
                       color: QColor, count: int = 4, speed: float = 0.85,
                       max_r: float = 38.0, base_r: float = 8.0,
                       peak_alpha: int = 180, width: float = 2.2):
        """Concentric expanding rings — reads as sound/voice pickup."""
        for i in range(count):
            phase = ((elapsed * speed) + i / count) % 1.0
            r = base_r + max_r * phase
            alpha = int(peak_alpha * (1.0 - phase) ** 1.3)
            c = QColor(color); c.setAlpha(alpha)
            p.setPen(QPen(c, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

    def _listen_color(self, elapsed: float) -> QColor:
        """Interpolate through LISTEN_PALETTE at ~1 step per 2.5s."""
        speed = 0.4  # palette cycles per second
        phase = (elapsed * speed) % len(LISTEN_PALETTE)
        idx = int(phase)
        t = phase - idx
        a = LISTEN_PALETTE[idx]
        b = LISTEN_PALETTE[(idx + 1) % len(LISTEN_PALETTE)]
        r = int(a.red()   * (1 - t) + b.red()   * t)
        g = int(a.green() * (1 - t) + b.green() * t)
        bl = int(a.blue() * (1 - t) + b.blue()  * t)
        return QColor(r, g, bl)

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2
        now = time.time()
        elapsed = now - self._t0

        is_pointing = self._mode == self.MODE_POINTING
        is_listening = self._state == "listening"
        is_thinking = self._state == "thinking"

        thinking_scale = 1.0 + (0.07 * math.sin(elapsed * 3.6)) if is_thinking else 1.0
        listen_scale = 1.0 + (0.05 * math.sin(elapsed * 2.4)) if (is_listening and not is_pointing) else 1.0

        for s in self._sparkles:
            s.paint(p, cx, cy)
        for s in self._burst_sparkles:
            s.paint(p, cx, cy)

        # ── Background rings / ripples ───────────────────────────────────────
        if is_listening and not is_pointing:
            # Full listening mode: voice-ripple rings emanating from tip.
            ripple_color = self._listen_color(elapsed)
            self._paint_ripples(p, cx, cy, elapsed, ripple_color,
                                count=4, speed=0.9, max_r=42, base_r=10,
                                peak_alpha=190, width=2.4)
        else:
            # Regular sonar pulse — toned way down in follow/idle
            ring_a, ring_b = _STATE_RINGS.get(self._state, _STATE_RINGS["idle"])
            if is_pointing:
                ring_speed, ring_max, ring_base, ring_peak = 1.3, 40, 18, 200
            elif is_thinking:
                ring_speed, ring_max, ring_base, ring_peak = 1.1, 34, 14, 160
            else:
                # Idle — SUBTLE. One gentle ring, quiet alpha.
                ring_speed, ring_max, ring_base, ring_peak = 0.42, 14, 8, 65
            for phase_offset, ring_color in ((0.0, ring_a), (0.5, ring_b)):
                phase = ((elapsed * ring_speed) + phase_offset) % 1.0
                r = ring_base + ring_max * phase
                alpha = int(ring_peak * (1.0 - phase) ** 1.4)
                c = QColor(ring_color); c.setAlpha(alpha)
                p.setPen(QPen(c, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r, r)

        # ── Halo ─────────────────────────────────────────────────────────────
        if is_pointing:
            halo_a = QColor(POINT_BODY_MID);   halo_a.setAlpha(150)
            halo_b = QColor(POINT_BODY_START); halo_b.setAlpha(75)
        elif is_thinking:
            halo_a = QColor(GOLD);  halo_a.setAlpha(140)
            halo_b = QColor(AMBER); halo_b.setAlpha(70)
        elif is_listening:
            lc = self._listen_color(elapsed)
            halo_a = QColor(lc); halo_a.setAlpha(140)
            halo_b = QColor(lc); halo_b.setAlpha(70)
        else:
            halo_a = QColor(PINK_HOT); halo_a.setAlpha(85)
            halo_b = QColor(ROSE);     halo_b.setAlpha(45)
        halo = QRadialGradient(cx - 4, cy - 2, 46)
        halo.setColorAt(0.0, halo_a)
        halo.setColorAt(0.55, halo_b)
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 4, cy - 2), 46, 46)

        # ── Body colors & transform ──────────────────────────────────────────
        rotation = 0.0
        if is_listening and not is_pointing:
            # Full listening: gentle nod (swoosh "listens intently"), no spin
            rotation = 14.0 * math.sin(elapsed * 1.9)
            body_color = self._listen_color(elapsed)
            body_start = _lighten(body_color, 0.3)
            body_mid   = body_color
            body_end   = _darken(body_color, 0.2)
            rim_start  = QColor(255, 255, 255, 160)
            rim_end    = _darken(body_color, 0.4); rim_end.setAlpha(200)
        elif is_pointing:
            body_start = POINT_BODY_START
            body_mid   = POINT_BODY_MID
            body_end   = POINT_BODY_END
            rim_start  = QColor(210, 235, 255, 180)
            rim_end    = QColor( 20,  50, 140, 200)
            rotation = 8.0 * math.sin(elapsed * 2.1)
        else:
            body_start = PINK_SOFT
            body_mid   = PINK_HOT
            body_end   = RED
            rim_start  = QColor(255, 200, 220, 160)
            rim_end    = QColor(180,  20,  60, 200)

        p.save()
        p.translate(cx, cy)
        scale = thinking_scale * listen_scale
        if scale != 1.0:
            p.scale(scale, scale)
        p.rotate(rotation)
        p.translate(-cx, -cy)

        path = self._swoosh_path(cx, cy)
        body_grad = QLinearGradient(cx - 30, cy - 20, cx, cy)
        body_grad.setColorAt(0.0, body_start)
        body_grad.setColorAt(0.55, body_mid)
        body_grad.setColorAt(1.0, body_end)
        p.setBrush(body_grad)

        rim_grad = QLinearGradient(cx - 30, cy - 20, cx, cy)
        rim_grad.setColorAt(0.0, rim_start)
        rim_grad.setColorAt(1.0, rim_end)
        rim_pen = QPen(); rim_pen.setBrush(rim_grad); rim_pen.setWidthF(1.4)
        p.setPen(rim_pen)
        p.drawPath(path)

        # Thinking golden shimmer
        if is_thinking:
            shimmer_progress = (elapsed * 1.8) % 1.0
            sg = QLinearGradient(cx - 30, cy - 20, cx, cy)
            clear = QColor(GOLD.red(), GOLD.green(), GOLD.blue(), 0)
            lit   = QColor(GOLD.red(), GOLD.green(), GOLD.blue(), 180)
            sg.setColorAt(max(0.0, shimmer_progress - 0.15), clear)
            sg.setColorAt(shimmer_progress, lit)
            sg.setColorAt(min(1.0, shimmer_progress + 0.15), clear)
            sh_pen = QPen(); sh_pen.setBrush(sg); sh_pen.setWidthF(2.2)
            p.setPen(sh_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        hl = QPainterPath()
        hl.moveTo(cx - 22, cy - 14)
        hl.cubicTo(
            QPointF(cx - 14, cy - 8),
            QPointF(cx - 6, cy - 5),
            QPointF(cx - 2, cy - 2),
        )
        shimmer_alpha = 130 + int(80 * (math.sin(elapsed * 3.0) + 1) / 2)
        p.setPen(QPen(QColor(255, 255, 255, shimmer_alpha), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hl)

        p.restore()

        # ── Tip glow (always at tip, unrotated) ──────────────────────────────
        tip_glow = QRadialGradient(cx, cy, 9)
        tip_glow.setColorAt(0.0, WHITE_HOT)
        tip_glow.setColorAt(0.5, QColor(255, 210, 220, 230))
        tip_edge = QColor(PINK_HOT); tip_edge.setAlpha(0)
        tip_glow.setColorAt(1.0, tip_edge)
        p.setBrush(tip_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 6, 6)

        # ── Mid-animation listening underscore ───────────────────────────────
        # If we're in pointing mode AND also listening, show a subtle pink
        # mini-ripple at the tip + a small mic dot below. Signals "I'm still
        # guiding AND I'm listening for your input" without hijacking the look.
        if is_pointing and is_listening:
            for i in range(2):
                phase = ((elapsed * 1.5) + i / 2) % 1.0
                r = 7 + 14 * phase
                a = int(160 * (1 - phase))
                c = QColor(PINK_HOT); c.setAlpha(a)
                p.setPen(QPen(c, 1.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(cx, cy), r, r)
            # Small pink mic bead tucked under the tip
            bead_y = cy + 14
            bead_glow = QRadialGradient(cx, bead_y, 6)
            bead_glow.setColorAt(0.0, QColor(PINK_HOT.red(), PINK_HOT.green(), PINK_HOT.blue(), 230))
            bead_glow.setColorAt(0.6, QColor(PINK_SOFT.red(), PINK_SOFT.green(), PINK_SOFT.blue(), 120))
            bead_glow.setColorAt(1.0, QColor(PINK_HOT.red(), PINK_HOT.green(), PINK_HOT.blue(), 0))
            p.setBrush(bead_glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, bead_y), 5, 5)

        # ── Mode-change flash ────────────────────────────────────────────────
        flash_age = now - self._mode_change_t if self._mode_change_t > 0 else 1.0
        if 0.0 <= flash_age <= 0.45:
            t = flash_age / 0.45
            flash_r = 14 + 46 * t
            flash_alpha = int(230 * (1 - t))
            p.setPen(QPen(QColor(255, 255, 255, flash_alpha), 2.5))
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


# ── Helpers ─────────────────────────────────────────────────────────────────

def _lighten(c: QColor, t: float) -> QColor:
    return QColor(
        int(c.red()   + (255 - c.red())   * t),
        int(c.green() + (255 - c.green()) * t),
        int(c.blue()  + (255 - c.blue())  * t),
    )


def _darken(c: QColor, t: float) -> QColor:
    return QColor(
        int(c.red()   * (1 - t)),
        int(c.green() * (1 - t)),
        int(c.blue()  * (1 - t)),
    )


class _Sparkle:
    def __init__(self, burst: bool = False):
        self.burst = burst
        self.dead = False
        self.reset()

    def reset(self):
        if self.burst:
            self.life = random.uniform(0.35, 0.65)
            self.radius = random.uniform(2, 8)
            self.radial_vel = random.uniform(50, 90)
            self.angular_vel = random.uniform(-3.5, 3.5)
            self.size = random.uniform(1.6, 2.8)
            self.hue = random.choice([WHITE_HOT, PINK_SOFT, POINT_BODY_START])
        else:
            self.life = random.uniform(1.0, 2.4)
            self.radius = random.uniform(6, 28)
            self.radial_vel = random.uniform(10, 18)
            self.angular_vel = random.uniform(-0.9, 0.9)
            self.size = random.uniform(1.3, 2.4)
            self.hue = random.choice([PINK_SOFT, VIOLET, WHITE_HOT, GOLD])
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
