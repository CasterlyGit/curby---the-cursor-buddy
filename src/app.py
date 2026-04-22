import sys
import threading
import time
import queue
from collections.abc import Callable
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from pynput import keyboard

from src.cursor_tracker import CursorTracker
from src.ghost_cursor import GhostCursor
from src.speech_bubble import SpeechBubble
from src.text_input_popup import TextInputPopup
from src.guide_path import GuidePath
from src.action_highlight import ActionHighlight
from src.continuous_listener import ContinuousListener
from src.status_window import StatusWindow

HOTKEY_VOICE     = "<ctrl>+/"
HOTKEY_VOICELESS = "<ctrl>+."
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
    cursor_moved          = pyqtSignal(int, int)
    voice_hotkey_fired    = pyqtSignal()
    voiceless_hotkey_fired = pyqtSignal()
    set_state             = pyqtSignal(str)
    guide_show            = pyqtSignal(int, int)
    guide_to              = pyqtSignal(int, int)
    guide_hide            = pyqtSignal()
    bubble_show           = pyqtSignal(int, int, str)
    bubble_hide           = pyqtSignal()
    text_prompt_show      = pyqtSignal(int, int)
    path_show             = pyqtSignal(int, int, int, int)  # sx, sy, ex, ey
    path_hide             = pyqtSignal()
    highlight_show        = pyqtSignal(int, int, int, int, str)  # x1,y1,x2,y2,action
    highlight_hide        = pyqtSignal()


