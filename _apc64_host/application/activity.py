"""ActivityLog: the live list of what each action did (contract d162, d163, q7).

A ring of the latest 200 entries, newest first. Aftertouch is folded into its note's entry (one entry per
routed note holding its latest aftertouch value) instead of one entry per aftertouch message. Subscribers
get every new or updated entry in order; each carries a stable id so a page can update a folded entry in
place.
"""
import threading
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable

from ..domain.effects import ActivityEntry

CAPACITY = 200


@dataclass(frozen=True)
class ActivityRecord:
    id: int
    entry: ActivityEntry
    folded: bool = False   # an update of an entry already listed (its aftertouch changed)


class ActivityLog:
    def __init__(self, capacity: int = CAPACITY):
        self._capacity = capacity
        self._records: deque[ActivityRecord] = deque(maxlen=capacity)   # oldest first
        self._next_id = 1
        self._subscribers: dict[int, Callable[[ActivityRecord], None]] = {}
        self._next_token = 1
        self._lock = threading.Lock()

    def append(self, entry: ActivityEntry) -> ActivityRecord:
        with self._lock:
            record = ActivityRecord(self._next_id, entry)
            self._next_id += 1
            self._records.append(record)
        self._notify(record)
        return record

    def fold(self, note: int, aftertouch: int) -> ActivityRecord | None:
        """Sets the latest aftertouch on the newest entry of that note; None when no such entry is listed."""
        with self._lock:
            for index in range(len(self._records) - 1, -1, -1):
                record = self._records[index]
                if record.entry.note == note:
                    updated = ActivityRecord(record.id, replace(record.entry, aftertouch=aftertouch), True)
                    self._records[index] = updated
                    break
            else:
                return None
        self._notify(updated)
        return updated

    def recent(self, limit: int = CAPACITY) -> list[ActivityEntry]:
        """The newest `limit` entries (at most 200), newest first."""
        return [r.entry for r in self.records(limit)]

    def records(self, limit: int = CAPACITY) -> list[ActivityRecord]:
        limit = max(0, min(int(limit), self._capacity))
        with self._lock:
            return list(reversed(self._records))[:limit]

    def subscribe(self, callback: Callable[[ActivityRecord], None]) -> int:
        with self._lock:
            token, self._next_token = self._next_token, self._next_token + 1
            self._subscribers[token] = callback
        return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    def _notify(self, record: ActivityRecord) -> None:
        for callback in list(self._subscribers.values()):
            callback(record)
