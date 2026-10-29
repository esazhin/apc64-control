"""The performer's infrastructure (contract 2 §2.10): the pattern files and the timer thread on the monotonic clock."""
import threading
import time

from _apc64_lab.application.ports import PatternSource, PerformerTimer
from _apc64_lab.infrastructure.pattern_files import PatternFiles
from _apc64_lab.infrastructure.performer_timer import ThreadTimer


def test_pattern_files_list_yaml_and_json_by_name_and_read_them_when_asked(tmp_path):
    (tmp_path / "travis.yaml").write_text("name: T\n")
    (tmp_path / "travis.json").write_text("{}")                # the YAML one wins
    (tmp_path / "walk.json").write_text('{"name": "W"}')
    (tmp_path / "notes.txt").write_text("not a pattern")
    files = PatternFiles(tmp_path)
    assert isinstance(files, PatternSource)
    assert files.ids() == ["travis", "walk"] and files.read("travis") == "name: T\n"
    assert files.file_name("walk") == "walk.json" and files.read("gone") is None
    (tmp_path / "late.yml").write_text("name: L\n")              # seen at once
    assert "late" in files.ids()
    assert PatternFiles(tmp_path / "missing").ids() == []


def test_the_timer_calls_tick_at_each_due_time_and_at_once_after_a_wake():
    timer = ThreadTimer()
    assert isinstance(timer, PerformerTimer)
    start = timer.now()
    calls, lock = [], threading.Lock()
    dues = [start + 0.02, start + 0.04, start + 0.06]

    def tick(now):
        with lock:
            calls.append(now)
            return dues[len(calls) - 1] if len(calls) <= len(dues) else None
    timer.start(tick)
    try:
        deadline = time.monotonic() + 2
        while len(calls) < 4 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(calls) == 4
        assert all(c >= d for c, d in zip(calls[1:], dues))       # never early
        timing = timer.timing()
        assert timing["ticks"] == 3 and timing["max_ms"] < 50
        timer.wake()                                              # an input: tick is asked again at once
        deadline = time.monotonic() + 2
        while len(calls) < 5 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(calls) == 5 and timer.timing()["ticks"] == 3   # a wake is not a due call
    finally:
        timer.stop()
