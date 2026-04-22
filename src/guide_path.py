"""Full-screen transparent overlay that draws a dotted path from the user's cursor
to the current guidance target. Dots light up sequentially as the fairy moves
along the path.

The effect should read as a single path-to-follow, not a string of colored
lights — tight spacing, single accent color, small dots.
"""
import ctypes
import math
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import QPainter, QColor, QRadialGradient

# Single accent color — matches pointing-mode body so the trail reads as one piece
TRAIL = QColor(125, 211, 252)   # sky-300
TRAIL_EDGE = QColor(79, 70, 229)  # indigo edge on destination
WHITE_HOT = QColor(255, 255, 255)

ANIM_MS = 950
HOLD_MS = 1800
FADE_MS = 500

STEP_DOTS = 44          # dense — reads as a continuous path, not discrete lights
DOT_CORE_R = 1.6
DOT_HALO_R = 5

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
        self._t_arrived: float = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _cover_virtual(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        self.setGeometry(scr.virtualGeometry())

    def show_path(self, sx: int, sy: int, ex: int, ey: int):
        self._cover_virtual()
        vg = self.geometry()
        self._start = (sx - vg.left(), sy - vg.top())
        self._end   = (ex - vg.left(), ey - vg.top())
        self._t_start = time.time()
        self._t_arrived = 0.0
        self.show()
        self.raise_()

    def hide_path(self):
        if self._t_arrived == 0.0:
            self._t_arrived = time.time()

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

    def paintEvent(self, event):
        if self._start is None or self._end is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        now = time.time()
        elapsed_ms = (now - self._t_start) * 1000
        progress = max(0.0, min(1.0, elapsed_ms / ANIM_MS))

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
        # Gentle arc — enough to feel guided, not enough to feel curvy
        cx_ctrl = (sx + ex) / 2 - dy * 0.12
        cy_ctrl = (sy + ey) / 2 + dx * 0.12

        for i in range(STEP_DOTS):
            t = (i + 0.5) / STEP_DOTS
            u = 1 - t
            bx = u * u * sx + 2 * u * t * cx_ctrl + t * t * ex
            by = u * u * sy + 2 * u * t * cy_ctrl + t * t * ey

            # Behind the fairy → bright. Ahead → dim.
            if t <= progress:
                trail_age = progress - t
                intensity = max(0.25, 1.0 - trail_age * 1.4)
            else:
                intensity = 0.18

            alpha_core = int(230 * intensity * overall)
            alpha_halo = int(110 * intensity * overall)

            halo = QRadialGradient(QPointF(bx, by), DOT_HALO_R)
            h0 = QColor(TRAIL); h0.setAlpha(alpha_halo)
            h1 = QColor(TRAIL); h1.setAlpha(int(alpha_halo * 0.3))
            halo.setColorAt(0.0, h0)
            halo.setColorAt(0.55, h1)
            halo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(bx, by), DOT_HALO_R, DOT_HALO_R)

            core = QColor(WHITE_HOT); core.setAlpha(alpha_core)
            p.setBrush(core)
            p.drawEllipse(QPointF(bx, by), DOT_CORE_R, DOT_CORE_R)

        # Destination beacon — clearly marks the end of the path
        beacon_alpha = int(220 * overall)
        ring_color = QColor(TRAIL_EDGE); ring_color.setAlpha(beacon_alpha)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ring_color)
        pulse_r = 3.5 + 2 * math.sin(now * 4.5)
        p.drawEllipse(QPointF(ex, ey), pulse_r, pulse_r)
