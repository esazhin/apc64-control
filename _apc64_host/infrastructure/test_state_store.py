import json
from datetime import UTC, datetime

from _apc64_host.application.ports import StateStore
from _apc64_host.domain.calibration import Calibration
from _apc64_host.domain.controls import PadPos, Strip
from _apc64_host.domain.layout import BankNo, LayoutId, NavState, PageNo
from _apc64_host.domain.midi import Value14
from _apc64_host.infrastructure.state_store import FileStateStore


def test_the_holding_marker_is_set_cleared_and_reported(tmp_path):
    # T16, s36.c2, s85, inv14 (a7: a missed release shows as 'may still be in DAW mode' at the next start)
    store = FileStateStore(tmp_path / "state")
    assert isinstance(store, StateStore)
    assert store.marker_present() is False
    store.marker_set()
    assert store.marker_present() is True
    assert FileStateStore(tmp_path / "state").marker_present() is True     # survives a restart
    store.marker_clear()
    store.marker_clear()                                                   # clearing twice is harmless
    assert store.marker_present() is False


def test_calibration_round_trips_and_can_be_forgotten(tmp_path):
    # T16, s67.c2
    store = FileStateStore(tmp_path)
    assert store.calibration_get() is None
    taken = Calibration(datetime(2026, 10, 23, 10, 42, 5, tzinfo=UTC), 36, 99)
    store.calibration_put(taken)
    again = FileStateStore(tmp_path).calibration_get()
    assert again == taken and again.position_of(53).pad == PadPos(3, 2)
    assert again.label == taken.label
    store.calibration_put(None)
    assert store.calibration_get() is None


def test_nav_and_strip_positions_round_trip_and_shift_never_comes_back_held(tmp_path):
    # T16, s53.c2, q5 (Shift is momentary), q6 (the last layout/page/bank is restored on take)
    store = FileStateStore(tmp_path)
    assert store.nav_get() is None
    nav = NavState(LayoutId("jam"), PageNo(3), BankNo(2), shift=True)
    positions = {(LayoutId("jam"), BankNo(2), Strip(1)): Value14(8192),
                 (LayoutId("tonnetz"), BankNo(1), Strip(8)): Value14(16383)}
    store.nav_put(nav, positions)
    restored, strips = FileStateStore(tmp_path).nav_get()
    assert restored == NavState(LayoutId("jam"), PageNo(3), BankNo(2), shift=False)
    assert strips == positions
    assert all(isinstance(k[0], LayoutId) and isinstance(k[2], Strip) for k in strips)
    store.nav_put(NavState(None), {})
    assert FileStateStore(tmp_path).nav_get() == (NavState(None), {})


def test_files_are_written_whole_and_damaged_ones_read_as_nothing(tmp_path):
    store = FileStateStore(tmp_path)
    store.nav_put(NavState(LayoutId("jam")), {})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["nav.json"]          # no temp file left behind
    assert json.loads((tmp_path / "nav.json").read_text())["layout"] == "jam"
    (tmp_path / "nav.json").write_text("{not json")
    (tmp_path / "calibration.json").write_text('{"at": "yesterday"}')
    assert store.nav_get() is None and store.calibration_get() is None
    (tmp_path / "nav.json").write_text('{"layout": "jam", "page": 9, "bank": 1, "strips": []}')
    assert store.nav_get() is None
