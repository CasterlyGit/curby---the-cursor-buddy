from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QFont, QKeyEvent


OFFSET_X = 20
OFFSET_Y = 20
WINDOW_W = 340
WINDOW_H = 320


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
            reply = ask(self.text, self.image)
            self.result_ready.emit(reply)
        except Exception as e:
            self.error.emit(str(e))


class BuddyWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._current_image = None
        self._worker = None
        self._setup_window()
        self._build_ui()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: Segoe UI, sans-serif;
                font-size: 12px;
            }
            QTextEdit {
                background-color: #181825;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px;
            }
            QLineEdit {
                background-color: #181825;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #b4befe; }
            QPushButton:disabled { background-color: #45475a; color: #6c7086; }
            QLabel { color: #a6adc8; font-size: 11px; }
        """)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel("Curby")
        title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        title.setStyleSheet("color: #89b4fa; font-size: 11px;")
        self._status = QLabel("ready")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._status)
        layout.addLayout(header)

        # Chat display
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setPlaceholderText("Ask me anything about what's on screen...")
        layout.addWidget(self._chat, stretch=1)

        # Screenshot indicator
        self._img_label = QLabel("No screenshot captured")
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._img_label)

        # Input row
        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask about screen...")
        self._input.returnPressed.connect(self._send)
        self._btn_ask = QPushButton("Ask")
        self._btn_ask.clicked.connect(self._send)
        self._btn_snap = QPushButton("Snap")
        self._btn_snap.setToolTip("Capture screen around cursor")
        self._btn_snap.clicked.connect(self._snap)
        input_row.addWidget(self._input, stretch=1)
        input_row.addWidget(self._btn_snap)
        input_row.addWidget(self._btn_ask)
        layout.addLayout(input_row)

    def move_near_cursor(self, x, y):
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        wx = x + OFFSET_X
        wy = y + OFFSET_Y
        if wx + WINDOW_W > screen.width():
            wx = x - WINDOW_W - OFFSET_X
        if wy + WINDOW_H > screen.height():
            wy = y - WINDOW_H - OFFSET_Y
        self.move(max(0, wx), max(0, wy))

    def set_screenshot(self, image):
        self._current_image = image
        self._img_label.setText(f"Screenshot: {image.size[0]}x{image.size[1]}")

    def _snap(self):
        from src.screen_capture import grab_region
        from PyQt6.QtGui import QCursor
        pos = QCursor.pos()
        img = grab_region(pos.x(), pos.y(), radius=400)
        self.set_screenshot(img)
        self._append_chat("System", "Screenshot captured.")

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._append_chat("You", text)
        self._btn_ask.setEnabled(False)
        self._btn_snap.setEnabled(False)
        self._status.setText("thinking...")

        self._worker = AIWorker(text, self._current_image)
        self._worker.result_ready.connect(self._on_reply)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    @pyqtSlot(str)
    def _on_reply(self, text):
        self._append_chat("Buddy", text)
        self._status.setText("ready")
        self._btn_ask.setEnabled(True)
        self._btn_snap.setEnabled(True)

    @pyqtSlot(str)
    def _on_error(self, err):
        self._append_chat("Error", err)
        self._status.setText("error")
        self._btn_ask.setEnabled(True)
        self._btn_snap.setEnabled(True)

    def _append_chat(self, speaker, text):
        colors = {"You": "#a6e3a1", "Buddy": "#89b4fa", "System": "#f9e2af", "Error": "#f38ba8"}
        color = colors.get(speaker, "#cdd6f4")
        self._chat.append(f'<span style="color:{color};font-weight:bold">{speaker}:</span> {text}')
