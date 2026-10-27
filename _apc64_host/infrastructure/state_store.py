"""StateStore in the state directory, outside the repository (contract §7, s36/s53/s67/s85):
the holding marker, calibration.json and nav.json (the last NavState and strip positions).

The marker exists while the host holds the unit; finding it at start means a release was missed and the
unit may still be in DAW mode (a7). JSON files are written temp + rename; a damaged file reads as nothing.
Shift is momentary (q5), so a stored NavState always comes back with Shift released.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from ..domain.calibration import Calibration
from ..domain.controls import Strip
from ..domain.layout import BankNo, LayoutId, NavState, PageNo
from ..domain.midi import Value14

MARKER, CALIBRATION, NAV = "holding", "calibration.json", "nav.json"

log = logging.getLogger(__name__)


class FileStateStore:
    def __init__(self, state_dir):
        self._dir = Path(state_dir).expanduser()

    # --- holding marker --------------------------------------------------------------------------------------
    def marker_set(self) -> None:
        self._write(MARKER, f"pid {os.getpid()} at {datetime.now().astimezone().isoformat()}\n")

    def marker_clear(self) -> None:
        (self._dir / MARKER).unlink(missing_ok=True)

    def marker_present(self) -> bool:
        return (self._dir / MARKER).exists()

    # --- calibration ------------------------------------------------------------------------------------------
    def calibration_get(self) -> Calibration | None:
        data = self._read_json(CALIBRATION)
        if data is None:
            return None
        try:
            return Calibration(datetime.fromisoformat(data["at"]), data["bottom_left"], data["top_right"])
        except Exception as error:
            log.warning("state: %s unusable (%s)", CALIBRATION, error)
            return None

    def calibration_put(self, calibration: Calibration | None) -> None:
        if calibration is None:
            (self._dir / CALIBRATION).unlink(missing_ok=True)
            return
        self._write(CALIBRATION, json.dumps({"at": calibration.at.isoformat(),
                                             "bottom_left": int(calibration.bottom_left),
                                             "top_right": int(calibration.top_right)}, indent=1))

    # --- navigation and strip positions --------------------------------------------------------------------------
    def nav_get(self) -> tuple[NavState, dict[tuple, Value14]] | None:
        data = self._read_json(NAV)
        if data is None:
            return None
        try:
            layout = LayoutId(data["layout"]) if data.get("layout") else None
            nav = NavState(layout, PageNo(data.get("page", 1)), BankNo(data.get("bank", 1)), shift=False)
            positions = {(LayoutId(s["layout"]), BankNo(s["bank"]), Strip(s["strip"])): Value14(s["value"])
                         for s in data.get("strips", [])}
            return nav, positions
        except Exception as error:
            log.warning("state: %s unusable (%s)", NAV, error)
            return None

    def nav_put(self, nav: NavState, positions: dict[tuple, Value14]) -> None:
        strips = [{"layout": str(layout), "bank": int(bank), "strip": strip.n, "value": int(value)}
                  for (layout, bank, strip), value in sorted(positions.items(), key=lambda kv: (
                      str(kv[0][0]), int(kv[0][1]), kv[0][2].n))]
        self._write(NAV, json.dumps({"layout": nav.layout, "page": int(nav.page), "bank": int(nav.bank),
                                     "strips": strips}, indent=1))

    # --- files ------------------------------------------------------------------------------------------------------
    def _read_json(self, name: str):
        try:
            return json.loads((self._dir / name).read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as error:
            log.warning("state: %s unreadable (%s)", name, error)
            return None

    def _write(self, name: str, text: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._dir / name
        temporary = target.with_name(name + ".tmp")
        with open(temporary, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
