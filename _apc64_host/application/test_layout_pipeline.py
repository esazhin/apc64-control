from pathlib import Path

from _apc64_host.application.conftest import Catalog, ManualClock, MemorySource
from _apc64_host.application.layout_pipeline import LayoutPipeline, Restored, UnknownVersion
from _apc64_host.application.library import DuplicateName, LayoutLibrary
from _apc64_host.application.ports import ChangeKind
from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import LayoutIssue, Severity, SourceRef
from _apc64_host.domain.layout import Layer, VersionId
from _apc64_host.notation.compiler import compile_text

JAM = (Path(__file__).resolve().parents[2] / "layouts" / "jam.yaml").read_text()
R1C1 = PadPos(1, 1)


class Versions:
    """VersionStore double: newest first, stamps from a counter ('10:42' style ids are just order here)."""

    def __init__(self):
        self.saved = []

    def save(self, layout, text, content_hash):
        version = VersionId(f"2026102{len(self.saved):04d}", content_hash)
        self.saved.append((str(layout), version, text))
        return version

    def list(self, layout):
        return [v for lay, v, _ in reversed(self.saved) if lay == str(layout)]

    def read(self, layout, version):
        return next((t for lay, v, t in self.saved if lay == str(layout) and v == version), None)


class Engine:
    def __init__(self):
        self.swaps = []

    def swap(self, layout_id, layout):
        self.swaps.append((str(layout_id), layout))
        return True


class Rig:
    def __init__(self, files=None, catalog=None, library=None, compile=compile_text):
        self.clock = ManualClock()
        self.source = MemorySource(files if files is not None else {"jam": JAM})
        self.versions, self.engine = Versions(), Engine()
        self.library = library or LayoutLibrary()
        self.pipeline = LayoutPipeline(source=self.source, versions=self.versions, library=self.library,
                                       engine=self.engine, clock=self.clock, catalog=catalog, compile=compile)
        self.pipeline.start()

    def write(self, text, layout="jam"):
        self.source.files[layout] = text
        self.source.emit(layout)

    def pad(self, layout="jam"):
        return self.library.compiled(layout).page(1).binding(Layer.BASE, R1C1).actions[0].number


def test_start_loads_registers_versions_and_swaps_every_file():
    rig = Rig()
    assert rig.pad() == 36 and len(rig.versions.list("jam")) == 1 and len(rig.engine.swaps) == 1


def test_a_valid_write_goes_live_within_the_settle_window_with_a_new_version():   # A50, inv18
    rig = Rig()
    rig.write(JAM.replace("notes from 36", "notes from 38"))
    rig.clock.advance(0.2)
    assert len(rig.engine.swaps) == 1
    rig.clock.advance(0.06)
    assert len(rig.engine.swaps) == 2 and rig.pad() == 38
    assert len(rig.versions.list("jam")) == 2


