"""LabStatePublisher over the host's WebSocket hub (contract s23 supplier, s24 consumer; inv15; A79).

Each snapshot goes to the hub's 'lab' topic as one JSON payload with its kind: the lab panel's state
(LabState, kind 'lab') or what is played (HarmonyState, kind 'harmony'). The hub keeps the latest payload per
topic and kind and greets every (re)connecting page with them, so a new tab shows the chord at once (A79).

The hub is built after the lab (the gate needs the lab's scoped writes first, see HostModule.bind), so the
publisher may be bound late: until then it keeps the latest payload of each kind, and binding hands them over.
current() answers the latest of each kind either way.
"""
import threading

from ..domain.harmony import HarmonyState

TOPIC = "lab"
LAB, HARMONY = "lab", "harmony"


def payload_of(snapshot) -> dict:
    """{kind, …}: a LabState carries kind 'lab' already; a HarmonyState gets kind 'harmony'."""
    if isinstance(snapshot, dict):
        data = dict(snapshot)
    elif hasattr(snapshot, "to_json"):
        data = snapshot.to_json()
    else:
        raise TypeError(f"cannot publish {snapshot!r}")
    if "kind" not in data:
        data = {"kind": HARMONY if isinstance(snapshot, HarmonyState) else LAB, **data}
    return data


class HubPublisher:
    def __init__(self, hub=None, topic: str = TOPIC):
        self._hub, self.topic = hub, topic
        self._lock = threading.Lock()
        self._latest: dict[str, dict] = {}

    def bind(self, hub) -> None:
        """The host's hub (TopicPublisher), once it exists; the latest payloads are handed over."""
        with self._lock:
            self._hub = hub
            latest = list(self._latest.values())
        if hub is not None:
            for payload in latest:
                hub.publish(self.topic, payload)

    def publish(self, snapshot) -> None:
        payload = payload_of(snapshot)
        with self._lock:
            self._latest[payload["kind"]] = payload
            hub = self._hub
        if hub is not None:
            hub.publish(self.topic, payload)

    def current(self) -> dict:
        """{kind: latest payload} (s23.c2)."""
        with self._lock:
            return dict(self._latest)
