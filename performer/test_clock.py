"""The MIDI clock follower: the tempo from 24 ticks a quarter, steady over jitter, gone after a gap or a Stop."""
import random

from performer import ClockFollower
from performer.clock import START, STOP, TICK


def ticks(follower, bpm, count, start=0.0, jitter=0.0, seed=0):
    rng = random.Random(seed)
    interval = 60.0 / bpm / 24
    for k in range(count):
        follower.tick(start + k * interval + rng.uniform(-jitter, jitter))
    return start + (count - 1) * interval


def test_the_tempo_of_a_steady_clock():
    follower = ClockFollower()
    assert follower.bpm() is None
    last = ticks(follower, 100, 25)
    assert follower.bpm(last) == 100.0


def test_a_jittery_clock_reads_steady_over_a_quarter_note():
    follower = ClockFollower()
    last = ticks(follower, 120, 49, jitter=0.0005)
    assert abs(follower.bpm(last) - 120) <= 0.6


def test_a_gap_a_stop_or_a_start_forget_the_tempo():
    follower = ClockFollower()
    last = ticks(follower, 90, 30)
    assert follower.bpm(last + 0.6) is None                  # no tick for longer than the timeout
    ticks(follower, 90, 30, start=last + 1.0)                 # the gap is not measured as an interval
    assert follower.bpm() == 90.0
    follower.message(STOP, 3.0)
    assert follower.bpm() is None
    follower.message(START, 3.1)
    for k in range(10):
        follower.message(TICK, 3.1 + k * 60.0 / 140 / 24)
    assert follower.bpm() == 140.0


def follow(follower, times):
    """Every tick in turn: [(time, the tempo given then)]."""
    out = []
    for t in times:
        follower.tick(t)
        out.append((t, follower.bpm(t)))
    return out


def clock_times(bpm, start, end, jitter=0.0, rng=None):
    interval = 60.0 / bpm / 24
    times, k = [], 0
    while start + k * interval < end:
        times.append(start + k * interval + (rng.uniform(-jitter, jitter) if jitter else 0.0))
        k += 1
    return times


def test_a_jittery_usb_clock_reads_steady_and_changes_rarely():
    """125 BPM, every tick ±3 ms: over 30 s the tempo given stays within 0.2 of 125 and seldom moves."""
    follower = ClockFollower()
    read = follow(follower, clock_times(125, 0.0, 30.0, jitter=0.003, rng=random.Random(1)))
    settled = [bpm for t, bpm in read if t > 2.0]                 # four beats in: the window is full
    assert all(abs(bpm - 125) <= 0.2 for bpm in settled), (min(settled), max(settled))
    changes = sum(1 for a, b in zip(settled, settled[1:]) if a != b)
    assert changes <= 2, changes
    assert read[6][1] is not None                                # a provisional tempo after 6 ticks


def test_a_real_tempo_change_is_followed_within_a_beat():
    beat = 60.0 / 140
    for jitter, near_soon, near_later in ((0.0, 0.0, 0.0), (0.003, 1.5, 0.3)):
        follower = ClockFollower()
        rng = random.Random(2)
        follow(follower, clock_times(125, 0.0, 6.0, jitter, rng))
        read = follow(follower, clock_times(140, 6.0, 12.0, jitter, rng))
        soon = [bpm for t, bpm in read if 6.0 + beat <= t < 6.0 + 2 * beat]
        later = [bpm for t, bpm in read if t >= 6.0 + 4 * beat]
        assert all(abs(bpm - 140) <= near_soon for bpm in soon), (jitter, soon)
        assert all(abs(bpm - 140) <= near_later for bpm in later), (jitter, min(later), max(later))
