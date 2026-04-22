# Curby — design

A single-process Python desktop app. PyQt6 draws the UI, pynput handles global hotkeys and mouse tracking, mss grabs screenshots, Claude (via CLI or direct API) reads the screen and produces each guidance step. All overlays are frameless, always-on-top, click-through.

---

## Architecture at a glance

```
                  ┌──────────────────────────────────────┐
                  │              CurbyApp                │
                  │  (QApplication + signal _Bridge)     │
                  └──────┬───────────────────────────────┘
                         │ Qt signals
   ┌─────────────────────┼─────────────────────┬───────────────┐
   │                     │                     │               │
   ▼                     ▼                     ▼               ▼
CursorTracker     GlobalHotKeys            AssistantWorker   TextInputPopup
(pynput bg)       (pynput bg)              (QThread)        (on voiceless)
   │                     │                     │
   │ cursor_moved        │ hotkey_fired        │ produces guidance steps
   ▼                     ▼                     │
 GhostCursor ◄──────── app.py routes ──────────┤
 GuidePath                                     │
 ActionHighlight                               │
 SpeechBubble ◄────────────────────────────────┘
```

Four visual widgets, all frameless + translucent + click-through:

| Widget | Role |
|---|---|
| **GhostCursor** (`src/ghost_cursor.py`) | The fairy. Always visible. Follow mode floats beside the cursor with ambient bob; pointing mode anchors to a guidance target. |
| **GuidePath** (`src/guide_path.py`) | A dotted bezier from the user's cursor to the current target. Full-screen overlay; dots light up sequentially as the fairy moves. |
| **ActionHighlight** (`src/action_highlight.py`) | Rounded-rectangle reticle around the element to act on. Corner brackets + pulsing glow + action badge. |
| **SpeechBubble** (`src/speech_bubble.py`) | Floating dark bubble with gradient border, carries the instruction text. Tail points at the target. |

Plus **TextInputPopup** (`src/text_input_popup.py`) for voiceless mode — the only widget that takes keyboard focus, and only while accepting a prompt.

---

## State & modes

Two orthogonal axes:

**Mode** — where the fairy is anchored.
- `follow` — tracks the user's cursor with spring damping + ambient bob
- `pointing` — anchored to a guidance target; ambient motion replaced with lean

**State** — what curby is doing.
- `idle` — waiting
- `listening` — capturing voice input
- `thinking` — waiting on Claude's response
- `speaking` — playing back TTS
- `error` — something failed

Modes and states are independent. A common combination is `pointing + listening` (user asked for a clarification mid-animation) — the fairy keeps its cool-blue pointing body and adds a subtle pink ripple at the tip.

---

## Component contracts

### `CurbyApp` — `src/app.py`

Owns the Qt application, the signal bridge, all widgets, the cursor tracker, the global-hotkey listener, and the worker lifecycle. Single point that wires everything together. Does not itself do I/O with Claude or the screen — it delegates to `AssistantWorker`.

Key methods:
- `_activate_voice()` / `_activate_voiceless()` — hotkey handlers. Check guided-waiting state and either advance (`self._step_event.set()`) or start a new session.
- `_run_guided()` — (on the worker) main loop per guided session. Grabs a screenshot, asks Claude for the next step, emits signals to position the overlays, waits on `step_event`, re-captures, repeats.

### `AssistantWorker` — `src/app.py`

`QThread`. Per-session. Holds cancel and step events. Two paths:

1. **Conversational** — single-shot Q&A (voice or voiceless). Captures the region around the cursor, asks Claude for a reply, plays TTS (voice) or shows a bubble (voiceless).
2. **Guided** — multi-step flow. Triggered by keyword detection (see `_is_guided` in `app.py`). Loops up to 10 steps. Uses monitor-size screenshots (not region) so targets anywhere on the active screen can be pointed at.

### AI dispatch — `src/ai_client.py`

One entry point: `ask_guided_step(task, image, steps_done) -> (text, x, y, box, action)`.

Internally picks between:
- **API path** (`src/ai_client_api.py`) — direct Anthropic SDK call with `tools=[{"type": "computer_20250124"}]` and the `anthropic-beta: computer-use-2025-01-24` header. Screenshot is resized to an aspect-matched Computer Use resolution (1280×800 / 1366×768 / 1024×768). Claude's `tool_use` block is parsed for the pixel coordinate; synthesized default 36×36 box around it.
- **CLI path** — pipes image + prompt to `claude.exe -p --input-format stream-json --output-format stream-json`. System prompt constrains output to a single-line trailing-tag format: `… [POINT:x,y:label] [BOX:x1,y1,x2,y2] [ACTION:click|type|close|select|drag|open]`.

Returns `[POINT:none]` / `(None, None, None, None, None)` when the task is already complete or the next step isn't on the current screen.

### `GhostCursor` — `src/ghost_cursor.py`

Paints the fairy every frame (16 ms timer). Public API:

```python
follow(x, y)        # user cursor moved — drift toward (x + offset, y + offset)
set_state(state)    # update accent color family
show_at(x, y)       # hard place at (x, y), enter pointing mode
animate_to(x, y)    # snap to user's cursor, then ease to (x, y)
release()           # return to follow mode (stay visible)
```

Key behaviors:
- **Spring follow**: `smoothed += (target - smoothed) * 0.14` each frame
- **Ambient bob**: two sines on X + Y + a wobble sine, amplitudes ~9/6/2.6 px
- **Idle-bored**: after 0.9 s without cursor movement, adds lazy secondary bobbing
- **Every pointing animation starts from the user's cursor position** (not from wherever the ghost last landed), for a consistent "from here to there" read
- **Per-screen clamp**: uses `QApplication.screenAt()` to keep the widget on the monitor the cursor is on

