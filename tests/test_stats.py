"""Tests for src/stats.py — P50/P95 latency stats computation."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.stats import compute_stats, _load_events, _backend_breakdown_str, print_stats, save_summary


def _make_events(n: int, ttft_ms: int = 200, total_ms: int = 900,
                 backend: str = "api_key", followup: bool = False,
                 ts: str = "2026-05-25T10:00:00+00:00") -> list[dict]:
    return [
        {
            "ts": ts,
            "event": "quick_ask",
            "backend": backend,
            "ttft_ms": ttft_ms,
            "total_ms": total_ms,
            "was_followup": followup,
        }
        for _ in range(n)
    ]


def test_compute_stats_empty():
    s = compute_stats([])
    assert s["quick_asks"] == 0
    assert s["sessions"] == 0
    assert s["ttft_p50"] is None


def test_compute_stats_basic():
    events = _make_events(10, ttft_ms=200, total_ms=900)
    s = compute_stats(events)
    assert s["quick_asks"] == 10
    assert s["ttft_p50"] == 200
    assert s["ttft_p95"] == 200
    assert s["wall_clock_p50"] == 900


def test_compute_stats_percentiles():
    # 10 events with varying latency
    events = []
    for i in range(10):
        events.append({
            "ts": "2026-05-25T10:00:00+00:00",
            "event": "quick_ask",
            "backend": "api_key",
            "ttft_ms": (i + 1) * 100,  # 100, 200, ..., 1000
            "total_ms": (i + 1) * 100,
            "was_followup": False,
        })
    s = compute_stats(events)
    # p50 of [100,200,...,1000]: ceil(10*50/100)-1 = 5-1 = 4 → value 500
    assert s["ttft_p50"] == 500
    # p95: ceil(10*95/100)-1 = ceil(9.5)-1 = 10-1 = 9 → value 1000
    assert s["ttft_p95"] == 1000


def test_compute_stats_backend_breakdown():
    events = (
        _make_events(9, backend="api_key") +
        _make_events(1, backend="claude_cli")
    )
    s = compute_stats(events)
    assert s["backend_counts"]["api_key"] == 9
    assert s["backend_counts"]["claude_cli"] == 1


def test_compute_stats_avg_followups():
    # 5 non-followup + 5 followup → avg = 1.0
    events = (
        _make_events(5, followup=False) +
        _make_events(5, followup=True)
    )
    s = compute_stats(events)
    assert s["avg_followups"] == 1.0


def test_compute_stats_session_count():
    # 3 events on same day + 2 on different day
    events = (
        _make_events(3, ts="2026-05-25T10:00:00+00:00") +
        _make_events(2, ts="2026-05-24T10:00:00+00:00")
    )
    s = compute_stats(events)
    assert s["sessions"] == 2


def test_backend_breakdown_str_empty():
    assert _backend_breakdown_str({}) == "—"


def test_backend_breakdown_str():
    result = _backend_breakdown_str({"api_key": 9, "claude_cli": 1})
    assert "api_key 90%" in result
    assert "claude_cli 10%" in result


def test_load_events_from_file(tmp_path):
    log = tmp_path / "curby.log"
    entries = [
        {"ts": "2026-05-25T10:00:00+00:00", "event": "quick_ask", "backend": "api_key",
         "ttft_ms": 210, "total_ms": 890, "was_followup": False},
        {"ts": "2026-05-25T10:01:00+00:00", "event": "agent_dispatch"},  # should be excluded
        {"ts": "2026-05-25T10:02:00+00:00", "event": "quick_ask", "backend": "api_key",
         "ttft_ms": 180, "total_ms": 810, "was_followup": True},
    ]
    with log.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    events = _load_events(log_path=log, days=365)
    assert len(events) == 2
    assert all(e["event"] == "quick_ask" for e in events)


def test_load_events_respects_lookback(tmp_path):
    log = tmp_path / "curby.log"
    # One event from 60 days ago (should be excluded), one recent
    entries = [
        {"ts": "2025-03-25T10:00:00+00:00", "event": "quick_ask", "backend": "api_key",
         "ttft_ms": 200, "total_ms": 800, "was_followup": False},
        {"ts": "2026-05-25T10:00:00+00:00", "event": "quick_ask", "backend": "api_key",
         "ttft_ms": 200, "total_ms": 800, "was_followup": False},
    ]
    with log.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

    events = _load_events(log_path=log, days=30)
    assert len(events) == 1


def test_print_stats_no_crash(capsys):
    s = compute_stats(_make_events(5))
    print_stats(s)
    out = capsys.readouterr().out
    assert "curby stats" in out
    assert "quick-asks" in out


def test_print_stats_empty(capsys):
    s = compute_stats([])
    print_stats(s)
    out = capsys.readouterr().out
    assert "0" in out


def test_save_summary(tmp_path):
    stats_path = tmp_path / "stats.jsonl"
    s = compute_stats(_make_events(3))
    save_summary(s, stats_path=stats_path)
    lines = stats_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["quick_asks"] == 3
    assert "ts" in entry


def test_save_summary_appends(tmp_path):
    stats_path = tmp_path / "stats.jsonl"
    s = compute_stats(_make_events(3))
    save_summary(s, stats_path=stats_path)
    save_summary(s, stats_path=stats_path)
    lines = stats_path.read_text().strip().splitlines()
    assert len(lines) == 2
