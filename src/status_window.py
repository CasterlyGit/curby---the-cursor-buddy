"""Small floating status window showing what curby heard and what it's saying.

Movable (drag the header), semi-transparent, always-on-top. Styled to match the
curby palette. Closable to an iconized state via the minus button.
"""
import time

from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QPoint, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen, QPainterPath, QFont


BG_NAVY      = QColor(12, 15, 22, 215)    # near black, 85%
BG_NAVY_LT   = QColor(22, 26, 38, 215)
VIOLET       = QColor(167, 139, 250)
BLUE         = QColor( 96, 165, 250)
PINK_HOT     = QColor(236,  72, 153)
SKY          = QColor(125, 211, 252)
MINT         = QColor( 52, 211, 153)
TEXT_COOL    = QColor(244, 244, 248)
TEXT_DIM     = QColor(150, 160, 180)
TEXT_MUTE    = QColor(110, 120, 140)

ROLE_COLOR = {
    "user":   PINK_HOT,
    "curby":  SKY,
    "status": VIOLET,
    "error":  QColor(239, 68, 68),
}

MAX_LINES = 12
MIN_W = 280
DEFAULT_W = 340
DEFAULT_H = 240


class StatusWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(DEFAULT_W, DEFAULT_H)

        self._drag_offset: QPoint | None = None
        self._lines: list[tuple[str, str, float]] = []   # (role, text, ts)
        self._current_state: str = "idle"
        self._collapsed: bool = False

        # Animations
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self.update)
        self._pulse_timer.start(40)

    # ── Positioning ──────────────────────────────────────────────────────────

    def place_default(self):
        from PyQt6.QtWidgets import QApplication
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        geom = scr.availableGeometry()
        x = geom.right() - DEFAULT_W - 24
        y = geom.top() + 80
        self.move(x, y)

    # ── Public API (called via Qt signals) ──────────────────────────────────

    def set_state(self, state: str):
        self._current_state = state
        self.update()

    def push_heard(self, text: str):
        self._add_line("user", text)

    def push_said(self, text: str):
        self._add_line("curby", text)

    def push_status(self, text: str):
        self._add_line("status", text)

    def push_error(self, text: str):
        self._add_line("error", text)

    def _add_line(self, role: str, text: str):
        if not text:
            return
        self._lines.append((role, text, time.time()))
        if len(self._lines) > MAX_LINES:
            self._lines = self._lines[-MAX_LINES:]
        self.update()

    # ── Mouse — drag to move ─────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Only drag when press is inside the header zone (top 36 px)
            if e.position().y() <= 36:
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        # Double-click header collapses / expands
        if e.position().y() <= 36:
            self._collapsed = not self._collapsed
            self.resize(self.width(), 44 if self._collapsed else DEFAULT_H)
            self.update()

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Body — dark gradient
        body_path = QPainterPath()
        body_path.addRoundedRect(0, 0, w, h, 12, 12)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0.0, BG_NAVY)
        bg.setColorAt(1.0, BG_NAVY_LT)
        p.fillPath(body_path, bg)

        # Gradient border
        border = QLinearGradient(0, 0, w, h)
        border.setColorAt(0.0, VIOLET)
        border.setColorAt(1.0, BLUE)
        bpen = QPen(); bpen.setBrush(border); bpen.setWidthF(1.2)
        p.setPen(bpen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(body_path)

        # Header bar
        header_h = 36
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(0, 0, w, header_h, 12, 12)
        # flat bottom edge
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QColor(255, 255, 255, 20))
        p.drawLine(8, header_h, w - 8, header_h)

        # Status dot + label
        dot_color = self._state_color()
        # Dot with a breathing halo when active
        dot_cx, dot_cy = 14, header_h // 2
        if self._current_state in ("listening", "thinking", "speaking"):
            import math
            t = (time.time() * 2.2) % (2 * math.pi)
            breathe = (math.sin(t) + 1) / 2
            halo = QColor(dot_color)
            halo.setAlpha(int(60 + 90 * breathe))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPoint(dot_cx, dot_cy), 9, 9)
        p.setBrush(dot_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPoint(dot_cx, dot_cy), 4, 4)

        # Title + state label
        title_font = QFont("Segoe UI", 10); title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(TEXT_COOL)
        p.drawText(QRectF(26, 0, w - 40, header_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "curby")
        # State text
        state_font = QFont("Segoe UI", 9)
        p.setFont(state_font)
        p.setPen(TEXT_DIM)
        p.drawText(QRectF(80, 0, w - 100, header_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._state_label())

        # Drag hint on the right side of header
        grip_font = QFont("Segoe UI", 9)
        p.setFont(grip_font)
        p.setPen(TEXT_MUTE)
        p.drawText(QRectF(0, 0, w - 14, header_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "⋮⋮")

        if self._collapsed:
            return

        # Transcript lines
        line_y = header_h + 12
        line_h = 22
        visible_lines = (h - header_h - 16) // line_h
        lines = self._lines[-visible_lines:] if visible_lines > 0 else []

        p.setFont(QFont("Segoe UI", 9))

        if not lines:
            p.setPen(TEXT_MUTE)
            p.drawText(QRectF(14, line_y, w - 28, h - line_y),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                       "waiting for your voice…")
            return

        for role, text, _ts in lines:
            prefix = {"user": "you:", "curby": "curby:", "status": "•", "error": "!"}.get(role, "")
            role_color = ROLE_COLOR.get(role, TEXT_COOL)
            # Role prefix
            pf = QFont("Segoe UI", 9); pf.setBold(True); p.setFont(pf)
            p.setPen(role_color)
            p.drawText(QRectF(14, line_y, 50, line_h),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                       prefix)
            # Message text
            p.setFont(QFont("Segoe UI", 9))
            p.setPen(TEXT_COOL if role in ("user", "curby") else TEXT_DIM)
            p.drawText(QRectF(66, line_y, w - 80, line_h),
                       Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                       text)
            line_y += line_h

    def _state_color(self) -> QColor:
        return {
            "idle":      QColor(110, 120, 140),
            "listening": PINK_HOT,
            "thinking":  QColor(253, 224, 71),
            "speaking":  MINT,
            "error":     QColor(239, 68, 68),
        }.get(self._current_state, TEXT_DIM)

    def _state_label(self) -> str:
        return {
            "idle":      "idle",
            "listening": "listening…",
            "thinking":  "thinking…",
            "speaking":  "speaking…",
            "error":     "error",
        }.get(self._current_state, self._current_state)