class AssistantWorker(QThread):
    state    = pyqtSignal(str)
    exchange = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(self, cx: int, cy: int, history: list[dict],
                 bridge: _Bridge, step_event: threading.Event,
                 get_pos: Callable[[], tuple[int, int]],
                 mode: str = "voice",
                 typed_text: str | None = None,
                 heard_text: str | None = None):
        super().__init__()
        self.cx = cx
        self.cy = cy
        self.history = list(history)
        self._bridge = bridge
        self._step_event = step_event
        self._get_pos = get_pos
        self._cancel = threading.Event()
        self.mode = mode                      # "voice" | "voiceless"
        self.typed_text = typed_text
        self.heard_text = heard_text          # pretranscribed (skip mic)
        self.guided_waiting = False

    # ── Main pipeline ──────────────────────────────────────────────────────────

    def run(self):
        from src.voice_io import listen_once, speak
        from src.screen_capture import grab_region, grab_monitor_at
        from src.ai_client import ask_stream

        voiceless = (self.mode == "voiceless")

        # ── Acquire user text (typed, pretranscribed, or live mic) ──
        if voiceless:
            text = (self.typed_text or "").strip()
            if not text:
                self.state.emit("idle")
                self.finished.emit()
                return
        elif self.heard_text:
            text = self.heard_text.strip()
            if not text:
                self.state.emit("idle")
                self.finished.emit()
                return
        else:
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
                self._say_or_show("couldn't capture the screen.", self.cx, self.cy)
                self.state.emit("idle")
                self.finished.emit()
            else:
                self._run_guided(mon_left, mon_top, text, image)
            return

        # ── Conversational path ──
        try:
            image = grab_region(self.cx, self.cy, radius=500)
        except Exception as e:
            print(f"[capture error] {e}")
            self._say_or_show("something went wrong capturing the screen.", self.cx, self.cy)
            self.state.emit("idle")
            self.finished.emit()
            return

        if voiceless:
            # Single-shot: get full reply, then show in bubble
            try:
                reply = ask_stream(text, image, self.history, on_sentence=lambda s: None)
            except Exception as e:
                print(f"[ai error] {e}")
                reply = "something went wrong."
            self._bridge.bubble_show.emit(self.cx, self.cy, reply)
            self.exchange.emit(text, reply)
            self.state.emit("idle")
            self.finished.emit()
            return

        # Voice: sentence-stream TTS
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

    def _watch_for_screen_change(self, target_x: int, target_y: int,
                                 radius: int = 150,
                                 diff_threshold: float = 0.12,
                                 warmup_s: float = 0.7,
                                 timeout_s: float = 45.0,
                                 poll_s: float = 0.35) -> bool:
        """
        Watch a region around (target_x, target_y) for significant pixel change.
        Returns True when the user's action changes the UI (auto-advance).
        Returns False if cancelled or timed out.
        """
        from src.screen_capture import grab_region
        from PIL import ImageChops
        import math

        # Warmup: let any animation from our own ghost settle, and capture baseline
        end_warmup = time.time() + warmup_s
        while time.time() < end_warmup:
            if self._cancel.is_set():
                return False
            time.sleep(0.05)

        try:
            baseline = grab_region(target_x, target_y, radius=radius).convert("L")
        except Exception as e:
            print(f"[watch] baseline capture failed: {e}")
            return False

        baseline_px = baseline.size[0] * baseline.size[1]
        deadline = time.time() + timeout_s

        while not self._cancel.is_set() and time.time() < deadline:
            time.sleep(poll_s)
            if self._cancel.is_set():
                return False
            try:
                current = grab_region(target_x, target_y, radius=radius).convert("L")
            except Exception:
                continue
            if current.size != baseline.size:
                continue

            diff = ImageChops.difference(baseline, current)
            # Sum of absolute pixel differences, normalized to [0, 1]
            hist = diff.histogram()
            changed = sum(i * hist[i] for i in range(len(hist))) / (baseline_px * 255)
            if changed > diff_threshold:
                print(f"[watch] screen change detected around ({target_x},{target_y}): {changed:.3f}")
                return True

        if not self._cancel.is_set():
            print(f"[watch] timeout at ({target_x},{target_y}) — assuming user moved on")
            return True   # fallback so we don't stall forever
        return False

    def _say_or_show(self, text: str, x: int, y: int) -> None:
        """Speak in voice mode, show bubble in voiceless mode."""
        from src.voice_io import speak
        if self.mode == "voiceless":
            self._bridge.bubble_show.emit(x, y, text)
        else:
            speak(text, block=True)

    def _run_guided(self, mon_left: int, mon_top: int, task: str, image) -> None:
        """Clicky-style adaptive guidance loop. Same logic for voice + voiceless,
        differs only in the I/O edge: TTS vs bubble."""
        from src.ai_client import ask_guided_step
        from src.screen_capture import grab_monitor_at

        voiceless = (self.mode == "voiceless")
        print(f"[guided] starting mode={self.mode} offset=({mon_left},{mon_top})")
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
                spoken, x, y, box, action = ask_guided_step(task, current_image, steps_done)

                if self._cancel.is_set():
                    break

                print(f"[guided] response: {spoken!r}  point=({x},{y}) box={box} action={action}")

                img_w, img_h = current_image.size
                anchor_x, anchor_y = self.cx, self.cy

                # Hide any previous step's overlays before showing new ones
                self._bridge.highlight_hide.emit()

                if x is not None and y is not None:
                    scale = max(img_w, img_h) / 1280 if max(img_w, img_h) > 1280 else 1.0
                    sx = int(x * scale) + current_left
                    sy = int(y * scale) + current_top
                    anchor_x, anchor_y = sx, sy

                    # Dotted footstep path from user's current cursor → target
                    user_x, user_y = self._get_pos()
                    self._bridge.path_show.emit(user_x, user_y, sx, sy)

                    # Action highlight box (if Claude gave one)
                    if box is not None:
                        bx1 = int(box[0] * scale) + current_left
                        by1 = int(box[1] * scale) + current_top
                        bx2 = int(box[2] * scale) + current_left
                        by2 = int(box[3] * scale) + current_top
                        self._bridge.highlight_show.emit(
                            bx1, by1, bx2, by2, action or "click"
                        )

                    print(f"[guided] animating ghost to screen ({sx}, {sy})")
                    self._bridge.guide_to.emit(sx, sy)
                else:
                    self._bridge.guide_hide.emit()

                # Speak or show
                if voiceless:
                    # No auto-hide while waiting for advance — bubble stays until next step or cancel
                    self._bridge.bubble_show.emit(anchor_x, anchor_y, spoken)
                    self.state.emit("idle")
                else:
                    self.state.emit("speaking")
                    from src.voice_io import speak
                    speak(spoken, block=True)

                if x is None:
                    # [POINT:none] — task complete
                    break

                # Manual advance: wait until hotkey sets step_event (or user cancels)
                self.state.emit("idle")
                self.guided_waiting = True
                self._step_event.clear()
                while not self._cancel.is_set() and not self._step_event.is_set():
                    time.sleep(0.05)
                self.guided_waiting = False
                if self._cancel.is_set():
                    break
                self._step_event.clear()

                if voiceless:
                    self._bridge.bubble_hide.emit()
                # Clear previous step's path + highlight once user has acted
                self._bridge.path_hide.emit()
                self._bridge.highlight_hide.emit()

                steps_done.append(spoken)
                time.sleep(0.3)  # brief settle after change detected

                try:
                    cx, cy = self._get_pos()
                    current_image, current_left, current_top = grab_monitor_at(cx, cy)
                    print(f"[guided] re-captured at ({cx},{cy}) offset=({current_left},{current_top})")
                except Exception as e:
                    print(f"[guided] re-capture failed: {e}")
                    break

            self._bridge.guide_hide.emit()
            if voiceless:
                self._bridge.bubble_hide.emit()
            self.exchange.emit(task, "; ".join(steps_done) or "(guided session)")
        finally:
            self.state.emit("idle")
            self.finished.emit()


