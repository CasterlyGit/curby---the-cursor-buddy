"""Full-screen transparent overlay that highlights a target UI element with a
rounded rectangle + corner brackets + action-specific icon.

Click-through. Covers the virtual desktop so it works on multi-monitor setups.
"""
import ctypes
import math
import time

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QLinearGradient

SKY   = QColor(125, 211, 252)
BLUE  = QColor( 59, 130, 246)
INDIGO= QColor( 79,  70, 229)
PINK  = QColor(244, 114, 182)
RED   = QColor(239,  68,  68)
MINT  = QColor( 52, 211, 153)
WHITE = QColor(255, 255, 255)

# Action -> accent color (matches pointing palette, but accents shift for intent)
ACTION_COLORS = {
    "click":  (SKY, BLUE),
    "select": (SKY, INDIGO),
    "close":  (QColor(255, 180, 180), RED),
    "type":   (PINK, INDIGO),
    "drag":   (SKY, MINT),
    "open":   (SKY, MINT),
}

FADE_IN_MS  = 250
HOLD_MS     = 12_000       # maximum time box stays up (cleared by hide_highlight)
FADE_OUT_MS = 400

_GWL_EXSTYLE       = -20
_WS_EX_TRANSPARENT = 0x00000020


class ActionHighlight(QWidget):
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

        self._rect: tuple[int, int, int, int] | None = None   # widget-local
        self._action = "click"
        self._t_show = 0.0
        self._t_hide = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _cover_virtual(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        vg = scr.virtualGeometry()
        self.setGeometry(vg)

    def show_highlight(self, x1: int, y1: int, x2: int, y2: int, action: str = "click"):
        self._cover_virtual()
        vg = self.geometry()
        # Normalize + clamp
        lx, rx = sorted((x1 - vg.left(), x2 - vg.left()))
        ty, by = sorted((y1 - vg.top(),  y2 - vg.top()))
        # Pad minimum element size for visibility
        if rx - lx < 14: rx = lx + 14
        if by - ty < 14: by = ty + 14
        self._rect = (lx, ty, rx - lx, by - ty)
        self._action = action.lower() if action else "click"
        self._t_show = time.time()
        self._t_hide = 0.0
        self.show()
        self.raise_()

    def hide_highlight(self):
        if self._t_hide == 0.0:
            self._t_hide = time.time()

    def _tick(self):
        if self._t_hide > 0.0:
            if (time.time() - self._t_hide) * 1000 > FADE_OUT_MS:
                self.hide()
                self._rect = None
                return
        elif self._t_show > 0.0:
            if (time.time() - self._t_show) * 1000 > HOLD_MS:
                self.hide_highlight()
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
        if self._rect is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = time.time()

        # Overall opacity: fade in, hold, fade out
        in_ms = (now - self._t_show) * 1000
        in_op = min(1.0, in_ms / FADE_IN_MS)
        out_op = 1.0
        if self._t_hide > 0.0:
            out_ms = (now - self._t_hide) * 1000
            out_op = max(0.0, 1.0 - out_ms / FADE_OUT_MS)
        overall = min(in_op, out_op)
        if overall <= 0.0:
            return

        x, y, w, h = self._rect
        rect = QRectF(x, y, w, h)

        accent_a, accent_b = ACTION_COLORS.get(self._action, ACTION_COLORS["click"])

        # Pulsing glow outline
        breathe = (math.sin(now * 3.4) + 1) / 2
        glow_alpha = int((100 + 80 * breathe) * overall)
        glow_pen = QPen(QColor(accent_b.red(), accent_b.green(), accent_b.blue(), glow_alpha))
        glow_pen.setWidthF(6)
        p.setPen(glow_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(-4, -4, 4, 4), 10, 10)

        # Inner solid outline with gradient stroke
        sg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        a = QColor(accent_a); a.setAlpha(int(255 * overall))
        b = QColor(accent_b); b.setAlpha(int(255 * overall))
        sg.setColorAt(0.0, a)
        sg.setColorAt(1.0, b)
        pen = QPen(); pen.setBrush(sg); pen.setWidthF(2.4)
        p.setPen(pen)
        p.drawRoundedRect(rect, 8, 8)

        # Soft interior tint
        tint = QColor(accent_b); tint.setAlpha(int(28 * overall))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(rect, 8, 8)

        # Corner brackets for that "targeting reticle" feel
        bracket_len = max(10, min(22, int(min(w, h) * 0.22)))
        bracket_pen = QPen(WHITE, 2.2)
        bracket_color = QColor(255, 255, 255, int(220 * overall))
        bracket_pen.setColor(bracket_color)
        p.setPen(bracket_pen)
        L = x; R = x + w; T = y; B = y + h
        # Top-left
        p.drawLine(int(L), int(T + bracket_len), int(L), int(T))
        p.drawLine(int(L), int(T), int(L + bracket_len), int(T))
        # Top-right
        p.drawLine(int(R - bracket_len), int(T), int(R), int(T))
        p.drawLine(int(R), int(T), int(R), int(T + bracket_len))
        # Bottom-right
        p.drawLine(int(R), int(B - bracket_len), int(R), int(B))
        p.drawLine(int(R), int(B), int(R - bracket_len), int(B))
        # Bottom-left
        p.drawLine(int(L + bracket_len), int(B), int(L), int(B))
        p.drawLine(int(L), int(B), int(L), int(B - bracket_len))

        # Action icon — small badge in the top-right corner
        badge_w, badge_h = 70, 22
        bx = int(R - badge_w - 2)
        by_ = int(T - badge_h - 6) if T - badge_h - 6 > 0 else int(B + 6)
        badge_bg = QColor(15, 20, 30, int(230 * overall))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(badge_bg)
        p.drawRoundedRect(bx, by_, badge_w, badge_h, 10, 10)
        # Badge border (gradient)
        bg = QLinearGradient(bx, by_, bx + badge_w, by_ + badge_h)
        bg.setColorAt(0.0, a); bg.setColorAt(1.0, b)
        bpen = QPen(); bpen.setBrush(bg); bpen.setWidthF(1.2)
        p.setPen(bpen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(bx, by_, badge_w, badge_h, 10, 10)

        # Badge text
        p.setPen(QColor(244, 244, 248, int(240 * overall)))
        font = p.font(); font.setPointSize(9); font.setBold(True); p.setFont(font)
        p.drawText(QRectF(bx, by_, badge_w, badge_h), Qt.AlignmentFlag.AlignCenter,
                   self._action.upper())
