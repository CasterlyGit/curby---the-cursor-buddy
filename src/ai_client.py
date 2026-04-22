import base64
import io
import json
import re
import subprocess
from collections.abc import Callable
from PIL import Image

_CLAUDE = r"C:\Users\tarun\.local\bin\claude.exe"

# [POINT:x,y] or [POINT:x,y:label] or [POINT:none] — trailing anchor tag
_POINT_RE = re.compile(r'\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::[^\]]*)?)\]')
# [BOX:x1,y1,x2,y2] — optional bounding rect of the target element
_BOX_RE   = re.compile(r'\[BOX:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]')
# [ACTION:click|type|close|select|drag|open] — intent hint for the overlay
_ACTION_RE = re.compile(r'\[ACTION:\s*(click|type|close|select|drag|open)\s*\]', re.I)

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')

# ── System prompts ────────────────────────────────────────────────────────────

_SYSTEM = (
    "you are curby, a voice assistant that lives near the user's cursor. "
    "you can see a screenshot of exactly what they're looking at. "
    "be conversational — like a knowledgeable friend sitting next to them. "
    "write for the ear, not the eye: short sentences, no lists, no markdown, no bullet points. "
    "give 1-2 sentence responses, then stop. "
    "if a question needs more, give the single most important point first. "
    "when natural, ask a short follow-up to keep the conversation going. "
    "never start with 'i' — vary how you open each reply."
)

_GUIDED_SYSTEM = (
    "you are curby — a friendly, calm in-screen guide. the user is learning a ui "
    "task and you're walking beside them, one step at a time. you can see a real "
    "screenshot of their screen right now.\n\n"
    "before you speak, silently look at the screenshot and take in:\n"
    "  - which app or website this is\n"
    "  - what's actually on screen: menus, buttons, icons, fields, panels\n"
    "  - which element is the next one they should touch\n"
    "\n"
    "then reply in a warm, conversational voice. lowercase. like a friend leaning "
    "over their shoulder. rules for how you talk:\n"
    "\n"
    "  - TWO short sentences max. first sentence says what to do in plain words. "
    "    second sentence (optional) gives a tiny nudge of context — why this step, "
    "    or what they'll see after. don't over-explain. never leave them guessing.\n"
    "  - talk about the element as it actually appears on screen. use its visible "
    "    label, or describe it by shape / position (\"the gear in the bottom-left\")\n"
    "  - never invent buttons, menu labels, or text to type. if you can't see it, "
    "    don't say it.\n"
    "  - never output shell commands or keyboard shortcuts unless the element is a "
    "    literal key on screen.\n"
    "  - if they're already where they need to be, say so warmly ('looks like you're "
    "    already set — nothing to do here'). end with [POINT:none].\n"
    "  - if the next step isn't on THIS screen, acknowledge it ('we'll need to open "
    "    ___ first — can you get there?'). end with [POINT:none].\n"
    "\n"
    "voice examples (this is the tone to match):\n"
    "  'click the three-dot menu on the video — that's where playback options live.'\n"
    "  'open the gear in the sidebar. it'll take you to settings.'\n"
    "  'pop your search in the bar up top. i'll walk you to the next step from the results.'\n"
    "  'hit the x in the corner to close this — we'll come back to it later.'\n"
    "\n"
    "always end your ONE line of output with, in order:\n"
    "  <your gentle instruction>  [POINT:x,y:label]  [BOX:x1,y1,x2,y2]  [ACTION:click|type|close|select|drag|open]\n"
    "\n"
    "  - POINT = pixel center of the exact element (image is full screen, coords map 1:1)\n"
    "  - BOX   = tight bounding rectangle around that element (x1<x2, y1<y2)\n"
    "  - ACTION = the single most appropriate intent\n"
    "\n"
    "use [POINT:none] (drop BOX and ACTION) if the step isn't on this screen or "
    "if the task is already done.\n"
    "\n"
    "full examples:\n"
    "  click the three-dot menu on the video — that's the playback menu. [POINT:1820,240:more menu] [BOX:1806,226,1834,254] [ACTION:click]\n"
    "  open the gear in the sidebar. settings live in there. [POINT:62,740:settings] [BOX:46,724,78,756] [ACTION:click]\n"
    "  type your search into this box. [POINT:960,120:search] [BOX:400,100,1520,140] [ACTION:type]"
)

