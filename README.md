# Curby

A desktop AI companion that lives on your screen, watches what you're doing, and walks you through UI tasks one step at a time. A small glowing fairy floats beside your cursor. When you ask for help, it animates across the screen to show you exactly what to click next.

Voice or text. One hotkey. Works in any Windows app.

---

## Quick start

**Prereqs** — Windows 10 / 11, Python 3.14, [Claude CLI](https://docs.anthropic.com/en/docs/claude-code) installed (`claude.exe` on PATH).

```powershell
git clone https://github.com/CasterlyGit/curby---the-cursor-buddy.git
cd curby---the-cursor-buddy
pip install -r requirements.txt
python main.py
```

The fairy appears next to your cursor. A short "curby ready" will play.

---

## How to use

### Voice mode — `Ctrl+/`

Press the hotkey, speak your question, stop talking. Curby captures your screen, hears you out, and answers aloud.

> _"what does this button do?"_
> _"summarize what's on screen"_
> _"where do I add a breakpoint?"_

### Voiceless mode — `Ctrl+.`

For libraries, meetings, shared spaces. Press the hotkey, type your question, press Enter. Curby answers in a floating speech bubble that auto-dismisses.

> _"what's this dialog asking?"_
> _"explain this error"_

### Guided mode — ask a "how do I…" question

```
how do I enable dark mode in vs code?
```

The fairy animates from your cursor to the first target. A dotted path shows the route; a highlighted box marks the thing to touch; a speech bubble tells you what to do and why.

Do the step yourself. Then press the hotkey again — the fairy re-reads the screen, speaks the next step, and sweeps to the new target. Repeat until the task is done.

---

## What you see on screen

| Element | When | What it does |
|---|---|---|
| **Fairy** (pink swoosh, swaying) | always | floats beside your cursor, never blocks input |
| **Voice ripples** (concentric warm rings) | listening | a curated warm palette cycles — curby is hearing you |
| **Gold shimmer + breath** | thinking | curby is asking Claude |
| **Cool blue-indigo body** | guiding | the fairy is animating to a target |
| **Dotted path** | guiding | a tight line from your cursor to the target |
| **Outlined box + action badge** | guiding | rings the exact element with a CLICK / TYPE / CLOSE / … label |
| **Speech bubble** | guiding | the instruction in plain words, with a tail pointing at the target |
| **Mini pink ripple at tip** | mid-animation listening | curby is still guiding and can also hear a clarification |

Nothing is clickable. Every overlay is click-through — your mouse goes straight to the app underneath.

---

## Hotkeys

| | Voice mode | Voiceless mode |
|---|---|---|
| Idle | `Ctrl+/` starts a voice session | `Ctrl+.` opens a text input near cursor |
| Thinking / speaking | `Ctrl+/` cancels + restarts | `Ctrl+.` cancels |
| Guided session waiting | `Ctrl+/` advances to next step | `Ctrl+.` advances to next step |
| Text input open | — | `Esc` cancels, `Enter` submits |

---

## Accuracy modes

Curby picks its brain automatically:

- **API + Computer Use** — if `ANTHROPIC_API_KEY` is set in your environment, curby calls Claude directly with the pixel-calibrated Computer Use tool. Coordinates land dead-center.
- **CLI fallback** — otherwise curby pipes screenshots and prompts to `claude.exe`. Coordinates are vision-estimated; accuracy depends on the app and Claude's read of the screen.

To switch on the accurate path:

```powershell
setx ANTHROPIC_API_KEY "sk-ant-…"   # opens new shells with it set
# …or for this shell only:
$env:ANTHROPIC_API_KEY = "sk-ant-…"
python main.py
```

Model selection (default `claude-sonnet-4-5`):

```powershell
$env:CURBY_MODEL = "claude-opus-4-5"
```

---

## Multi-monitor

Curby clamps the fairy to the screen your real cursor is currently on — it can cross between monitors but won't drift into dead zones. Guidance captures only the screen the cursor is on when you start the session.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Fairy doesn't appear | `claude.exe` not on PATH | `where claude` — install the Claude CLI and re-open the shell |
| Nothing happens on hotkey | another app grabbed `Ctrl+/` or `Ctrl+.` | run curby from an elevated shell, or change the hotkey in `src/app.py` |
| "couldn't capture the screen" | Windows privacy settings blocked screen access | System Settings → Privacy → Graphics → allow desktop apps |
| Pointer lands near but not on target | CLI path (vision-estimate) | set `ANTHROPIC_API_KEY` for pixel-exact Computer Use path |
| Voice mode hears nothing | microphone blocked or wrong default input | Settings → Privacy → Microphone; check default input device |

---

## Docs

- **[design.md](design.md)** — architecture, components, threading, visual pipeline
- **[MANAGERS_GUIDE.md](MANAGERS_GUIDE.md)** — what curby is, who it's for, a visual walkthrough

---

## License

MIT.
