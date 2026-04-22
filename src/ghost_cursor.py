import ctypes
import math
import time

from PyQt6.QtWidgets import QWidget
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
# Warm pink/red cursor body, violet/blue rings behind it for contrast.
PINK_HOT   = QColor(236,  72, 153)   # #EC4899
PINK_SOFT  = QColor(244, 114, 182)   # #F472B6
ROSE       = QColor(251, 113, 133)   # #FB7185
RED        = QColor(239,  68,  68)   # #EF4444
VIOLET     = QColor(167, 139, 250)   # #A78BFA
BLUE       = QColor( 96, 165, 250)   # #60A5FA
WHITE_HOT  = QColor(255, 255, 255)

SIZE = 110   # widget box; tip of cursor = center of widget

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020


class GhostCursor(QWidget):
    arrived = pyqtSignal()

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
        self._anim: QPropertyAnimation | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self.update)
        self._tick_timer.start(16)

    # ── Swoosh path ──────────────────────────────────────────────────────────

    def _swoosh_path(self, cx: float, cy: float) -> QPainterPath:
        """Nike-ish swoosh: narrow tail at upper-left, sweeps down-right, bulges in the
        middle, tapers to a sharp tip at the bottom-right. The TIP lands on (cx, cy)
        so animate_to places the sharp end on the target."""
        path = QPainterPath()

        # Tip is at (cx, cy). Everything else is offset from there.
        tip   = QPointF(cx, cy)
        tail  = QPointF(cx - 28, cy - 18)   # narrow start at upper-left

        # Outer (lower) curve: tail → tip
        path.moveTo(tail)
        path.cubicTo(
            QPointF(cx - 18, cy + 6),
            QPointF(cx - 4, cy + 10),
            tip,
        )
        # Inner (upper) curve: tip → tail, creates the swoosh bulge
        path.cubicTo(
            QPointF(cx - 6, cy - 2),
            QPointF(cx - 18, cy - 10),
            tail,
        )
        path.closeSubpath()
        return path

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE // 2
        elapsed = time.time() - self._t0

        # Sonar rings — violet/blue for contrast with the warm cursor body
        for phase_offset, ring_color in ((0.0, VIOLET), (0.5, BLUE)):
            phase = ((elapsed * 0.85) + phase_offset) % 1.0
            r = 18 + 34 * phase
            alpha = int(170 * (1.0 - phase) ** 1.4)
            c = QColor(ring_color); c.setAlpha(alpha)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)

        # Soft pink halo underneath the swoosh
        halo = QRadialGradient(cx - 4, cy - 2, 42)
        h0 = QColor(PINK_HOT);  h0.setAlpha(120)
        h1 = QColor(ROSE);      h1.setAlpha(70)
        h2 = QColor(ROSE);      h2.setAlpha(0)
        halo.setColorAt(0.0, h0)
        halo.setColorAt(0.55, h1)
        halo.setColorAt(1.0, h2)
        p.setBrush(halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx - 4, cy - 2), 42, 42)

        # Swoosh body — pink/red gradient along the diagonal
        path = self._swoosh_path(cx, cy)
        body_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        body_grad.setColorAt(0.0, PINK_SOFT)
        body_grad.setColorAt(0.55, PINK_HOT)
        body_grad.setColorAt(1.0, RED)
        p.setBrush(body_grad)

        # Subtle rim for separation
        rim_grad = QLinearGradient(cx - 28, cy - 18, cx, cy)
        rim_grad.setColorAt(0.0, QColor(255, 200, 220, 160))
        rim_grad.setColorAt(1.0, QColor(180, 20, 60, 200))
        rim_pen = QPen()
        rim_pen.setBrush(rim_grad)
        rim_pen.setWidthF(1.2)
        p.setPen(rim_pen)
        p.drawPath(path)

        # Bright highlight sliver on the upper edge of the swoosh
        hl = QPainterPath()
        hl.moveTo(cx - 22, cy - 14)
        hl.cubicTo(
            QPointF(cx - 14, cy - 8),
            QPointF(cx - 6, cy - 5),
            QPointF(cx - 2, cy - 2),
        )
        hl_pen = QPen(QColor(255, 255, 255, 150), 1.3)
        p.setPen(hl_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hl)

        # Tiny bright dot exactly on the tip (so the target point reads clearly)
        tip_glow = QRadialGradient(cx, cy, 7)
        tip_glow.setColorAt(0.0, WHITE_HOT)
        tip_glow.setColorAt(0.5, QColor(255, 200, 215, 230))
        tip_edge = QColor(PINK_HOT); tip_edge.setAlpha(0)
        tip_glow.setColorAt(1.0, tip_edge)
        p.setBrush(tip_glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), 5, 5)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_TRANSPARENT)
        except Exception:
            pass

    # ── API ──────────────────────────────────────────────────────────────────

    def show_at(self, x: int, y: int):
        print(f"[ghost] show_at ({x},{y})")
        self.move(x - SIZE // 2, y - SIZE // 2)
        self.show()

    def animate_to(self, x: int, y: int, ms: int = 900):
        print(f"[ghost] animate_to ({x},{y}) visible={self.isVisible()}")
        if not self.isVisible():
            self.move(x - SIZE // 2, y - SIZE // 2)
            self.show()
        if self._anim:
            try:
                self._anim.finished.disconnect()
            except Exception:
                pass
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        target = QPoint(x - SIZE // 2, y - SIZE // 2)
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(ms)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        anim.finished.connect(self.arrived)
        self._anim = anim
        anim.start()
