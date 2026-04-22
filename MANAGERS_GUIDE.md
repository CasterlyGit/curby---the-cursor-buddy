# Curby — at a glance

**A friendly AI companion that sits next to the user's cursor and walks them through any UI task on their computer.**

Hit a hotkey, ask _"how do I…"_, and a gentle animated fairy glides across the screen to show the user what to click — step by step, in plain language, in whatever app they're already using.

---

## The pitch

Today, learning a new app means watching a YouTube tutorial, searching help docs, or asking a coworker to share their screen. Curby collapses that loop. The user stays in their app. Curby reads the screen, speaks the next step, and points at exactly where to click. The user does the step, taps the hotkey, and curby walks them to the next one.

No tab switching. No docs. No context loss.

---

## Who it's for

| Audience | Why it matters |
|---|---|
| **New employees** onboarding into internal tools | "Here's how to file an expense report" → real-time on-screen walk-through |
| **Customer support** teams training on CRMs, ticketing, telemetry dashboards | Fewer "click the third tab from the left" phone calls |
| **Users of complex desktop software** (IDEs, design tools, finance apps) | Context-aware help without reading the manual |
| **Accessibility** scenarios | Voice input, clear visual cues, spoken guidance |

---

## What it looks like

```
   ┌────────────────────────────────────────────────────────────┐
   │                    user's actual app                       │
   │                                                             │
   │        ◯  ← user's cursor                                  │
   │          ╲                                                  │
   │           ╲  · · · · · · · · · · ·  ← dotted fairy path    │
   │            ╲                       ·                        │
   │             ╲                      ·                        │
   │              ╲                     ·                        │
   │               ╲                    ▼                        │
   │                ✦  ← fairy          ┌──────────┐             │
   │                                    │ Settings │             │
   │                                    └──────────┘             │
   │                                     ↑                       │
   │                      highlighted element + CLICK badge      │
   │                                                             │
   │     "open the gear in the sidebar — settings live in there" │
   │      └─ spoken (voice mode) or floating bubble (text mode) ┘│
   └────────────────────────────────────────────────────────────┘
```

On screen, the user sees **four things** during a guided step:

1. **The fairy** — a small glowing swoosh that glides from the user's cursor to the target element along a curved path.
2. **A dotted path** — a tight line of fading white-blue dots showing the route the fairy is taking. Reads as "follow this."
3. **A highlighted box** — rounded rectangle around the exact element to act on, with corner brackets (targeting-reticle feel) and an action badge (`CLICK`, `TYPE`, `CLOSE`, `SELECT`, etc.).
4. **A short instruction** — two sentences max, conversational. What to do + a tiny nudge of context.

Everything is click-through. Nothing blocks the app the user is actually working in.

---

## How the user interacts

There are two ways to talk to curby — both work in every app.

### Voice mode — `Ctrl + /`

```
press Ctrl+/         speak your question       stop speaking
     │                       │                       │
     ▼                       ▼                       ▼
  fairy                voice ripples            fairy animates
  listens              (warm pink cycling       to first target,
                        rings around tip)       speaks the step
```

### Voiceless mode — `Ctrl + .`

For libraries, open offices, meetings.

```
press Ctrl+.         type your question        press Enter
     │                       │                       │
     ▼                       ▼                       ▼
  text box               "how do I change
  pops up near            my profile photo"
  cursor                                          fairy animates,
                                                  bubble shows step
```

### Advancing through a guided task

After the user does the step themselves (clicks the thing curby pointed at), they press **the same hotkey again** to move to the next step. Curby re-reads the screen, figures out what's next, and walks them there.

---

## What's clever

| Capability | Why it matters |
|---|---|
| **Reads the actual screen** | Not tied to any one app. Works in VS Code, Figma, Chrome, Excel — anything you can screenshot. |
| **Calibrated pointing** | Uses Claude's Computer Use tool (when an API key is provided) for pixel-exact coordinates. Falls back to vision-estimated coordinates via the Claude CLI when no key is set — still usable, just less precise. |
| **Gentle character voice** | The assistant feels warm and patient. Two sentences max per step, never cold technical commands. |
| **Always visible companion** | The fairy isn't only around during tasks. It hovers beside the cursor all day, gently bobbing, ready to help. A persistent presence, not a pop-up. |
| **Multi-monitor aware** | Fairy stays on the screen the user is actually using. Never flies into dead zones between mismatched displays. |
| **Click-through everything** | Every overlay lets mouse and keyboard input pass straight to the app underneath. Curby never competes for focus. |

---

## How it's built (high-level)

Python + PyQt6 for the on-screen visuals. `mss` for screen capture. `pynput` for the global hotkey. Claude (Anthropic) is the brain — either via the Claude CLI (zero setup) or via the direct API with the Computer Use tool enabled (pixel-exact coordinates when an API key is present). Runs entirely local; no server.

For the full architecture, see **[design.md](design.md)**.

---

## Current limitations (and what's next)

**Today:**
- Windows 10 / 11 only
- One guided task at a time
- No conversation memory across sessions
- Wake-word not wired up (hotkey required)

**On deck:**
- App-specific context injection (e.g., auto-detect when user is in our internal tool → pre-prime Claude with tool-specific knowledge)
- Wake-word voice activation ("hey curby")
- Cross-monitor path animations (the fairy flying between screens)
- Conversation memory — curby remembers what the user was doing five minutes ago
- macOS / Linux builds

---

## Try it

```powershell
git clone https://github.com/CasterlyGit/curby---the-cursor-buddy.git
cd curby---the-cursor-buddy
pip install -r requirements.txt
python main.py
```

A small glowing swoosh appears next to your cursor — that's curby. Press `Ctrl+.` and type _"how do I enable dark mode"_ to see it in action.

For more detail: **[README.md](README.md)** covers hotkeys, troubleshooting, and the API key switch. **[design.md](design.md)** covers the architecture.
