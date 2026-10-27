"""The settings file that remembers the harmony inputs (§2.7 q7), on tmp_path."""
from _apc64_lab.application.harmony_tracker import INPUTS_KEY, HarmonyTracker
from _apc64_lab.application.ports import LabSettingsStore
from _apc64_lab.infrastructure.settings_file import SettingsFile


def test_a_choice_survives_a_restart(tmp_path):
    path = tmp_path / "lab-settings.json"
    settings = SettingsFile(path)
    assert isinstance(settings, LabSettingsStore) and settings.get(INPUTS_KEY, []) == []
    HarmonyTracker(settings=settings).select_inputs(["Keystation 49 MIDI 1"])
    assert HarmonyTracker(settings=SettingsFile(path)).inputs()["inputs"] == ["Keystation 49 MIDI 1"]


def test_a_damaged_file_reads_as_the_defaults(tmp_path):
    path = tmp_path / "lab-settings.json"
    path.write_text("{oops")
    assert SettingsFile(path).get(INPUTS_KEY, []) == []
    SettingsFile(path).put(INPUTS_KEY, ["MPC"])
    assert SettingsFile(path).get(INPUTS_KEY) == ["MPC"]
