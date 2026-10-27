"""Shared test helpers for the adapters: fixture captures and waiting for adapter threads."""
import time

from _apc64_host.protocol.conftest import FIXTURES, capture  # noqa: F401  (re-exported for adapter tests)


def wait_for(predicate, timeout=2.0, step=0.002):
    """Polls until predicate() is true (adapter threads deliver asynchronously); returns its last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value or time.monotonic() > deadline:
            return value
        time.sleep(step)
