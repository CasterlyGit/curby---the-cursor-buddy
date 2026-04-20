"""
Curby — the cursor buddy. MVP entry point.

Usage:
  set ANTHROPIC_API_KEY=sk-ant-...
  python main.py

Controls:
  - Window follows your cursor automatically
  - Click "Snap" to capture a screenshot of the area around your cursor
  - Type a question and press Enter or click "Ask"
  - The buddy sees the screenshot and answers
"""
import sys
import io
import pathlib

# Force UTF-8 output so terminal never crashes on Unicode in error messages
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from src.app import CurbyApp

if __name__ == "__main__":
    app = CurbyApp()
    sys.exit(app.run())
