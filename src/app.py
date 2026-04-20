import sys
import threading
import time
import queue
from collections.abc import Callable
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from pynput import keyboard

from src.cursor_tracker import CursorTracker
from src.buddy_icon import BuddyIcon
from src.ghost_cursor import GhostCursor

HOTKEY = "<ctrl>+<shift>+<space>"
MAX_HISTORY = 10

_GUIDED_KEYWORDS = (
    "how do i", "how to ", "where is ", "where do i",
    "show me", "can you show", "guide me", "take me to",
    "navigate to", "how can i", "what do i click",
    "walk me through",
)


def _is_guided(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _GUIDED_KEYWORDS)


class _Bridge(QObject):
    cursor_moved = pyqtSignal(int, int)
    hotkey_fired = pyqtSignal()
    set_state    = pyqtSignal(str)
    guide_show   = pyqtSignal(int, int)
    guide_to     = pyqtSignal(int, int)
    guide_hide   = pyqtSignal()


class AssistantWorker(QThread):
    state    = pyqtSignal(str)
    exchange = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(self, cx: int, cy: int, history: list[dict],
                 bridge: _Bridge, step_event: threading.Event,
                 get_pos: Callable[[], tuple[int, int]]):
        super().__init__()
        self.cx = cx
        self.cy = cy
        self.history = list(history)
        self._bridge = bridge
        self._step_event = step_event
        self._get_pos = get_pos
        self._cancel = threading.Event()
        self.guided_waiting = False

    # ── Main pipeline ──────────────────────────────────────────────────────────

    def run(self):
        from src.voice_io import listen_once, speak
        from src.screen_capture import grab_region, grab_monitor_at
        from src.ai_client import ask_stream

        try:
            self.state.emit("listening")
            text = listen_once()
        except Exception as e:
            print(f"[listen error] {e}")
            speak("sorry, i didn't catch that.")
            self.state.emit("idle")
            self.finished.emit()
            return

        self.state.emit("thinking")

        # ── Guided path ──
        if _is_guided(text):
            try:
                image, mon_left, mon_top = grab_monitor_at(self.cx, self.cy)
            except Exception as e:
                print(f"[capture error] {e}")
                speak("couldn't capture the screen.")
                self.state.emit("idle")
                self.finished.emit()
            else:
                self._run_guided(mon_left, mon_top, text, image)
            return

        # ── Voice path ──
        try:
            image = grab_region(self.cx, self.cy, radius=500)
        except Exception as e:
            print(f"[capture error] {e}")
            speak("something went wrong capturing the screen.")
            self.state.emit("idle")
            self.finished.emit()
            return

        sentence_q: queue.Queue[str | None] = queue.Queue()
        full_reply_box: list[str] = []

        def _produce():
            try:
                reply = ask_stream(text, image, self.history,
                                   on_sentence=lambda s: sentence_q.put(s))
                full_reply_box.append(reply)
            except Exception as e:
                print(f"[ai error] {e}")
                sentence_q.put("something went wrong.")
            finally:
                sentence_q.put(None)

        threading.Thread(target=_produce, daemon=True).start()

        first = True
        while True:
            sentence = sentence_q.get()
            if sentence is None:
                break
            if first:
                self.state.emit("speaking")
                first = False
            speak(sentence, block=True)

        full_reply = full_reply_box[0] if full_reply_box else "(no response)"
        self.exchange.emit(text, full_reply)
        self.state.emit("idle")
        self.finished.emit()

    # ── Guided cursor route ────────────────────────────────────────────────────

    def _wait_for_hotkey(self) -> bool:
        """Block until Ctrl+Shift+Space is pressed (next step) or session cancelled."""
        while not self._cancel.is_set():
            if self._step_event.wait(timeout=0.1):
                self._step_event.clear()
                return True
        return False

    def _run_guided(self, mon_left: int, mon_top: int, task: str, image) -> None:
        """
        Clicky-style adaptive guidance loop:
          1. Ask Claude for next step + [POINT:x,y] based on CURRENT screenshot
          2. Animate ghost cursor to that point
          3. Speak the instruction (blocking)
          4. Wait for user to press hotkey (they've done the step)
          5. Re-screenshot and repeat
        """
        from src.voice_io import speak
        from src.ai_client import ask_guided_step
        from src.screen_capture import grab_monitor_at

        print(f"[guided] starting — monitor offset ({mon_left}, {mon_top})")
        self._step_event.clear()
        self._bridge.guide_show.emit(self.cx, self.cy)

        steps_done: list[str] = []
        current_image = image
        current_left, current_top = mon_left, mon_top

        try:
            for step_num in range(10):
                if self._cancel.is_set():
                    break

                self.state.emit("thinking")
                print(f"[guided] step {step_num + 1} — asking Claude...")
                spoken, x, y = ask_guided_step(task, current_image, steps_done)

                if self._cancel.is_set():
                    break

                print(f"[guided] response: {spoken!r}  point=({x},{y})")

                # x,y are in Claude's image space (1280px max) — scale to logical screen space
                img_w, img_h = current_image.size
                if x is not None and y is not None:
                    scale = max(img_w, img_h) / 1280 if max(img_w, img_h) > 1280 else 1.0
                    sx = int(x * scale) + current_left
                    sy = int(y * scale) + current_top
                    print(f"[guided] animating ghost to screen ({sx}, {sy})")
                    self._bridge.guide_to.emit(sx, sy)
                else:
                    # [POINT:none] — task complete or nothing to point at
                    self._bridge.guide_hide.emit()

                self.state.emit("speaking")
                speak(spoken, block=True)

                if x is None:
                    # Done
                    break

                # Wait for user to press hotkey to advance
                self.state.emit("idle")
                self.guided_waiting = True
                ok = self._wait_for_hotkey()
                self.guided_waiting = False
                if not ok:
                    break

                steps_done.append(spoken)

                # Pause for UI to settle after user's action
                time.sleep(0.5)

                # Re-capture screen at user's current cursor position
                try:
                    cx, cy = self._get_pos()
                    current_image, current_left, current_top = grab_monitor_at(cx, cy)
                    print(f"[guided] re-captured at ({cx},{cy}) offset=({current_left},{current_top})")
                except Exception as e:
                    print(f"[guided] re-capture failed: {e}")
                    break

            self._bridge.guide_hide.emit()
            self.exchange.emit(task, "; ".join(steps_done) or "(guided session)")
        finally:
            self.state.emit("idle")
            self.finished.emit()


