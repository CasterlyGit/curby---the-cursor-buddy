import base64
import io
import json
import re
import subprocess
from collections.abc import Callable
from PIL import Image

_CLAUDE = r"C:\Users\tarun\.local\bin\claude.exe"

# Matches [POINT:x,y] or [POINT:x,y:label] at end of response — same pattern as Clicky
_POINT_RE = re.compile(r'\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::[^\]]*)?)\]\s*$')

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
    "you are curby, guiding a user through a ui task one step at a time. "
    "you can see a real screenshot of the user's screen right now.\n\n"
    "BEFORE answering, silently look at the screenshot and identify:\n"
    "1. which app / website is this (vs code, youtube, gmail, etc.)\n"
    "2. what elements are actually visible: menus, buttons, icons, tabs, panels\n"
    "3. which one advances the task\n\n"
    "then respond:\n"
    "- ONE short lowercase instruction (under 20 words) for the single next action\n"
    "- only reference elements you can literally SEE in the screenshot\n"
    "- never invent button names, menu labels, or text to type — if it's not visible, don't say it\n"
    "- never output shell commands, keyboard shortcuts, or app names the user must run\n"
    "- if the task looks already done, say 'looks like you're already there' and end with [POINT:none]\n"
    "- if the next step is on a different screen (not this one), say so and end with [POINT:none]\n"
    "\n"
    "end every response with a point tag on the same line: [POINT:x,y:label]\n"
    "where x,y is the pixel center of the exact element to click in this screenshot "
    "(image is full screen, coordinates map 1:1 to screen pixels after scaling).\n"
    "\n"
    "examples:\n"
    "click the three-dot menu next to the video [POINT:1820,240:more menu]\n"
    "open the settings gear in the sidebar [POINT:62,740:settings gear]\n"
    "use [POINT:none] if not applicable here"
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
    Strip [POINT:x,y:label] or [POINT:none] from end of text.
    Returns (clean_text, x, y) — x/y are None if [POINT:none] or no tag.
    """
    m = _POINT_RE.search(text)
    if not m:
        return text.strip(), None, None
    clean = text[:m.start()].strip()
    x = int(m.group(1)) if m.group(1) is not None else None
    y = int(m.group(2)) if m.group(2) is not None else None
    return clean, x, y


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

def ask_guided_step(
    task: str,
    image: Image.Image,
    steps_done: list[str],
) -> tuple[str, int | None, int | None]:
    """
    Blocking call. Returns (spoken_text, x, y).
    x/y are None if task is complete or nothing actionable is visible.

    Dispatch:
      - If ANTHROPIC_API_KEY is set → use direct Anthropic API + Computer Use tool
        (pixel-calibrated, much more accurate — Clicky's approach).
      - Otherwise → use the Claude CLI with the [POINT:x,y:label] text-tag format.
    """
    # Prefer API path when available
    try:
        from src.ai_client_api import is_api_available, ask_guided_step_api
        if is_api_available():
            try:
                return ask_guided_step_api(task, image, steps_done)
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
                        spoken, x, y = parse_point_tag(raw)
                        return spoken, x, y
        except (json.JSONDecodeError, KeyError):
            continue

    print(f"[guided/cli] no response parsed")
    return "sorry, i couldn't figure out the next step.", None, None
