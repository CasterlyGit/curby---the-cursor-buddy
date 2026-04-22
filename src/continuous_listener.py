"""Always-on voice listener. Runs in a QThread, continuously waits for speech,
transcribes each utterance, and emits it as a Qt signal.

Supports pause() / resume() so the app can silence it during TTS playback or while
processing a previous utterance.
"""
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal


class ContinuousListener(QThread):
    utterance    = pyqtSignal(str)     # emitted with clean transcribed text
    waiting      = pyqtSignal()        # emitted when the listener (re)starts listening
    captured     = pyqtSignal(str)     # emitted right after capture, with the text
    listen_error = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop    = threading.Event()
        self._paused  = threading.Event()
        self._resumed = threading.Event()
        self._resumed.set()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def stop(self):
        self._stop.set()
        self._paused.clear()
        self._resumed.set()

    def pause(self):
        self._paused.set()
        self._resumed.clear()

    def resume(self):
        self._paused.clear()
        self._resumed.set()

    def is_paused(self) -> bool:
        return self._paused.is_set()

    # ── run ──────────────────────────────────────────────────────────────────

    def run(self):
        from src.voice_io import listen_once
        while not self._stop.is_set():
            if self._paused.is_set():
                # Block here while paused; wake when resumed or stopped
                self._resumed.wait(timeout=0.5)
                continue

            try:
                self.waiting.emit()
                text = listen_once()
            except RuntimeError:
                # "no speech detected" — listen_once has a ~15s cap; loop and try again
                continue
            except Exception as e:
                self.listen_error.emit(str(e))
                time.sleep(0.3)
                continue

            if self._stop.is_set():
                return
            if self._paused.is_set():
                continue  # drop this capture, we're paused
            if text and text.strip():
                clean = text.strip()
                self.captured.emit(clean)
                self.utterance.emit(clean)
                # Auto-pause so the worker can process without another capture piling up
                self._paused.set()
                self._resumed.clear()