# ── Image encoding ────────────────────────────────────────────────────────────

def _encode_image(img: Image.Image, max_px: int = 1280) -> tuple[str, str]:
    """Resize to max_px on longest side (Clicky uses 1280), JPEG at 0.8 quality."""
    if max(img.size) > max_px:
        img = img.copy()
        img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8"), "image/jpeg"


def _build_messages(
    text: str,
    image: Image.Image | None,
    history: list[dict] | None,
    max_px: int = 1280,
) -> list[dict]:
    """Build alternating user/assistant message list, Clicky-style."""
    messages: list[dict] = []

    # Inject last 4 turns as real alternating messages (not embedded text)
    if history:
        for turn in history[-4:]:
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["assistant"]})

    # Current user message
    content: list[dict] = []
    if image:
        data, media_type = _encode_image(image, max_px)
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        })
    content.append({"type": "text", "text": text})
    messages.append({"role": "user", "content": content})
    return messages


def _make_cmd(system: str) -> list[str]:
    return [
        _CLAUDE, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--system-prompt", system,
    ]


def _send_messages(messages: list[dict], system: str) -> subprocess.Popen:
    """Open a Claude CLI subprocess and write the message list to stdin."""
    # Claude CLI stream-json expects a single user message; we embed history in text for multi-turn
    # Use the last user message content directly, prepend history as context text
    last = messages[-1]
    history_turns = messages[:-1]

    content = list(last["content"]) if isinstance(last["content"], list) else [{"type": "text", "text": last["content"]}]

    if history_turns:
        lines = []
        for m in history_turns:
            role = "user" if m["role"] == "user" else "assistant"
            body = m["content"] if isinstance(m["content"], str) else next((b["text"] for b in m["content"] if b.get("type") == "text"), "")
            lines.append(f"{role}: {body}")
        prefix = "[conversation so far]\n" + "\n".join(lines) + "\n\n[current message]\n"
        # Inject before the text block
        for i, block in enumerate(content):
            if block.get("type") == "text":
                content[i] = {"type": "text", "text": prefix + block["text"]}
                break

    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    proc = subprocess.Popen(
        _make_cmd(system),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    proc.stdin.write(msg)
    proc.stdin.close()
    return proc


# ── Point tag parsing ─────────────────────────────────────────────────────────

def parse_point_tag(text: str) -> tuple[str, int | None, int | None]:
    """
    Strip [POINT:...] / [BOX:...] / [ACTION:...] from end of text.
    Returns (clean_text, x, y) — for back-compat with older callers.
    For full structured parse use parse_guided_tags.
    """
    clean, x, y, _box, _action = parse_guided_tags(text)
    return clean, x, y


def parse_guided_tags(
    text: str,
) -> tuple[str, int | None, int | None, tuple[int, int, int, int] | None, str | None]:
    """
    Returns (clean_text, x, y, box, action).
      - x,y: pixel center or None if [POINT:none]
      - box: (x1, y1, x2, y2) or None
      - action: "click" | "type" | "close" | "select" | "drag" | "open" | None
    """
    x = y = None
    box = None
    action = None

    clean = text
    mp = _POINT_RE.search(clean)
    if mp:
        if mp.group(1) is not None and mp.group(2) is not None:
            x, y = int(mp.group(1)), int(mp.group(2))
        clean = clean[: mp.start()] + clean[mp.end():]

    mb = _BOX_RE.search(clean)
    if mb:
        box = (int(mb.group(1)), int(mb.group(2)),
               int(mb.group(3)), int(mb.group(4)))
        clean = clean[: mb.start()] + clean[mb.end():]

    ma = _ACTION_RE.search(clean)
    if ma:
        action = ma.group(1).lower()
        clean = clean[: ma.start()] + clean[ma.end():]

    return clean.strip(), x, y, box, action


# ── Streaming voice reply ─────────────────────────────────────────────────────

def ask_stream(
    text: str,
    image: Image.Image | None,
    history: list[dict] | None,
    on_sentence: Callable[[str], None],
) -> str:
    """
    Stream a conversational reply from Claude, calling on_sentence() for each
    sentence as it arrives. Returns full response text when done.
    """
    messages = _build_messages(text, image, history)
    proc = _send_messages(messages, _SYSTEM)

    buffer = ""
    streamed_text = ""

    def _flush(buf: str, final: bool) -> str:
        parts = _SENTENCE_RE.split(buf)
        if final:
            for p in parts:
                if p.strip():
                    on_sentence(p.strip())
            return ""
        for p in parts[:-1]:
            if p.strip():
                on_sentence(p.strip())
        return parts[-1]

    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if obj.get("type") == "stream_event":
            event = obj.get("event", {})
            if event.get("type") == "content_block_delta":
                chunk = event.get("delta", {}).get("text", "")
                if chunk:
                    buffer += chunk
                    streamed_text += chunk
                    buffer = _flush(buffer, final=False)

        elif obj.get("type") == "assistant":
            for block in obj["message"]["content"]:
                if block.get("type") == "text":
                    full_text = block["text"]
                    if not streamed_text:
                        _flush(full_text, final=True)
                    elif buffer.strip():
                        _flush(buffer, final=True)
                    proc.wait()
                    return full_text

    proc.wait()
    return streamed_text or "(no response)"


# ── Single guided step ────────────────────────────────────────────────────────

GuidedStep = tuple[
    str,                                  # spoken_text
    int | None, int | None,               # point x, y
    tuple[int, int, int, int] | None,     # box x1,y1,x2,y2
    str | None,                           # action
]


def ask_guided_step(
    task: str,
    image: Image.Image,
    steps_done: list[str],
) -> GuidedStep:
    """Returns (text, x, y, box, action). Any of the later four may be None."""
    try:
        from src.ai_client_api import is_api_available, ask_guided_step_api
        if is_api_available():
            try:
                text, x, y = ask_guided_step_api(task, image, steps_done)
                # Computer Use returns a point only; synthesize a small default box around it
                box = None
                if x is not None and y is not None:
                    box = (x - 18, y - 18, x + 18, y + 18)
                return text, x, y, box, "click"
            except Exception as e:
                print(f"[api error] {e} — falling back to CLI")
    except ImportError:
        pass

    img_w, img_h = image.size
    print(f"[guided/cli] screenshot {img_w}x{img_h}")

    parts = [f"task: {task}"]
    if steps_done:
        parts.append("steps already done: " + "; ".join(steps_done))
    parts.append("what should the user do next? look only at what is visible right now.")
    prompt = "\n".join(parts)

    messages = _build_messages(prompt, image, history=None, max_px=1280)
    proc = _send_messages(messages, _GUIDED_SYSTEM)

    result_out, _ = proc.communicate(timeout=60)

    for line in result_out.splitlines():
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant":
                for block in obj["message"]["content"]:
                    if block.get("type") == "text":
                        raw = block["text"].strip()
                        print(f"[guided/cli] raw response: {raw!r}")
                        text, x, y, box, action = parse_guided_tags(raw)
                        return text, x, y, box, action
        except (json.JSONDecodeError, KeyError):
            continue

    print(f"[guided/cli] no response parsed")
    return "sorry, i couldn't figure out the next step.", None, None, None, None
