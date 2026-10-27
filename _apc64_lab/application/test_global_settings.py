"""T27: GlobalSettingsService (s31 supplier; inv8, inv9; A62–A67, d88–d94)."""
from _apc64_host.domain.outbound import WriteCapability
from _apc64_lab.application.conftest import Events, FakeBackups, FakeMemory, Wall, globals_block
from _apc64_lab.application.global_settings import GlobalSettingsService
from _apc64_lab.application.guarded_writer import GuardedWriter
from _apc64_lab.domain.memory import OutcomeCode, OutcomeKind


class Rig:
    def __init__(self):
        self.events = Events()
        self.memory, self.backups = FakeMemory(self.events), FakeBackups(self.events)
        self.writer = GuardedWriter(self.memory, self.backups, WriteCapability("t"), wall=Wall())
        self.service = GlobalSettingsService(self.writer)


def test_the_named_fields_read_with_their_shown_values():   # A62
    found = {f["field"]: f for f in Rig().service.read()["fields"]}
    assert found["led_level"]["text"] == "75%" and found["led_level"]["label"] == "LED level"
    assert found["cv1_source"]["text"].endswith("[TBD]") and "device_mode" in found and "drum16_note" in found


def test_a_change_backs_up_the_block_and_keeps_bytes_0_to_19():   # A63, inv1, inv3
    rig = Rig()
    outcome = rig.service.change({"led_level": 100})
    assert (outcome.result, outcome.message) == (OutcomeKind.PUSHED, "set LED level 100%")
    assert rig.backups.get(outcome.backup).data == globals_block().raw
    assert rig.memory.globals.led_percent == 100 and rig.memory.globals.raw[:20] == globals_block().raw[:20]


def test_device_mode_needs_confirmation():   # A64, d91, inv8
    rig = Rig()
    outcome = rig.service.change({"device_mode": "standalone"})
    assert outcome.result is OutcomeKind.REFUSED and outcome.message == (
        "device mode change needs confirmation: it changes how the unit starts; repeat the command with confirm")
    assert rig.memory.writes() == [] and rig.backups.order == []
    assert rig.service.change({"device_mode": "standalone"}, confirm=True).result is OutcomeKind.PUSHED
    assert rig.service.change({"device_mode": "standalone"}).result is OutcomeKind.UNCHANGED   # no change, no hazard


def test_two_fields_in_one_command_take_one_backup_and_one_write():   # A65, d92
    rig = Rig()
    outcome = rig.service.change({"led_level": 100, "cv2_channel": 4})
    assert outcome.message == "set LED level 100% and CV2 channel 4"
    assert [e[0] for e in rig.events] == ["read", "backup", "write", "read"]
    assert rig.memory.globals.led_percent == 100 and rig.memory.globals.cv_channel(2) == 4


def test_an_out_of_range_value_is_refused_naming_the_field():   # A66, d93
    rig = Rig()
    outcome = rig.service.change({"cv3_channel": 17})
    assert outcome.message == "CV3 channel 17: channels are 1–16" and outcome.field == "cv3_channel"
    assert outcome.code is OutcomeCode.INVALID and rig.events == []


def test_the_value_it_already_has_writes_nothing():   # A67, d94
    rig = Rig()
    rig.service.change({"led_level": 100})
    rig.events.clear()
    outcome = rig.service.change({"led_level": "100%"})
    assert (outcome.result, outcome.message) == (OutcomeKind.UNCHANGED, "LED level unchanged; nothing written")
    assert rig.memory.writes() == []