Rendering order each frame:
1. Ambient + burst sparkles behind everything
2. Background rings or voice-ripples (state-dependent)
3. Soft radial halo
4. Swoosh body (with rotation / scale per state)
5. Gold shimmer overlay (thinking only)
6. Highlight sliver (always)
7. Tip glow (always)
8. Mid-animation listening underscore (pointing + listening combo)
9. Mode-change flash (first 450 ms after mode switch)

### `GuidePath` — `src/guide_path.py`

Full-screen widget covering the virtual desktop. On `show_path(sx, sy, ex, ey)`:
- Computes a gentle quadratic bezier from start to end
- Samples 44 points along it
- Paints each as a small white core + sky-blue halo
- Dots behind the fairy's progress (measured by `(now - t_start) / 0.95`) glow brighter; dots ahead stay dim
- Destination gets a pulsing indigo beacon
- Holds for 1.8 s after arrival, fades out over 0.5 s

### `ActionHighlight` — `src/action_highlight.py`

Full-screen widget. On `show_highlight(x1, y1, x2, y2, action)`:
- Draws a rounded rectangle with a 2.4 px gradient stroke
- Pulsing outer glow (breathing alpha at 3.4 Hz)
- Corner brackets for a "targeting reticle" feel
- Action badge in the corner: `CLICK` / `TYPE` / `CLOSE` / `SELECT` / `DRAG` / `OPEN`
- Accent color varies by action (red for close, pink/indigo for type, mint for drag/open, sky/blue default)
- Auto-hides after 12 s if not explicitly cleared

---

## Threading model

```
Main (Qt) thread     : all widget painting + signals
pynput tracker thread: mouse position → bridge.cursor_moved → main
pynput hotkey thread : hotkeys → bridge.voice/voiceless_hotkey_fired → main
AssistantWorker QThread : per-session; captures, calls Claude, emits bridge signals → main
Audio playback thread   : TTS (voice mode only)
```

Rules:
- Workers never touch widgets directly. Every cross-thread update goes through `_Bridge` `pyqtSignal` emissions, which Qt queues to the main thread.
- Cancel is a `threading.Event` checked in every worker loop iteration.
- Advance (guided) is a separate `threading.Event`. Main thread sets it when the hotkey is pressed while a session is waiting.

---

## Visual pipeline — a guided step, end to end

```
user presses Ctrl+.
  ↓
text popup receives input, CurbyApp.start_worker('voiceless', text)
  ↓
AssistantWorker launches, _is_guided(text) is True
  ↓
bridge.guide_show.emit(cursor_x, cursor_y) → GhostCursor enters pointing mode
  ↓
loop: step_num in range(10)
  │
  │   state=thinking → GhostCursor shows gold shimmer + breath
  │
  │   grab_monitor_at(cursor)
  │   ask_guided_step(...)  → (text, x, y, box, action)
  │
  │   scale coords, offset by monitor origin
  │   bridge.highlight_hide.emit()   # clear previous step
  │   bridge.path_show.emit(user_x, user_y, sx, sy)
  │   bridge.highlight_show.emit(bx1, by1, bx2, by2, action)
  │   bridge.guide_to.emit(sx, sy)   # animate ghost
  │   bridge.bubble_show.emit(sx, sy, text)
  │
  │   state=idle, wait on step_event
  │   ← hotkey press → step_event.set() → advance
  │
  │   bridge.path_hide.emit()
  │   bridge.highlight_hide.emit()
  │
  │   re-capture screen, next iteration
  ↓
loop ends (POINT:none or step cap)
  ↓
bridge.guide_hide.emit() → GhostCursor.release(), path.hide, highlight.hide
```

---

## Palette

Single coherent accent system across all widgets.

| Token | Hex | Use |
|---|---|---|
| pink-hot | `#EC4899` | fairy body, listening ripples |
| pink-soft | `#F472B6` | fairy body, sparkle |
| rose | `#FB7185` | fairy body end-stop |
| fuchsia | `#D946EF` | listening palette |
| violet | `#A78BFA` | idle rings |
| blue | `#60A5FA` | idle rings |
| sky-300 | `#7DD3FC` | pointing body start, footstep trail |
| blue-500 | `#3B82F6` | pointing body mid |
| indigo-600 | `#4F46E5` | pointing body end, path beacon |
| mint | `#34D399` | speaking rings, drag/open action |
| gold | `#FDE047` | thinking shimmer |
| amber | `#FBBF24` | thinking rings |
| red | `#EF4444` | close action, error |
| white-hot | `#FFFFFF` | tip glow, path dot cores |

---

## File layout

```
src/
├── app.py                  CurbyApp + AssistantWorker + _Bridge + hotkey wiring
├── ai_client.py            CLI dispatch, prompt templates, tag parser
├── ai_client_api.py        Anthropic SDK + Computer Use path
├── ghost_cursor.py         The fairy widget
├── guide_path.py           Dotted path overlay
├── action_highlight.py     Target reticle overlay
├── speech_bubble.py        Instruction bubble widget
├── text_input_popup.py     Voiceless text input widget
├── screen_capture.py       mss-based region / monitor captures
├── cursor_tracker.py       pynput cursor listener → Qt signal
├── voice_io.py             Mic capture, STT, TTS
└── buddy_icon.py           (retired — kept for reference only, not imported)
```
