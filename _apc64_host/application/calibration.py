"""CalibrationService: the Note-view pad map as a labelled assumption (contract inv9, d147–d149, s21, s51, s67).

start() waits for the bottom-left pad, then the top-right pad, played in the unit's Note view; the two
notes make a Calibration (domain/calibration.py) that is stored and serves position_of(note). Every
position is labelled 'calibrated <time> (assumed)': the unit's Note-view settings cannot be read, so a
later change on the unit cannot be noticed (A123). The engine shows every played note-on to observe();
it is used only while a calibration is running and does not stop the note from being routed.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable

from ..domain.calibration import UNKNOWN_POSITION, Calibration, PadPosition
from ..domain.effects import PlayedMidi, UnitView
from ..domain.issues import DomainInvariantError
from ..domain.midi import NoteOn
from .ports import StateStore


class CalibrationStep(StrEnum):
    IDLE = "idle"
    BOTTOM_LEFT = "waiting for bottom-left"
    TOP_RIGHT = "waiting for top-right"
    DONE = "done"


_PROMPTS = {CalibrationStep.IDLE: "", CalibrationStep.BOTTOM_LEFT: "press the bottom-left pad",
            CalibrationStep.TOP_RIGHT: "press the top-right pad", CalibrationStep.DONE: "calibrated"}


@dataclass(frozen=True)
class CalibrationStatus:
    step: CalibrationStep = CalibrationStep.IDLE
    problem: str | None = None

    @property
    def text(self) -> str:
        return _PROMPTS[self.step]


class CalibrationService:
    def __init__(self, store: StateStore, now: Callable[[], datetime] = datetime.now):
        self._store = store
        self._now = now
        self._current: Calibration | None = store.calibration_get()
        self._status = CalibrationStatus()
        self._bottom_left: int | None = None
        self._subscribers: list[Callable[[CalibrationStatus], None]] = []

    # --- the page's side ------------------------------------------------------------------------------
    def start(self) -> CalibrationStatus:
        self._bottom_left = None
        return self._set(CalibrationStatus(CalibrationStep.BOTTOM_LEFT))

    def cancel(self) -> CalibrationStatus:
        self._bottom_left = None
        return self._set(CalibrationStatus())

    def status(self) -> CalibrationStatus:
        return self._status

    def subscribe(self, callback: Callable[[CalibrationStatus], None]) -> None:
        self._subscribers.append(callback)

    # --- the engine's side ----------------------------------------------------------------------------
    def observe(self, played: PlayedMidi, view: UnitView | None = None) -> None:
        message = played.message
        if not isinstance(message, NoteOn) or message.velocity == 0:
            return
        if self._status.step is CalibrationStep.BOTTOM_LEFT:
            self._bottom_left = int(message.note)
            self._set(CalibrationStatus(CalibrationStep.TOP_RIGHT))
        elif self._status.step is CalibrationStep.TOP_RIGHT:
            try:
                calibration = Calibration(self._now(), self._bottom_left, int(message.note))
            except DomainInvariantError as error:
                self._bottom_left = None
                self._set(CalibrationStatus(CalibrationStep.BOTTOM_LEFT, f"{error.problem}; {error.fix}"))
                return
            self._store.calibration_put(calibration)
            self._current = calibration
            self._set(CalibrationStatus(CalibrationStep.DONE))

    # --- readers --------------------------------------------------------------------------------------
    def current(self) -> Calibration | None:
        return self._current

    def position_of(self, note: int) -> PadPosition | None:
        return self._current.position_of(note) if self._current else None

    def label(self) -> str:
        return self._current.label if self._current else UNKNOWN_POSITION

    def _set(self, status: CalibrationStatus) -> CalibrationStatus:
        self._status = status
        for callback in list(self._subscribers):
            callback(status)
        return status
