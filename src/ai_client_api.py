"""
Anthropic API client for guided steps using Claude's Computer Use tool.
This is the pixel-calibrated path — much more accurate than the CLI.

Activated automatically when ANTHROPIC_API_KEY is set in the environment.
Otherwise ai_client.ask_guided_step falls back to the CLI-based approach.
"""
import base64
import io
import os
from PIL import Image

# Clicky-recommended computer-use resolutions; pick the one that matches
# the display's real aspect ratio to avoid x-axis distortion.
_CU_RESOLUTIONS = [
    (1280, 800),   # 16:10 — modern laptops
    (1366, 768),   # ~16:9 — most external monitors
    (1024, 768),   # 4:3
]

MODEL = os.environ.get("CURBY_MODEL", "claude-sonnet-4-5")
BETA_HEADER = "computer-use-2025-01-24"
TOOL_TYPE = "computer_20250124"

_SYSTEM = """you are curby, an on-screen AI tutor pointing users at the next thing to do.

rules:
- ground every step in what is actually visible in the screenshot; never invent UI or text to type
- respond with a short conversational instruction (under 20 words)
- use the computer tool to click or move the mouse to the EXACT pixel center of the target element
- if the task is already complete or the next step isn't on this screen, say so and DO NOT call the tool
- prefer the most natural single next action; avoid multi-part instructions"""


def is_api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _pick_resolution(w: int, h: int) -> tuple[int, int]:
    aspect = w / h
    return min(_CU_RESOLUTIONS, key=lambda r: abs(r[0] / r[1] - aspect))


def _prepare_image(img: Image.Image) -> tuple[str, int, int, int, int]:
    """Resize to aspect-matched CU resolution, return (b64_jpeg, w, h, orig_w, orig_h)."""
    orig_w, orig_h = img.size
    target_w, target_h = _pick_resolution(orig_w, orig_h)
    resized = img.resize((target_w, target_h), Image.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format="JPEG", quality=90)
    b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return b64, target_w, target_h, orig_w, orig_h


def ask_guided_step_api(
    task: str,
    image: Image.Image,
    steps_done: list[str],
) -> tuple[str, int | None, int | None]:
    """Use Claude's Computer Use tool via API to get pixel-accurate guidance."""
    from anthropic import Anthropic

    b64, w, h, orig_w, orig_h = _prepare_image(image)

    parts = [f"task: {task}"]
    if steps_done:
        parts.append("steps already done:\n- " + "\n- ".join(steps_done))
    parts.append(
        "what is the next single action? point at the element with the computer tool."
    )

    client = Anthropic()
    print(f"[api] model={MODEL} res={w}x{h} steps_done={len(steps_done)}")

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        tools=[
            {
                "type": TOOL_TYPE,
                "name": "computer",
                "display_width_px": w,
                "display_height_px": h,
            }
        ],
        extra_headers={"anthropic-beta": BETA_HEADER},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": "\n".join(parts)},
                ],
            }
        ],
    )

    spoken = ""
    coord_x: int | None = None
    coord_y: int | None = None

    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            spoken = (spoken + " " + block.text).strip()
        elif btype == "tool_use":
            inp = block.input if isinstance(block.input, dict) else {}
            action = inp.get("action", "")
            coord = inp.get("coordinate")
            if action in ("left_click", "mouse_move", "click", "move") and coord:
                if isinstance(coord, (list, tuple)) and len(coord) == 2:
                    coord_x, coord_y = int(coord[0]), int(coord[1])
                    break

    # Scale coords from CU resolution back to original image pixels
    if coord_x is not None and coord_y is not None:
        coord_x = int(coord_x * orig_w / w)
        coord_y = int(coord_y * orig_h / h)

    print(f"[api] response: {spoken!r} point=({coord_x},{coord_y})")
    return spoken or "next step", coord_x, coord_y
