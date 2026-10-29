"""ClockFollower: the tempo of an external MIDI clock (24 ticks a quarter note), from the ticks' arrival times.

Pure: the caller hands each tick (0xF8) its time in seconds. A clock over USB jitters (a steady 125 BPM arrives as
20 ms ticks give or take a millisecond or two), so the tempo is smoothed in three ways:

- **A long window.** The reading is the least-squares slope of the tick times over the last `window` ticks (four
  quarter notes by default), which jitter moves far less than a mean of the intervals over one quarter. It is known
  once `least` intervals have come (a provisional reading, from the few ticks there are) and firms up as the window
  fills; when it first fills, the tempo given is that reading.
- **Hysteresis.** The tempo given (bpm(), to 0.1) changes only when the reading moves more than `hold` BPM from it,
  or more than twice the reading's own standard error where that is larger (the scatter of the ticks about the fit
  says how far a reading from few ticks can be trusted), so the decimals do not wander with the jitter.
- **A real change is followed at once.** When the short reading (the slope over the last `short` ticks, one quarter)
  stays more than `departure` (a fraction: 0.02 is 2 %) away from the tempo given for `persist` ticks in a row, the
  tempo changed: the window starts again from those ticks and the tempo given is their reading.

The tempo is forgotten when no tick came for `timeout` seconds or a Stop (0xFC) arrived; a tick after such a gap
starts the measurement afresh. Start (0xFA) and Continue (0xFB) only reset the measurement: the performer's phase is
locked to the press, not to the clock.

    follower = ClockFollower()
    for k in range(25):
        follower.tick(k * 0.025)          # 24 ticks a quarter, 0.025 s apart
    follower.bpm(0.6)                      # 100.0
"""
from collections import deque

PPQN = 24
TICK, START, CONTINUE, STOP = 0xF8, 0xFA, 0xFB, 0xFC


class ClockFollower:
    def __init__(self, window: int = 4 * PPQN, least: int = 6, timeout: float = 0.5, *, short: int = PPQN,
                 hold: float = 0.2, departure: float = 0.02, persist: int = PPQN // 2):
        self.window, self.least, self.timeout = int(window), int(least), float(timeout)
        self.short, self.hold, self.departure, self.persist = int(short), float(hold), float(departure), int(persist)
        self._ticks: deque[float] = deque(maxlen=self.window + 1)     # the window's tick times, oldest first
        self._held: float | None = None                               # the tempo given
        self._firm = False                                            # the window has filled since the last reset
        self._away = 0                                                # ticks in a row the short reading departed

    def message(self, status: int, t: float) -> None:
        """A realtime byte as it arrived: a tick is measured; Start, Continue and Stop reset."""
        if status == TICK:
            self.tick(t)
        elif status in (START, CONTINUE, STOP):
            self.reset()

    def tick(self, t: float) -> None:
        t = float(t)
        if self._ticks:
            interval = t - self._ticks[-1]
            if interval > self.timeout:
                self.reset()                  # a gap: the clock stopped and started again
            elif interval <= 0:
                return
        self._ticks.append(t)
        self._follow()

    def reset(self) -> None:
        self._ticks.clear()
        self._held, self._firm, self._away = None, False, 0

    def bpm(self, t: float | None = None) -> float | None:
        """Quarter notes a minute, to 0.1, or None (too few ticks yet, or none for `timeout` seconds at t)."""
        if self._held is None or not self._ticks:
            return None
        if t is not None and float(t) - self._ticks[-1] > self.timeout:
            return None
        return self._held

    def reading(self) -> float | None:
        """The window's reading now, unrounded and without the hysteresis (None: too few ticks)."""
        return _fit(self._ticks)[0] if len(self._ticks) > self.least else None

    # --- internals ---------------------------------------------------------------------------------------------
    def _follow(self) -> None:
        if len(self._ticks) <= self.least:
            return
        reading, error = _fit(self._ticks)
        if reading is None:
            return
        if self._held is None:
            self._held = round(reading, 1)
            return
        short = _slope_bpm(list(self._ticks)[-(self.short + 1):]) if len(self._ticks) > self.short + 1 else None
        if short is not None and abs(short - self._held) > self.departure * self._held:
            self._away += 1
            if self._away >= self.persist:                    # a real change: start again from these ticks
                kept = list(self._ticks)[-(self.persist + 1):]
                self._ticks.clear()
                self._ticks.extend(kept)
                self._held, self._firm, self._away = round(_slope_bpm(kept), 1), False, 0
            return
        self._away = 0
        if not self._firm and len(self._ticks) == self._ticks.maxlen:
            self._firm = True                                 # the window is full: its reading, once
            self._held = round(reading, 1)
        elif abs(reading - self._held) > max(self.hold, 2 * error):
            self._held = round(reading, 1)


def _slope_bpm(times) -> float | None:
    return _fit(times)[0]


def _fit(times) -> tuple[float | None, float]:
    """The tempo of tick times by their least-squares slope (seconds a tick) and its standard error in BPM, from
    the scatter of the ticks about the line; (None, 0) for fewer than two ticks or a slope that is not forward."""
    n = len(times)
    if n < 2:
        return None, 0.0
    first = times[0]
    mean_i = (n - 1) / 2.0
    mean_t = sum(t - first for t in times) / n
    den = n * (n * n - 1) / 12.0                       # the sum of (i - mean_i)² over 0 … n-1
    seconds = sum((i - mean_i) * (t - first - mean_t) for i, t in enumerate(times)) / den
    if seconds <= 0:
        return None, 0.0
    bpm = 60.0 / (seconds * PPQN)
    if n < 3:
        return bpm, 0.0
    scatter = sum((t - first - mean_t - seconds * (i - mean_i)) ** 2 for i, t in enumerate(times)) / (n - 2)
    return bpm, bpm * (scatter / den) ** 0.5 / seconds
