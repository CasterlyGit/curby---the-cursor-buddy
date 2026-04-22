# Curby — the cursor buddy

A desktop AI assistant that lives near your mouse cursor. Press a hotkey, ask a question, get an answer grounded in what's on your screen right now. Works in **voice mode** (speak / hear) or **voiceless mode** (type / read) — same brain, pick whichever fits the room.

For the full architecture, see [`design.md`](./design.md).

---

## Requirements

- Windows 10 / 11
- Python 3.14
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) on PATH (`claude.exe`) — fallback path
- (Recommended) `ANTHROPIC_API_KEY` env var — enables Claude's **Computer Use** tool for pixel-calibrated guidance. Much more accurate than the CLI fallback; use this for real daily use.
- Microphone + speakers (voice mode only)

### Accuracy modes

| mode | activation | accuracy |
|---|---|---|
| **API + Computer Use** (recommended) | `setx ANTHROPIC_API_KEY sk-ant-…` in a new shell | pixel-exact |
| **CLI fallback** | default, no env var | vision-guess, ~30–80 px drift on complex UIs |

Model selection: export `CURBY_MODEL=claude-sonnet-4-5` (default) or set a different model id.

Install dependencies:
```powershell
pip install -r requirements.txt
```

## Run

```powershell
$env:PATH += ';C:\Users\tarun\.local\bin'
cd C:\Users\tarun\dev\cursor_buddy
python main.py
```

You'll hear "curby ready" and a small grey dot will appear near your cursor — that's Curby waiting for a hotkey.

---

## How to try voice mode

**Hotkey:** `Ctrl+/`

1. Press `Ctrl+/` — the dot turns orange (listening).
2. Speak a question, e.g. _"what's in this window?"_
3. Stop talking — Claude replies out loud.

### Try a guided request
Ask Curby to walk you through a UI task:

> _"how do I bold text in this app"_

- The ghost cursor animates to the first target and speaks the step.
- Do the step yourself.
- **Press `Ctrl+/` (voice) or `Ctrl+.` (voiceless) again to advance to the next step.** Curby re-captures your screen and guides you to the next target.
- Repeat until done. To cancel mid-flow, press the hotkey while curby is still thinking (before a step bubble appears).

### Example voice prompts
- _"what does this button do?"_
- _"summarize what's on screen"_
- _"how do I create a new file here?"_
- _"where do I click to add a breakpoint?"_

---

## How to try voiceless mode

For libraries, meetings, or shared spaces. **No mic, no speakers needed.**

**Hotkey:** `Ctrl+.`

1. Press `Ctrl+.` — a small text box pops up near your cursor.
2. Type your question, press `Enter`.
3. A speech bubble appears near the cursor with Claude's reply. It auto-dismisses after ~6 seconds, or press `Ctrl+.` again to dismiss early.
4. Press `Esc` in the text box to cancel without sending.

### Guided voiceless
Type a "how do I…" question and Enter:

> _"how do I open settings"_

- The ghost cursor animates to the target and pulses.
- A floating speech bubble appears **next to the ghost** (with a tail pointing at it) with the written instruction. The bubble doesn't block clicks — you can interact with anything underneath it.
- Do the step yourself.
- **Press `Ctrl+.` again to advance to the next step.** Curby re-captures the screen and guides you onward.
- Press `Ctrl+.` while curby is thinking (before a new bubble appears) to cancel.

### Example voiceless prompts
(Same as voice — same brain.)
- _"what is this dialog asking?"_
- _"where do I click to add a breakpoint?"_
- _"explain this error"_
- _"walk me through adding a new file"_

---

## Hotkey behavior

While a guided session is **waiting for you** (step shown, bubble visible):
- `Ctrl+/` or `Ctrl+.` → **advance to the next step**.

While curby is **thinking / speaking / transcribing**:
- `Ctrl+/` → cancel + immediately restart fresh voice session.
- `Ctrl+.` → cancel, return to idle (press again to start a new voiceless session).

When curby is **idle**:
- `Ctrl+/` → start a voice session.
- `Ctrl+.` → open the text input popup.

---

## Architecture at a glance

```
Hotkey → _Bridge signal → CurbyApp._activate_voice / _voiceless
              ↓
      AssistantWorker (QThread)
         mode = "voice" | "voiceless"
              ↓
   listen_once  OR  typed_text  (input)
              ↓
   grab_monitor_at / grab_region
              ↓
   ask_stream  OR  ask_guided_step  (Claude CLI subprocess, streaming)
              ↓
   speak()  OR  bubble.show_text()  (output)
```

Both modes share 95% of the code — only the input acquisition and output rendering differ at the edges. See [`design.md`](./design.md) for the full state diagram and per-module notes.

---

## Roadmap
- [x] Multi-turn conversation history
- [x] Guided cursor (Clicky-style adaptive per-screenshot loop)
- [x] Voiceless mode with floating speech bubble
- [x] Auto-advance via screen-change detection (no key press between steps)
- [ ] UIA-tree element resolution (stable across DPI / window moves)
- [ ] MPLAB / IDE context injection
