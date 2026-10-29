"""PerformerTimer on a thread of its own and the monotonic clock (contract 2 §2.10).

start(tick) runs a daemon thread that calls tick(now) at the time tick last answered: it waits on a condition until
EARLY seconds before that time, then sleeps in short slices up to it (the condition's timeout alone is too coarse
for music), and calls tick with the time it actually woke. wake() — an input changed the engine — makes it ask tick
at once. How late each due call came is kept (the latest SAMPLES) for timing(): ticks, mean, p99 and max in ms.
"""
import logging
import threading
import time
from collections import deque
from typing import Callable

log = logging.getLogger(__name__)
EARLY = 0.002          # wake this long before the due time, then sleep in slices
SLICE = 0.0002         # the slice
SAMPLES = 2000


class ThreadTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._cond = threading.Condition()
        self._woken = False
        self._stopped = True
        self._thread: threading.Thread | None = None
        self._tick: Callable[[float], float | None] | None = None
        self._late: deque[float] = deque(maxlen=SAMPLES)
        self._count = 0

    def now(self) -> float:
        return self._clock()

    def start(self, tick: Callable[[float], float | None]) -> None:
        with self._cond:
            if self._thread is not None:
                return
            self._tick, self._stopped = tick, False
            self._thread = threading.Thread(target=self._run, name="lab performer", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        with self._cond:
            self._woken = True
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify()
            thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def timing(self) -> dict:
        late = sorted(self._late)
        if not late:
            return {"ticks": self._count, "mean_ms": None, "p99_ms": None, "max_ms": None}
        p99 = late[min(len(late) - 1, int(len(late) * 0.99))]
        return {"ticks": self._count, "mean_ms": round(sum(late) / len(late) * 1000, 3),
                "p99_ms": round(p99 * 1000, 3), "max_ms": round(late[-1] * 1000, 3)}

    def _call(self, now: float) -> float | None:
        try:
            return self._tick(now)
        except Exception:   # a failing tick never ends the thread
            log.exception("lab: the performer's tick failed")
            return None

    def _run(self) -> None:
        due = self._call(self.now())
        while True:
            with self._cond:
                while not self._stopped and not self._woken:
                    if due is not None and self.now() >= due - EARLY:
                        break
                    self._cond.wait(None if due is None else max(0.0, due - EARLY - self.now()))
                if self._stopped:
                    return
                woken, self._woken = self._woken, False
            if not woken and due is not None:
                while (left := due - self.now()) > 0:
                    time.sleep(min(left, SLICE))
                now = self.now()
                self._late.append(max(0.0, now - due))
                self._count += 1
            else:
                now = self.now()
            due = self._call(now)
