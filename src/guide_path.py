"""Full-screen transparent overlay that draws a dotted bezier path from the user's
cursor to the current guidance target. Dots brighten sequentially as the fairy
moves along the path — 'fairy footsteps'.

Click-through. Reconfigures to cover the virtual desktop bounds so it works across
monitors.
"""
import ctypes
import math
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QRadialGradient

PINK_SOFT = QColor(244, 114, 182)
SKY       = QColor(125, 211, 252)
BLUE      = QColor( 96, 165, 250)
WHITE_HOT = QColor(255, 255, 255)

ANIM_MS   = 950      # should match GhostCursor.animate_to default
HOLD_MS   = 1800     # stay visible this long after arrival
FADE_MS   = 500      # then fade

STEP_DOTS = 18       # number of footprints along the path

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020


class GuidePath(QWidget):
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

        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._t_start: float = 0.0
        self._t_arrived: float = 0.0  # set when hide_path is called (begin fade)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _cover_virtual(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        vg = scr.virtualGeometry()
        self.setGeometry(vg)

    def show_path(self, sx: int, sy: int, ex: int, ey: int):
        self._cover_virtual()
        vg = self.geometry()
        # Convert absolute screen coords into widget-local coords
        self._start = (sx - vg.left(), sy - vg.top())
        self._end   = (ex - vg.left(), ey - vg.top())
        self._t_start = time.time()
        self._t_arrived = 0.0
        self.show()
        self.raise_()

    def hide_path(self):
        if self._t_arrived == 0.0:
            self._t_arrived = time.time()

    # ── Tick ─────────────────────────────────────────────────────────────────

    def _tick(self):
        if self._t_arrived > 0.0:
            if (time.time() - self._t_arrived) * 1000 > HOLD_MS + FADE_MS:
                self.hide()
                self._start = self._end = None
                return
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        if self._start is None or self._end is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        elapsed_ms = (now - self._t_start) * 1000
        anim_progress = max(0.0, min(1.0, elapsed_ms / ANIM_MS))

        # Overall opacity (fade out after hold)
        overall = 1.0
        if self._t_arrived > 0.0:
            ms_since = (now - self._t_arrived) * 1000
            if ms_since > HOLD_MS:
                overall = max(0.0, 1.0 - (ms_since - HOLD_MS) / FADE_MS)
        if overall <= 0.0:
            return

        sx, sy = self._start
        ex, ey = self._end
        dx, dy = ex - sx, ey - sy
        # Control point for a gentle arc (perpendicular offset)
        cx_ctrl = (sx + ex) / 2 - dy * 0.18
        cy_ctrl = (sy + ey) / 2 + dx * 0.18

        for i in range(STEP_DOTS):
            t = (i + 0.5) / STEP_DOTS
            u = 1 - t
            bx = u * u * sx + 2 * u * t * cx_ctrl + t * t * ex
            by = u * u * sy + 2 * u * t * cy_ctrl + t * t * ey

            # Dot brightness: ones BEHIND the fairy glow; ones ahead are dim.
            behind = t <= anim_progress
            glow_age = max(0.0, anim_progress - t)
            if behind:
                intensity = max(0.15, 1.0 - glow_age * 1.6)
            else:
                intensity = 0.18

            # Alternate colors for a sparkle-trail feel
            color = SKY if (i % 2 == 0) else PINK_SOFT
            c = QColor(color); c.setAlpha(int(220 * intensity * overall))

            # Dot with halo
            halo = QRadialGradient(QPointF(bx, by), 9)
            h0 = QColor(c); h0.setAlpha(int(220 * intensity * overall))
            h1 = QColor(color); h1.setAlpha(int(80 * intensity * overall))
            h2 = QColor(0, 0, 0, 0)
            halo.setColorAt(0.0, h0)
            halo.setColorAt(0.5, h1)
            halo.setColorAt(1.0, h2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(bx, by), 9, 9)

            # Solid core
            core = QColor(WHITE_HOT); core.setAlpha(int(220 * intensity * overall))
            p.setBrush(core)
            p.drawEllipse(QPointF(bx, by), 2.2, 2.2)

        # Destination beacon — a wider ring that pulses as the fairy arrives
        dest_alpha = int(200 * overall * (0.5 + 0.5 * anim_progress))
        beacon = QColor(BLUE); beacon.setAlpha(dest_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(beacon)
        pulse_r = 4 + 3 * math.sin(now * 4.5)
        p.drawEllipse(QPointF(ex, ey), pulse_r, pulse_r)