class CurbyApp:
    def __init__(self):
        self._qt = QApplication.instance() or QApplication(sys.argv)
        self._bridge = _Bridge()
        self._ghost = GhostCursor()
        self._bubble = SpeechBubble()
        self._text_popup = TextInputPopup()
        self._path = GuidePath()
        self._highlight = ActionHighlight()
        self._status = StatusWindow()
        self._cursor = CursorTracker(on_move=self._on_move)
        self._hotkey = keyboard.GlobalHotKeys({
            HOTKEY_VOICE:     self._on_voice_hotkey,
            HOTKEY_VOICELESS: self._on_voiceless_hotkey,
        })
        self._worker: AssistantWorker | None = None
        self._listener: ContinuousListener | None = None
        self._cx = 0
        self._cy = 0
        self._history: list[dict] = []
        self._step_event = threading.Event()
        self._restart_pending = False
        self._pending_mode = "voice"
        self._pending_text: str | None = None
        self._worker_lock = threading.Lock()

        # Ghost is always-visible now; buddy-icon dot is retired (file kept for history).
        self._bridge.cursor_moved.connect(self._ghost.follow)
        self._bridge.voice_hotkey_fired.connect(self._activate_voice)
        self._bridge.voiceless_hotkey_fired.connect(self._activate_voiceless)
        self._bridge.set_state.connect(self._ghost.set_state)
        self._bridge.set_state.connect(self._status.set_state)
        self._bridge.guide_show.connect(self._ghost.show_at)
        self._bridge.guide_to.connect(self._ghost.animate_to)
        self._bridge.guide_hide.connect(self._ghost.release)
        self._bridge.guide_hide.connect(self._path.hide_path)
        self._bridge.guide_hide.connect(self._highlight.hide_highlight)
        self._bridge.bubble_show.connect(self._on_bubble_show)
        self._bridge.bubble_hide.connect(self._bubble.hide)
        self._bridge.text_prompt_show.connect(self._text_popup.show_at)
        self._bridge.path_show.connect(self._path.show_path)
        self._bridge.path_hide.connect(self._path.hide_path)
        self._bridge.highlight_show.connect(self._highlight.show_highlight)
        self._bridge.highlight_hide.connect(self._highlight.hide_highlight)

        self._text_popup.submitted.connect(self._on_voiceless_submitted)

        # Wire TTS so the continuous listener pauses while curby is speaking —
        # otherwise the mic would pick up its own voice.
        from src.voice_io import set_speak_callbacks
        set_speak_callbacks(
            on_start=self._on_speak_start,
            on_end=self._on_speak_end,
        )

    # ── Event handlers ─────────────────────────────────────────────────────────

    def _on_move(self, x, y):
        self._cx, self._cy = x, y
        self._bridge.cursor_moved.emit(x, y)

    def _on_voice_hotkey(self):
        self._bridge.voice_hotkey_fired.emit()

    def _on_voiceless_hotkey(self):
        self._bridge.voiceless_hotkey_fired.emit()

    def _on_bubble_show(self, x: int, y: int, text: str):
        # During guided mode, the bubble should stay until the next step —
        # pass auto_hide_ms=0 when a worker is running in guided waiting.
        auto_hide = 0 if (self._worker and self._worker.isRunning()
                          and self._worker.mode == "voiceless"
                          and self._worker.guided_waiting is False
                          and False) else 6000
        # Simpler: when a voiceless guided session is live, disable auto-hide.
        if (self._worker and self._worker.isRunning()
                and self._worker.mode == "voiceless"):
            auto_hide = 0
        self._bubble.show_text(x, y, text, auto_hide_ms=auto_hide)

    def _on_exchange(self, user_text: str, assistant_reply: str):
        self._history.append({"user": user_text, "assistant": assistant_reply})
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[-MAX_HISTORY:]
        # Show in status window
        if user_text:
            self._status.push_heard(user_text)
        if assistant_reply and assistant_reply != "(guided session)":
            self._status.push_said(assistant_reply)

    # ── Continuous listener ───────────────────────────────────────────────────

    def _listener_running(self) -> bool:
        return self._listener is not None and self._listener.isRunning()

    def _start_listener(self):
        if self._listener_running():
            return
        self._listener = ContinuousListener()
        self._listener.waiting.connect(lambda: self._ghost.set_state("listening"))
        self._listener.waiting.connect(lambda: self._status.set_state("listening"))
        self._listener.captured.connect(self._on_listener_captured)
        self._listener.utterance.connect(self._on_listener_utterance)
        self._listener.listen_error.connect(lambda m: self._status.push_error(m))
        self._listener.start()
        self._status.push_status("listening — talk to me anytime.")
        from src.voice_io import speak
        speak("listening.")

    def _stop_listener(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener.quit()
            self._listener = None
        self._ghost.set_state("idle")
        self._status.set_state("idle")
        self._status.push_status("paused. tap the hotkey to turn me back on.")
        from src.voice_io import speak
        speak("stopped listening.")

    def _on_listener_captured(self, text: str):
        self._status.set_state("thinking")
        self._status.push_heard(text)
        self._ghost.set_state("thinking")

    def _on_listener_utterance(self, text: str):
        # Cancel anything in flight — user spoke, new intent wins
        with self._worker_lock:
            if self._worker and self._worker.isRunning():
                self._worker._cancel.set()
                self._restart_pending = False
                self._bridge.guide_hide.emit()
                self._bridge.bubble_hide.emit()
        # Kick off a worker with the transcribed text
        self._start_worker(mode="voice", heard_text=text)

    def _on_speak_start(self):
        # Pause the mic while curby is talking so it doesn't hear itself
        if self._listener is not None:
            self._listener.pause()

    def _on_speak_end(self):
        # Resume mic, unless a worker is still processing
        if (self._listener is not None
                and not (self._worker and self._worker.isRunning())):
            self._listener.resume()

    def _on_worker_finished(self):
        with self._worker_lock:
            restart = self._restart_pending
            self._restart_pending = False
        # Resume the continuous listener once the worker is done processing
        if self._listener is not None and not self._listener.is_paused():
            pass  # already unpaused
        elif self._listener is not None:
            self._listener.resume()
        if restart:
            self._start_worker(self._pending_mode, self._pending_text)

    # ── Worker lifecycle ───────────────────────────────────────────────────────

    def _start_worker(self, mode: str = "voice",
                      typed_text: str | None = None,
                      heard_text: str | None = None):
        with self._worker_lock:
            w = AssistantWorker(
                self._cx, self._cy, self._history,
                self._bridge, self._step_event,
                get_pos=lambda: (self._cx, self._cy),
                mode=mode,
                typed_text=typed_text,
                heard_text=heard_text,
            )
            w.state.connect(self._ghost.set_state)
            w.state.connect(self._status.set_state)
            w.exchange.connect(self._on_exchange)
            w.finished.connect(self._on_worker_finished)
            self._worker = w
        w.start()

    def _activate_voice(self):
        """Hotkey behavior:
          - guided session waiting  → ADVANCE step
          - worker running (not waiting) → cancel it
          - no worker, listener running  → stop listener (pause always-on mode)
          - no worker, listener stopped  → start listener (begin always-on mode)
        """
        with self._worker_lock:
            w = self._worker
            running = w is not None and w.isRunning()
            waiting = running and w.guided_waiting

        if waiting:
            self._step_event.set()
            return

        if running:
            with self._worker_lock:
                self._worker._cancel.set()
                self._restart_pending = False
            self._bridge.guide_hide.emit()
            self._bridge.bubble_hide.emit()
            self._ghost.set_state("idle")
            self._status.set_state("idle")
            # Resume the listener so the next utterance is captured
            if self._listener is not None:
                self._listener.resume()
            return

        if self._listener_running():
            self._stop_listener()
        else:
            self._start_listener()

    def _activate_voiceless(self):
        """Hotkey behavior:
          - guided session waiting for next step → ADVANCE
          - running non-guided → cancel
          - idle → open text input popup
        """
        with self._worker_lock:
            w = self._worker
            running = w is not None and w.isRunning()
            waiting = running and w.guided_waiting

        if waiting:
            self._step_event.set()
            return

        if running:
            with self._worker_lock:
                self._worker._cancel.set()
                self._restart_pending = False
            self._bridge.guide_hide.emit()
            self._bridge.bubble_hide.emit()
            self._ghost.set_state("idle")
            return

        self._bridge.text_prompt_show.emit(self._cx, self._cy)

    def _on_voiceless_submitted(self, text: str):
        if not text:
            return
        self._start_worker(mode="voiceless", typed_text=text)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def run(self):
        from PyQt6.QtGui import QCursor
        from src.voice_io import speak
        pos = QCursor.pos()
        self._cx, self._cy = pos.x(), pos.y()
        self._ghost.follow(self._cx, self._cy)

        # Status window appears in top-right by default
        self._status.place_default()
        self._status.show()
        self._status.push_status(f"tap {HOTKEY_VOICE} to start listening.")

        self._cursor.start()
        self._hotkey.start()
        speak("curby ready.")
        print(f"Curby ready.")
        print(f"  Voice (always-listen): tap {HOTKEY_VOICE}  (again to stop)")
        print(f"  Type prompt:           tap {HOTKEY_VOICELESS}")
        print(f"  Advance guided step:   tap {HOTKEY_VOICE} or {HOTKEY_VOICELESS}")
        code = self._qt.exec()
        if self._listener is not None:
            self._listener.stop()
        self._cursor.stop()
        self._hotkey.stop()
        return code