class CurbyApp:
    def __init__(self):
        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._bridge = _Bridge()
        self._icon = BuddyIcon()
        self._ghost = GhostCursor()
        self._cursor = CursorTracker(on_move=self._on_move)
        self._hotkey = keyboard.GlobalHotKeys({HOTKEY: self._on_hotkey})
        self._worker: AssistantWorker | None = None
        self._cx = 0
        self._cy = 0
        self._history: list[dict] = []
        self._step_event = threading.Event()
        self._restart_pending = False
        self._worker_lock = threading.Lock()

        self._bridge.cursor_moved.connect(self._icon.move_near_cursor)
        self._bridge.hotkey_fired.connect(self._activate)
        self._bridge.set_state.connect(self._icon.set_state)
        self._bridge.guide_show.connect(self._ghost.show_at)
        self._bridge.guide_to.connect(self._ghost.animate_to)
        self._bridge.guide_hide.connect(self._ghost.hide)

    def _on_move(self, x, y):
        self._cx, self._cy = x, y
        self._bridge.cursor_moved.emit(x, y)

    def _on_hotkey(self):
        self._bridge.hotkey_fired.emit()

    def _on_exchange(self, user_text: str, assistant_reply: str):
        self._history.append({"user": user_text, "assistant": assistant_reply})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]

    def _on_worker_finished(self):
        with self._worker_lock:
            restart = self._restart_pending
            self._restart_pending = False
        if restart:
            self._start_worker()

    def _start_worker(self):
        with self._worker_lock:
            w = AssistantWorker(
                self._cx, self._cy, self._history,
                self._bridge, self._step_event,
                get_pos=lambda: (self._cx, self._cy),
            )
            w.state.connect(self._icon.set_state)
            w.exchange.connect(self._on_exchange)
            w.finished.connect(self._on_worker_finished)
            self._worker = w
        w.start()

    def _activate(self):
        with self._worker_lock:
            running = self._worker is not None and self._worker.isRunning()
            waiting = running and self._worker.guided_waiting

        if waiting:
            # Between guided steps — advance to next step
            self._step_event.set()
            return

        if running:
            # Actively processing — cancel and restart fresh
            with self._worker_lock:
                self._worker._cancel.set()
                self._restart_pending = True
            self._step_event.set()
            self._bridge.guide_hide.emit()
            self._icon.set_state("idle")
            return

        self._start_worker()

    def run(self):
        from PyQt6.QtGui import QCursor
        from src.voice_io import speak
        pos = QCursor.pos()
        self._cx, self._cy = pos.x(), pos.y()
        self._icon.move_near_cursor(self._cx, self._cy)

        self._cursor.start()
        self._hotkey.start()
        self._icon.show()
        speak("curby ready.")
        print(f"Curby ready. Press {HOTKEY} to speak.")
        code = self._qt.exec()
        self._cursor.stop()
        self._hotkey.stop()
        return code
