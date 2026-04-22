import math
import time

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QRadialGradient

# ── Vista / Curby palette ────────────────────────────────────────────────────
# Cohesive with ghost_cursor + speech_bubble
VIOLET       = QColor(167, 139, 250)   # #A78BFA
BLUE         = QColor( 96, 165, 250)   # #60A5FA
VIOLET_LIGHT = QColor(196, 181, 253)   # #C4B5FD
PINK_HOT     = QColor(236,  72, 153)   # #EC4899 (listening — warm rose)
MINT         = QColor( 52, 211, 153)   # #34D399 (speaking)
RED          = QColor(248, 113, 113)   # #F87171 (error)
STEEL        = QColor( 71,  85, 105)   # #475569 (idle)

STATE_ACCENT = {
    "idle":      STEEL,
    "listening": PINK_HOT,
    "thinking":  VIOLET,
    "speaking":  MINT,
    "error":     RED,
}

SIZE        = 28          # core orb diameter
HALO        = 22          # halo extra radius beyond orb
WIDGET_SIZE = SIZE + HALO * 2
OFFSET_X    = 22
OFFSET_Y    = 22


class BuddyIcon(QWidget):
    def __init__(self):
        super().__init__()
        self._state = "idle"
        self._t0 = time.time()
        self._setup()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)

    def _setup(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)

    def set_state(self, state: str):
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = cy = WIDGET_SIZE / 2
        accent = STATE_ACCENT.get(self._state, STEEL)
        active = self._state in ("thinking", "listening", "speaking")
        elapsed = time.time() - self._t0
        breathe = (math.sin(elapsed * (4.0 if active else 1.6)) + 1) * 0.5

        # Outer halo (soft radial)
        halo = QRadialGradient(cx, cy, HALO + SIZE / 2)
        a0 = QColor(accent); a0.setAlpha(int((80 if active else 40) + 80 * breathe))
        a1 = QColor(accent); a1.setAlpha(int((40 if active else 20) + 30 * breathe))
        a2 = QColor(accent); a2.setAlpha(0)
        halo.setColorAt(0.0, a0)
        halo.setColorAt(0.45, a1)
        halo.setColorAt(1.0, a2)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), HALO + SIZE / 2, HALO + SIZE / 2)

        # Orb gradient fill (top-light to accent)
        orb = QRadialGradient(cx - SIZE * 0.18, cy - SIZE * 0.2, SIZE * 0.9)
        hi = QColor(255, 255, 255); hi.setAlpha(230)
        mid = QColor(accent); mid.setAlpha(240)
        base = QColor(accent); base.setAlpha(255)
        orb.setColorAt(0.0, hi)
        orb.setColorAt(0.35, mid)
        orb.setColorAt(1.0, base)
        p.setBrush(orb)
        p.drawEllipse(QPointF(cx, cy), SIZE / 2, SIZE / 2)

        # Thin inner rim (white @ low alpha)
        rim = QColor(255, 255, 255, 80)
        p.setPen(rim)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), SIZE / 2 - 0.5, SIZE / 2 - 0.5)

    def move_near_cursor(self, x: int, y: int):
        self.move(x + OFFSET_X, y + OFFSET_Y)
