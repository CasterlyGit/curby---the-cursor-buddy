# Curby — the cursor buddy — Design Document
_Last updated: session 4 — guided phantom cursor route_

---

## START HERE (next session)

**What this is:** Home MVP of an AI voice assistant that follows your cursor. Goal is to eventually bring it into MPLAB/MCC at Microchip as a guided assistant. Testing the concept here first.

**It works.** Run it with:
```powershell
$env:PATH += ';C:\Users\tarun\.local\bin'
cd C:\Users\tarun\dev\cursor_buddy
python main.py
```
Press `Ctrl+Shift+Space`, speak a question, Claude answers out loud. The dot near your cursor shows state.

**What to build next (in order):**
1. ~~Multi-turn conversation~~ — DONE (session 3)
2. ~~Guided cursor mode~~ — DONE (session 4)
3. MPLAB detection — detect foreground window, inject context into AI prompt

**Codebase is at:** `C:\Users\tarun\dev\cursor_buddy\`

---

## HIGH LEVEL

### What it is
A desktop AI voice assistant that lives near your mouse cursor. Press a hotkey, speak a question, and Claude answers out loud — seeing exactly what's on your screen at the cursor position. No typing, no panel, no friction.

Long-term target: bring this into MPLAB/MCC at Microchip — guided walkthroughs where a ghost cursor shows the user what to click, context-aware help for firmware configuration. This repo is the home MVP.

### What works right now
- Tiny glowing dot follows cursor (click-through, never blocks anything)
- `Ctrl+Shift+Space` activates — Claude listens to your voice
- Silence detection stops recording automatically when you stop talking
- Screenshot auto-grabbed at cursor position the moment you activate
- Claude sees the screenshot + hears your question, answers out loud via TTS
- Dot animates color to show state: gray=idle, orange=listening, blue=thinking, green=speaking, red=error

### What's next (priority order)
1. **Guided cursor mode** — ghost cursor overlay that animates to show where to click
2. **MPLAB/MCC integration** — detect foreground window, inject tool/peripheral context into prompt
3. **Conversation memory** — multi-turn within a session, not just single-shot Q&A
4. **Wake word** — replace hotkey with "Hey Buddy" always-on listening
5. **Window confinement** — optionally restrict buddy to one app window

---

## MEDIUM LEVEL

### Stack
| Concern | Library | Notes |
|---|---|---|
| UI overlay | PyQt6 6.11 | Frameless, always-on-top, transparent windows |
| Mouse tracking | pynput 1.8 | Listener thread, signals to Qt main thread |
| Global hotkey | pynput GlobalHotKeys | Daemon thread, system-wide |
| Screen capture | mss 10.1 | Fast region grab, PIL Image output |
| Audio recording | sounddevice 0.5 + scipy | Avoids pyaudio (needs C++ build tools on Win) |
| Speech-to-text | SpeechRecognition 3.16 | Google Web Speech API, needs internet |
| Text-to-speech | pyttsx3 2.99 | Windows SAPI5, fully offline |
| AI | claude CLI subprocess | stream-json stdin/stdout, uses existing Claude Code OAuth |
| Python | 3.14.4 | Via Microsoft Store / py launcher |
| Tests | pytest 9.0 + pytest-qt | `python -m pytest tests/ -v` |

### Module map
```
main.py                     entry point, sets UTF-8 stdout/stderr
src/
  app.py                    orchestrator — VoiceWorker, hotkey, cursor tracking
  cursor_tracker.py         pynput mouse listener, fires on_move(x,y) callback
  screen_capture.py         grab_region(x,y,radius) -> PIL Image, clamps to screen edges
  ai_client.py              ask(text, image) -> claude CLI via subprocess, parses stream-json
  voice_io.py               listen_once() -> transcribed str / speak(text) -> SAPI5 TTS
  buddy_icon.py             22px click-through animated dot, 5 states
  chat_panel.py             OLD — replaced by voice, keep as reference or delete
  buddy_window.py           OLD — from phase 1, not used
tests/
  test_integration.py       screen capture, cursor tracker, window positioning, AI (needs PATH)
```

### Full voice flow
```
Ctrl+Shift+Space pressed
  -> pynput GlobalHotKeys callback (listener thread)
    -> _Bridge.hotkey_fired signal (crosses to Qt main thread)
      -> CurbyApp._activate()
        -> VoiceWorker(cx, cy).start()

VoiceWorker.run() [QThread]:
  icon = "listening"
  listen_once()              <- sounddevice mic, silence detection, Google STT
  icon = "thinking"
  grab_region(cx, cy, 500)  <- screenshot of 1000x1000 around cursor
  ask(text, image)           <- claude CLI subprocess, stream-json with base64 image
  icon = "speaking"
  speak(reply)               <- pyttsx3 SAPI5 TTS, non-blocking daemon thread
  icon = "idle"
