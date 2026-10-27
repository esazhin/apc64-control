from datetime import datetime

from _apc64_host.application.calibration import CalibrationService, CalibrationStep
from _apc64_host.application.conftest import MemoryStore
from _apc64_host.domain.calibration import Calibration
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.effects import PlayedMidi, UnitView
from _apc64_host.domain.layout import UnitPortRole
from _apc64_host.domain.midi import NoteOff, NoteOn, PolyAftertouch

AT = datetime(2026, 10, 23, 14, 2)


def played(note, velocity=100):
    return PlayedMidi(UnitPortRole.NOTES, NoteOn(1, note, velocity))


def test_two_corner_notes_make_a_stored_calibration_labelled_assumed():   # A121
    store = MemoryStore()
    service = CalibrationService(store, now=lambda: AT)
    assert service.current() is None and service.label() == "pad position unknown"
    assert service.start().step is CalibrationStep.BOTTOM_LEFT
    service.observe(PlayedMidi(UnitPortRole.NOTES, PolyAftertouch(1, 36, 5)), UnitView.NOTE)   # ignored
    service.observe(PlayedMidi(UnitPortRole.NOTES, NoteOff(1, 36)), UnitView.NOTE)              # ignored
    service.observe(played(36), UnitView.NOTE)
    assert service.status().step is CalibrationStep.TOP_RIGHT
    service.observe(played(99), UnitView.NOTE)
    assert service.status().step is CalibrationStep.DONE
    assert store.calibration == Calibration(AT, 36, 99) == service.current()
    position = service.position_of(53)
    assert position.assumed and position.pad == PadPos(3, 2)
    assert service.label() == "calibrated 14:02 (assumed)"


def test_without_a_calibration_positions_are_unknown():   # A122
    service = CalibrationService(MemoryStore())
    service.observe(played(53, 56), UnitView.NOTE)   # not calibrating: nothing happens
    assert service.position_of(53) is None and service.label() == "pad position unknown"
    assert service.status().step is CalibrationStep.IDLE


def test_a_stored_calibration_keeps_its_time_label_whatever_changed_on_the_unit():   # A123
    service = CalibrationService(MemoryStore(calibration=Calibration(AT, 36, 99)),
                                 now=lambda: datetime(2026, 10, 24, 9, 0))
    assert service.label() == "calibrated 14:02 (assumed)"
    assert service.position_of(36).pad == PadPos(1, 1)


def test_cancel_keeps_the_previous_calibration_and_a_reversed_pair_asks_again():   # s21
    store = MemoryStore(calibration=Calibration(AT, 36, 99))
    service, seen = CalibrationService(store, now=lambda: AT), []
    service.subscribe(seen.append)
    service.start()
    service.observe(played(60), UnitView.NOTE)
    assert service.cancel().step is CalibrationStep.IDLE
    assert service.current() == Calibration(AT, 36, 99)
    service.start()
    service.observe(played(60), UnitView.NOTE)
    service.observe(played(40), UnitView.NOTE)
    status = service.status()
    assert status.step is CalibrationStep.BOTTOM_LEFT and "bottom-left pad first" in status.problem
    assert store.calibration == Calibration(AT, 36, 99)
    assert [s.step for s in seen][:3] == [CalibrationStep.BOTTOM_LEFT, CalibrationStep.TOP_RIGHT,
                                          CalibrationStep.IDLE]
    assert service.status().text == "press the bottom-left pad"
