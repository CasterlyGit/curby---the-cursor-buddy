from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QFont, QKeyEvent, QColor

PANEL_W = 360
PANEL_H = 420
MARGIN = 20


class AIWorker(QThread):
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text, image):
        super().__init__()
        self.text = text
        self.image = image

    def run(self):
        try:
            from src.ai_client import ask
            self.result_ready.emit(ask(self.text, self.image))
        except Exception as e:
            self.error.emit(str(e))


class ChatPanel(QWidget):
    state_changed = pyqtSignal(str)   # "idle" | "thinking" | "ready" | "error"

    def __init__(self):
        super().__init__()
        self._image = None
        self._worker = None
        self._setup_window()
        self._build_ui()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedSize(PANEL_W, PANEL_H)
        self.setStyleSheet("""
            QWidget#panel {
                background: #16161e;
                border: 1px solid #2a2a3e;
                border-radius: 12px;
            }
            QTextEdit {
                background: #1a1a27;
                border: 1px solid #2a2a3e;
                border-radius: 6px;
                color: #c0c0d0;
                font-size: 12px;
                padding: 6px;
            }
            QLineEdit {
                background: #1a1a27;
                border: 1px solid #3a3a5e;
                border-radius: 6px;
                color: #e0e0f0;
                font-size: 12px;
                padding: 6px 10px;
            }
            QLineEdit:focus { border: 1px solid #6060cc; }
            QPushButton {
                background: #3a3af0;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background: #5050ff; }
            QPushButton:disabled { background: #2a2a3e; color: #505060; }
            QPushButton#snap {
                background: #2a2a3e;
                color: #8080cc;
            }
            QPushButton#snap:hover { background: #3a3a5e; }
        """)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        panel = QWidget()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Curby")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title.setStyleSheet("color: #8080ee; background: transparent;")
        self._status = QLabel("ready")
        self._status.setStyleSheet("color: #505060; font-size: 10px; background: transparent;")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #505060; font-size: 16px; border: none; padding: 0; }
            QPushButton:hover { color: #cc4444; }
        """)
        close_btn.clicked.connect(self.hide)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._status)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Chat log
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        layout.addWidget(self._chat, stretch=1)

        # Screenshot strip
        self._img_label = QLabel("")
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_label.setStyleSheet("color: #505060; font-size: 10px; background: transparent;")
        layout.addWidget(self._img_label)

        # Input row
        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask anything... (Enter to send)")
        self._input.returnPressed.connect(self._send)
        snap_btn = QPushButton("Snap")
        snap_btn.setObjectName("snap")
        snap_btn.setFixedWidth(50)
        snap_btn.clicked.connect(self._snap)
        self._ask_btn = QPushButton("Ask")
        self._ask_btn.setFixedWidth(50)
        self._ask_btn.clicked.connect(self._send)
        row.addWidget(self._input, stretch=1)
        row.addWidget(snap_btn)
        row.addWidget(self._ask_btn)
        layout.addLayout(row)

        outer.addWidget(panel)

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()

    def toggle_at(self, x: int, y: int):
        if self.isVisible():
            self.hide()
            return
        screen = QApplication.primaryScreen().geometry()
        wx = min(x + 20, screen.width() - PANEL_W - MARGIN)
        wy = min(y + 20, screen.height() - PANEL_H - MARGIN)
        self.move(max(MARGIN, wx), max(MARGIN, wy))
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def set_screenshot(self, image):
        self._image = image
        if image:
            self._img_label.setText(f"Screenshot ready: {image.size[0]}x{image.size[1]}")
        else:
            self._img_label.setText("")

    def _snap(self):
        from src.screen_capture import grab_region
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        img = grab_region(pos.x(), pos.y(), radius=400)
        self.set_screenshot(img)
        self._append("System", "Screenshot captured.")

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append("You", text)
        self._ask_btn.setEnabled(False)
        self._status.setText("thinking...")
        self.state_changed.emit("thinking")

        self._worker = AIWorker(text, self._image)
        self._worker.result_ready.connect(self._on_reply)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_reply(self, text):
        self._append("Buddy", text)
        self._status.setText("ready")
        self._ask_btn.setEnabled(True)
        self.state_changed.emit("ready")

    @pyqtSlot(str)
    def _on_error(self, err):
        self._append("Error", err)
        self._status.setText("error")
        self._ask_btn.setEnabled(True)
        self.state_changed.emit("error")

    def _append(self, speaker, text):
        colors = {
            "You":    "#88cc88",
            "Buddy":  "#8888ee",
            "System": "#ccaa55",
            "Error":  "#ee6666",
        }
        c = colors.get(speaker, "#c0c0d0")
        self._chat.append(
            f'<span style="color:{c};font-weight:bold">{speaker}</span>'
            f'<span style="color:#606070"> › </span>'
            f'<span style="color:#c0c0d0">{text}</span>'
        )
