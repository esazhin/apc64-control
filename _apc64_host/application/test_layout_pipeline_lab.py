"""Contract 2 T17: the layout pipeline, reused unchanged, for generated layouts (inv10, inv14, pi2; s35, s36,
s37, s39 suppliers; A14, and the pipeline half of A15/a12).

The real pipeline compiles with the registered section compilers (the composition root passes
compile_text with sections=…), registers, keeps versions and hot-reloads the live layout into the real engine,
whose single load point calls the module's on_layout_loaded with the new section."""
from functools import partial

from _apc64_host.application.conftest import MemorySource
from _apc64_host.application.layout_pipeline import LayoutPipeline
from _apc64_host.application.test_engine_modules import Lab, LabRig
from _apc64_host.application.test_tweaks_sections import SECTIONS, TONNETZ
from _apc64_host.application.tweaks import Saved, TweakService
from _apc64_host.domain.controls import Encoder
from _apc64_host.domain.layout import LayoutId
from _apc64_host.infrastructure.version_store import FileVersionStore
from _apc64_host.notation.compiler import compile_text


class SectionLab(Lab):
    def layout_sections(self):
        return SECTIONS

    def on_layout_loaded(self, layout, section):
        self.calls.append(("on_layout_loaded", layout.id if layout else None, dict(section) if section else None))


def rig(tmp_path):
    lab = SectionLab()
    engine_rig = LabRig(layouts=(), module=lab)
    source = MemorySource({"tonnetz-c": TONNETZ})
    pipeline = LayoutPipeline(source=source, versions=FileVersionStore(tmp_path / "versions"),
                              library=engine_rig.library, engine=engine_rig.engine, clock=engine_rig.clock,
                              compile=partial(compile_text, sections=SECTIONS))
    pipeline.start()
    engine_rig.hold()
    engine_rig.engine.load("tonnetz-c")
    lab.calls.clear()
    return engine_rig, source, pipeline, lab


def test_a14_a_second_file_with_the_same_display_name_is_refused(tmp_path):
    engine_rig, source, pipeline, lab = rig(tmp_path)
    source.write("tonnetz-copy", TONNETZ)                         # the agent writes a second 'Tonnetz C'
    engine_rig.clock.advance(0.3)
    issues = engine_rig.library.all_issues()
    assert [i.message() for i in issues] == [
        "tonnetz-copy.yaml line 2: layout name Tonnetz C is already used by tonnetz-c.yaml; "
        "rename one of them; tonnetz-c.yaml stays loaded"]
    assert engine_rig.engine.layout.id == "tonnetz-c" and lab.calls == []


def test_an_edit_of_the_active_files_lab_scheme_compiles_and_the_engine_reloads_it(tmp_path):
    # A15 (pipeline half): within the watch's settle time, at the same layout
    engine_rig, source, pipeline, lab = rig(tmp_path)
    source.write("tonnetz-c", TONNETZ.replace("scheme: fifths", "scheme: root-highlight"))
    engine_rig.clock.advance(0.25)
    assert lab.calls == [("on_layout_loaded", "tonnetz-c",
                          {"generator": "tonnetz", "base": "C3", "scheme": "root-highlight"})]
    live = engine_rig.engine.layout
    assert live.sections["lab"]["scheme"] == "root-highlight"
    assert live.page(1).encoder.module_action is not None          # the implied bindings come along
    assert len(pipeline.versions(LayoutId("tonnetz-c"))) == 2


def test_an_invalid_edit_keeps_the_last_good_layout_and_shows_its_errors(tmp_path):
    # d9: an invalid change keeps the last good layout
    engine_rig, source, pipeline, lab = rig(tmp_path)
    source.write("tonnetz-c", TONNETZ.replace("scheme: fifths", "scheme: rainbow"))
    engine_rig.clock.advance(0.25)
    assert lab.calls == [] and engine_rig.engine.layout.sections["lab"]["scheme"] == "fifths"
    assert [i.control for i in engine_rig.library.all_issues()] == ["scheme"]


def test_a_section_tweak_is_registered_as_a_new_version_and_reloaded(tmp_path):
    # s39: tweaks hand the saved file to the pipeline; the live layout reloads (A16's path, host side)
    engine_rig, source, pipeline, lab = rig(tmp_path)
    tweaks = TweakService(source, sections=SECTIONS, on_saved=pipeline.changed)
    source.emit_on_write = False                                   # only the hand-over may trigger the reload
    assert isinstance(tweaks.save_section_field("tonnetz-c", "lab.base", "D3"), Saved)
    engine_rig.clock.advance(0.25)
    assert lab.calls == [("on_layout_loaded", "tonnetz-c", {"generator": "tonnetz", "base": "D3", "scheme": "fifths"})]
    assert engine_rig.engine.snapshot().layout.page(1).binding(engine_rig.engine.nav.layer, Encoder()) is not None
