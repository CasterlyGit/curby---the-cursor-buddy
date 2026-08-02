# Curby — Engineering Evidence Sprint

## Context: why this sprint exists

The goal is to make the implemented engineering easy for a technical evaluator
to verify. Every README statement should connect to source, tests, or a
reproducible measurement. Latency numbers must be measured and scoped, not
inferred. Architecture should be quickly scannable.

Reference: look at how emergency-ai (~/Documents/Dev/emergency-ai) is structured.
That's the bar. But go deeper than that — curby is technically richer.

---

## What curby already has (don't redo)
- CI badge, Python badge, MIT badge
- Latency table with real numbers (700–1200ms api_key, 6–8s claude_cli)
- AVSpeechSynthesizer in-process TTS (no subprocess, 100–150ms)
- Live demo at casterlygit.github.io/curby
- design.md exists
- Structured logging, `curby log` command
- Agent dispatch with sandbox + puck UI

## What's missing for a complete evaluation path

### 1. The README doesn't surface *why* curby is technically hard
A technical reader should immediately see:
- **Why ~1.5s is hard** — breakdown of each phase and what optimization was needed
- **Why AVSpeechSynthesizer over `say`** — subprocess startup cost, how prewarm works, what was measured
- **Why two modes (quick-ask vs agent dispatch) require different architectures** — thread model, sandbox isolation, puck lifecycle
- **The sentence-streaming TTS design decision** — why it was deferred, what the tradeoff is
Add an "Engineering depth" or "How the latency was achieved" section that reads like a mini system design doc.

### 2. Benchmark script (`scripts/bench.py`)
- Measure: STT round-trip, API call (haiku), AVSpeechSynthesizer TTFS (time to first sample), full wall-clock
- Print results as a markdown table
- Save to `docs/benchmarks.md`
- These numbers replace the "~" estimates in the README with real measured data

### 3. Architecture diagram (ASCII or mermaid in README)
Shows: hotkey listener → STT → LLM backend → AVSpeechSynthesizer, with the agent-dispatch fork.
Needs to show threading model — main thread (Qt), STT thread, LLM thread, TTS in-process.

### 4. `docs/DESIGN.md` — decision log
- Why PyQt5 over tkinter/AppKit (event loop, overlay windows, Qt signals thread-safety)
- Why pluggable backends (`api_key` vs `claude_cli`) — the tradeoffs
- Why AVSpeechSynthesizer (vs `say`, vs pyttsx3, vs cloud TTS)
- Why sandbox isolation for agent dispatch
- Failure modes: STT timeout, LLM error, TTS crash — what curby does in each case
- Why the feather indicator is decoupled from cursor (input lag explanation)

### 5. `scripts/smoke.sh` — end-to-end wiring proof
- Start curby in headless mode (or mock mode)
- Send a test utterance programmatically
- Assert a reply comes back within 2s
- Runnable in CI (mocked STT + mocked LLM)

### 6. Version progression
- Keep the current version state explicit while the active feature branch is
  conflicting or its checks are not green.
- Preserve the existing `v0.4.0` release exactly as published. Its tag is not
  an ancestor of the current default branch, so it must not be moved, recreated,
  or presented as linear default-branch progression.
- Assign a prospective next version only after the feature milestone and
  release-line history are reconciled, the supported CI matrix and public guard
  pass, and README/benchmark claims are re-verified at the release commit.
- Release notes must distinguish measured latency evidence from design targets
  and summarize agent-dispatch behavior and remaining limits.

### 7. File 4–6 GitHub issues from the roadmap
Real issues with context, not just README bullet points. Shows active maintenance.
Examples:
- "feat: sentence-streaming TTS for sub-500ms TTFS"
- "feat: periodic prewarm ping (QTimer every 25s)"
- "feat: `curby stats` — session latency histogram"
- "feat: Linux support via pyttsx3 fallback"

### 8. Observability: `curby stats`
- Per-session latency log (already partially in structured logging)
- `curby stats`: show P50/P95 TTFT, P50/P95 wall-clock, session count, backend breakdown
- Writes to ~/.curby/stats.jsonl

### 9. docs/index.html live demo
- Current demo is a static simulation
- Update it to show the two-mode architecture visually
- Show the latency breakdown as an animated bar when a "request" fires

---

## The signal checklist (must pass before done)

- [ ] README first paragraph: specific technical claim with measured numbers
- [ ] Architecture diagram present
- [ ] "How the latency was achieved" section — each optimization named and explained
- [ ] docs/DESIGN.md with decision rationale
- [ ] Benchmark script exists and output is in README
- [ ] Version state and next eligible release condition documented
- [ ] Existing `v0.4.0` lineage documented; next release tagged only after the
  prospective version eligibility gate passes
- [ ] Issues filed for roadmap items
- [ ] CI still green

---

## Engineering evidence

Curby proves:
- You understand **latency decomposition** — you know which phase costs what and why
- You understand **threading on macOS** — Qt main loop, background workers, AVFoundation constraints
- You understand **pluggable architecture** — swappable backends, config-driven behavior
- You understand **system resilience** — what happens on STT timeout, LLM error, TTS crash
- You can ship **UI that feels fast** — prewarm, in-process TTS, interrupt handling

Every one of those should be a 10-second scannable claim in the README.
