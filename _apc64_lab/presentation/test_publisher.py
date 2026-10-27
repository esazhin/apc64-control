"""T34: LabStatePublisher over the hub (s23 supplier, s24 consumer; A79's lab half)."""
from _apc64_host.presentation.ws_hub import WebSocketHub
from _apc64_lab.application.ports import LabState, LabStatePublisher
from _apc64_lab.domain.harmony import Harmony
from _apc64_lab.presentation.publisher import HubPublisher, payload_of


class HubDouble:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def c_major():
    harmony = Harmony()
    for note in (48, 52, 55):
        state = harmony.note_on(note)
    return state


def test_a_harmony_state_goes_to_the_lab_topic_as_kind_harmony_and_current_returns_it():
    hub = HubDouble()
    publisher = HubPublisher(hub)
    publisher.publish(c_major())
    (topic, payload), = hub.published
    assert topic == "lab" and payload["kind"] == "harmony" and payload["chord"] == "C"
    assert [n["note"] for n in payload["held"]] == [48, 52, 55]
    assert publisher.current()["harmony"]["chord"] == "C"


def test_the_lab_state_keeps_its_own_kind():
    hub = HubDouble()
    publisher = HubPublisher(hub)
    publisher.publish(LabState(active={"layout": "tonnetz-c", "name": "Tonnetz C"}))
    assert hub.published[0][1]["kind"] == "lab" and hub.published[0][1]["active"]["name"] == "Tonnetz C"
    assert set(publisher.current()) == {"lab"}


def test_it_implements_the_application_port():
    assert isinstance(HubPublisher(), LabStatePublisher)


def test_before_the_hub_exists_the_latest_of_each_kind_is_kept_and_handed_over_on_bind():
    publisher = HubPublisher()
    publisher.publish(LabState(message="first"))
    publisher.publish(LabState(message="second"))
    publisher.publish(c_major())
    hub = HubDouble()
    publisher.bind(hub)
    assert [(t, p["kind"]) for t, p in hub.published] == [("lab", "lab"), ("lab", "harmony")]
    assert hub.published[0][1]["message"] == "second"


class Nothing:
    def subscribe(self, *a, **k):
        return lambda: None


def test_the_real_hub_keeps_the_latest_payload_per_kind_for_new_pages():   # s24, A79
    hub = WebSocketHub(Nothing(), Nothing(), Nothing())
    publisher = HubPublisher(hub)
    publisher.publish(LabState(message="lab state"))
    publisher.publish(c_major())
    assert hub.current("lab", "harmony")["chord"] == "C"
    assert hub.current("lab", "lab")["message"] == "lab state"


def test_payloads_are_plain_json():
    import json
    json.dumps(payload_of(c_major()))
    json.dumps(payload_of(LabState(generators=({"name": "tonnetz"},))))