def test_a_half_written_file_is_compiled_once_when_complete():   # A51, s57
    rig = Rig()
    rig.write(JAM[: len(JAM) // 2])
    rig.clock.advance(0.2)
    rig.write(JAM.replace("cc 118", "cc 119"))
    rig.clock.advance(0.25)
    assert rig.pipeline.compiles == 2 and len(rig.engine.swaps) == 2   # start + the completed file
    assert rig.library.issues("jam") == ()


def test_an_invalid_save_keeps_the_layout_shows_the_error_and_makes_no_version_until_fixed():   # A52
    rig = Rig()
    broken = JAM.replace("play: cc 118 on mpc ch 1", "play: cc 118 on mcp ch 1")
    rig.write(broken)
    rig.clock.advance(0.25)
    assert rig.pad() == 36 and len(rig.engine.swaps) == 1 and len(rig.versions.list("jam")) == 1
    assert "unknown device mcp" in rig.library.issues("jam")[0].message()
    rig.write(JAM.replace("cc 118", "cc 120"))
    rig.clock.advance(0.25)
    assert rig.library.issues("jam") == () and len(rig.versions.list("jam")) == 2 and len(rig.engine.swaps) == 2


def test_identical_content_does_nothing():   # A53, a22
    rig = Rig()
    rig.write(JAM)
    rig.source.emit("jam")
    rig.clock.advance(1.0)
    assert rig.pipeline.compiles == 1 and len(rig.engine.swaps) == 1 and len(rig.versions.list("jam")) == 1


def test_a_deleted_file_keeps_the_layout_live_and_marked():   # A56
    rig = Rig()
    del rig.source.files["jam"]
    rig.source.emit("jam", ChangeKind.DELETED)
    rig.clock.advance(0.25)
    assert rig.library.deleted("jam") and rig.library.compiled("jam") is not None
    assert len(rig.engine.swaps) == 1
    rig.write(JAM)   # the same content written again counts as new: it was gone
    rig.clock.advance(0.25)
    assert not rig.library.deleted("jam") and len(rig.engine.swaps) == 2


def test_restoring_a_version_writes_it_back_and_it_goes_live():   # A54, d120
    rig = Rig()
    for note in range(37, 41):
        rig.write(JAM.replace("notes from 36", f"notes from {note}"))
        rig.clock.advance(0.25)
    versions = rig.pipeline.versions("jam")
    assert len(versions) == 5
    ten_42 = versions[1]   # the one binding note 39
    assert rig.pipeline.restore("jam", str(ten_42)) == Restored(ten_42)
    rig.clock.advance(0.25)
    assert rig.pad() == 39 and rig.source.files["jam"] == JAM.replace("notes from 36", "notes from 39")
    assert set(versions) <= set(rig.pipeline.versions("jam"))
    assert rig.pipeline.restore("jam", "20260101T000000.000Z-000000000000") == UnknownVersion(
        "20260101T000000.000Z-000000000000")


def test_a_script_written_layout_of_64_single_pads_is_listed_and_loads():   # A44
    lines = ["name: Tonnetz C", "devices:", "  mpc: MPC Live III MIDI 1", "pages:", "  1 Grid:"]
    lines += [f"    pad r{r}c{c}: note {24 + 3 * c + 4 * r} on mpc ch 1" for r in range(1, 9) for c in range(1, 9)]
    rig = Rig({"jam": JAM})
    rig.write("\n".join(lines) + "\n", layout="tonnetz")
    rig.clock.advance(0.25)
    assert [s.name for s in rig.library.summaries()] == ["Jam", "Tonnetz C"]
    assert len(rig.library.compiled("tonnetz").page(1).layers[Layer.BASE]) == 64


def test_the_port_catalog_is_passed_into_compile():   # s89
    seen = []

    def compile_spy(text, file, ports=None):
        seen.append(ports)
        return compile_text(text, file, ports)

    rig = Rig(catalog=Catalog("MPC Live III MIDI 1", "USB MIDI Interface MIDI 1"), compile=compile_spy)
    assert seen == [["MPC Live III MIDI 1", "USB MIDI Interface MIDI 1"]]
    report = rig.pipeline.validate_text(JAM.replace("mpc: MPC Live III MIDI 1", "mpc: MIDI 1"), "draft.yaml")
    assert not report.valid and report.issues[0].message() == (
        'draft.yaml line 5, device mpc: "MIDI 1" matches MPC Live III MIDI 1 and USB MIDI Interface MIDI 1; '
        "write the full name")


def test_a_duplicate_name_is_an_issue_naming_both_files_and_nothing_swaps():   # A42, s60
    rig = Rig()
    rig.write(JAM.replace("cc 118", "cc 119"), layout="jam2")
    rig.clock.advance(0.25)
    [issue] = rig.library.issues("jam2")
    assert issue.message() == ("jam2.yaml line 3: layout name Jam is already used by jam.yaml; "
                               "rename one of them; jam.yaml stays loaded")
    assert [s for s, _ in rig.engine.swaps] == ["jam"] and rig.versions.list("jam2") == []


def test_notation_issues_leave_the_live_layout_and_are_published():   # s58 collaboration
    problem = LayoutIssue(Severity.ERROR, SourceRef("jam.yaml", 7), None, "broken", "fix")

    def compile_double(text, file, ports=None):
        if "BROKEN" not in text:
            return compile_text(text, file, ports)

        class Result:
            valid, issues, layout = False, (problem,), None
        return Result()

    rig = Rig(compile=compile_double)
    rig.write(JAM + "# BROKEN\n")
    rig.clock.advance(0.25)
    assert rig.library.issues("jam") == (problem,) and len(rig.engine.swaps) == 1


def test_validate_text_reports_counts_and_never_applies():   # A45 service side, s17.c2
    rig = Rig()
    report = rig.pipeline.validate_text(JAM.replace("notes from 36", "notes from 50"), "draft.yaml")
    assert report.valid and report.summary.startswith("valid: 1 page, 1 bank, 16 pads")
    assert rig.pad() == 36 and len(rig.engine.swaps) == 1


def test_a_library_answering_duplicate_name_blocks_the_swap():   # s60 with a library double
    class Library(LayoutLibrary):
        def register(self, layout_id, layout, warnings=()):
            return DuplicateName("other", "Jam")

    rig = Rig(library=Library())
    assert rig.engine.swaps == [] and "other.yaml" in rig.library.issues("jam")[0].message()
    assert rig.versions.saved == []