```

### How to run
```powershell
# In PowerShell (not bash — Python/claude not in bash PATH)
$env:PATH += ';C:\Users\tarun\.local\bin'
cd C:\Users\tarun\dev\cursor_buddy
python main.py
```

### How to test
```powershell
$env:PATH += ';C:\Users\tarun\.local\bin'
cd C:\Users\tarun\dev\cursor_buddy
python -m pytest tests/ -v
```

---

## LOW LEVEL

### Key implementation details

**Claude CLI auth**
No API key needed. Claude Max subscription. CLI at `C:\Users\tarun\.local\bin\claude.exe` uses OAuth token in `~/.claude/.credentials.json`. The `ask()` function in `ai_client.py` pipes a stream-json message to the CLI with `--system-prompt` and `--input-format stream-json --output-format stream-json --verbose`. Parses stdout line-by-line for `{"type":"assistant",...}` to extract reply text.

**ai_client.py flag gotcha**
The claude CLI flag is `--system-prompt`, NOT `--system`. The latter doesn't exist and silently fails with "unknown option".

**Audio: why not pyaudio**
pyaudio requires Microsoft C++ Build Tools to compile on Windows. Uses sounddevice instead. `listen_once()` records 100ms chunks, checks RMS against `SILENCE_THRESHOLD=500`, stops after 1.5s of silence post-speech. Max cap 15s. Writes temp WAV, passes to SpeechRecognition for Google transcription, deletes temp file.

**TTS sanitization**
All text passed to `speak()` is stripped to ASCII via `encode("ascii", errors="ignore")`. SAPI5 says "unknown character" out loud for any non-ASCII it can't pronounce. Exception messages (from sounddevice/PortAudio or Google STT) often contain Unicode — never pass them raw to speak().

**BuddyIcon QColor alpha bug (fixed)**
`self._pulse` floats between 0.0–1.0 but can overshoot by ~0.04 before the clamp in `_tick()`. `120 + 135 * 1.04 = 260` — Qt rejects alpha > 255. Fixed by clamping in `paintEvent`: `max(0.0, min(1.0, self._pulse))`.

**Thread safety**
pynput callbacks are on listener threads. All Qt widget interaction goes through `_Bridge(QObject)` pyqtSignals. Never touch QWidget methods directly from pynput or VoiceWorker threads. VoiceWorker inherits QThread and emits signals for state changes.

**pyqtSlot decorator bug**
`@pyqtSlot()` on `_activate()` caused `TypeError: connect() failed` with PyQt6 6.11 + Python 3.14. Removed the decorator — plain method connection works fine.

**Python PATH**
Python 3.14 and `claude.exe` are not in bash/git-bash PATH but are in PowerShell. Always launch from PowerShell. To fix permanently: System Properties > Environment Variables > User PATH, add:
- `C:\Users\tarun\.local\bin` (claude CLI)
- `C:\Users\tarun\AppData\Local\Python\pythoncore-3.14-64\` (python.exe)
- `C:\Users\tarun\AppData\Local\Python\pythoncore-3.14-64\Scripts\` (pip, pytest)

**Screen setup**
User has 6000x1600 virtual desktop (likely dual/triple monitor). `mss.monitors[0]` covers full virtual screen. grab_region clamps so capture never goes off any edge.

**Startup positioning**
On launch, icon is placed at current cursor position via `QCursor.pos()` before the pynput listener fires its first event, preventing the icon from starting at (0,0).

**TTS idle timing**
After `speak()` fires (non-blocking), icon is set to "idle" after 0.5s sleep in VoiceWorker. This is approximate — TTS runs in a daemon thread and may still be speaking. Good enough for MVP; proper fix would be a TTS completion callback.

### Known issues / TODOs
- TTS idle return is approximate (0.5s hardcoded, not tied to actual TTS completion)
- STT requires internet (Google Web Speech API)
- Conversation history kept in memory (up to 10 turns); clears on app restart
- `chat_panel.py` and `buddy_window.py` are dead code
- SILENCE_THRESHOLD=500 may need tuning per microphone/environment
- `VoiceWorker` not cancelled if user presses hotkey while already running (silently ignored)

### Next session starting points
1. **Multi-turn conversation** — keep a `messages: list` in `CurbyApp`, pass history to `ask()` each turn
2. **Guided cursor** — new `src/ghost_cursor.py`, frameless overlay that moves a semi-transparent arrow via `QPropertyAnimation` to demonstrate UI steps
3. **MPLAB detection** — `import win32gui; win32gui.GetWindowText(win32gui.GetForegroundWindow())` to detect MPLAB, append tool/peripheral context to the system prompt
4. **Better idle sync** — pyttsx3 has an `on_end_utterance` event; use it to emit the idle signal accurately
