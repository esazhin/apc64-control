"""The pattern editor's writes (Phase 2): validated before writing, canonical YAML from data, stale and existing
files refused, every replaced text kept as a version, the pattern playing following a save, the edited pattern
played live from the next step."""
import shutil
from pathlib import Path

import pytest

from _apc64_host.domain.issues import DomainInvariantError

from _apc64_host.domain.midi import NoteOff, NoteOn
from _apc64_lab.application.pattern_library import (
    PatternLibrary, PatternRefused, content_hash, id_for, pattern_text, users_of,
)
from _apc64_lab.application.test_performer import GUITAR, STEP, Rig
from _apc64_lab.application.test_performer_chords import PICKER
from _apc64_lab.infrastructure.pattern_files import PatternFiles

ROOT = Path(__file__).resolve().parents[2]
NEW = {"name": "My pick", "meter": "3/4", "step": "1/8", "lanes": {"1": ". x . x . x", "R": "X . . . . ."}}


@pytest.fixture
def library(tmp_path):
    shutil.copytree(ROOT / "patterns", tmp_path / "patterns")
    return PatternLibrary(PatternFiles(tmp_path / "patterns", tmp_path / "versions"))


def test_data_is_written_as_canonical_yaml_with_a_header_and_reads_back_the_same(library, tmp_path):
    answer = library.save("my-pick", data=NEW, create=True)
    assert answer["message"] == "created patterns/my-pick.yaml (My pick)" and answer["created"]
    text = (tmp_path / "patterns" / "my-pick.yaml").read_text()
    assert text.startswith("# My pick\n# Written by the pattern editor") and "  1: . x . x . x\n  R: X . . . . .\n" in text
    assert library.get("my-pick")[1] == library.check_data(NEW)[0] and answer["hash"] == content_hash(text)
    assert id_for("Travis pick 2!") == "travis-pick-2" and id_for("") == "pattern"


def test_an_invalid_pattern_is_never_written_and_every_issue_is_named(library, tmp_path):
    with pytest.raises(PatternRefused) as refused:
        library.save("bad", data={"name": "Bad", "length": 8, "lanes": {"1": "x . . .", "2": ". y . . . . . ."}})
    issues = refused.value.issues
    assert refused.value.status == 400 and [i["field"] for i in issues] == ["lane 2", "lane 1"]
    assert issues[1]["text"] == ("bad.yaml, lane 1: 4 steps; length is 8; write one cell per step: . (rest), x (hit) "
                                 "or X (accent); spaces and | are ignored")
    with pytest.raises(PatternRefused) as text_refused:
        library.save("bad", text="name: Bad\nstep: 1/5\nlanes:\n  1: x\n")
    assert text_refused.value.issues[0]["line"] == 2 and not (tmp_path / "patterns" / "bad.yaml").exists()
    with pytest.raises(PatternRefused) as name_refused:
        library.save("My Pick!", data=NEW)
    assert name_refused.value.problem == "'My Pick!' is not a pattern file name"


def test_stale_and_existing_files_are_refused_and_replaced_texts_are_kept_and_restored(library, tmp_path):
    text, digest = library.read("travis")
    with pytest.raises(PatternRefused) as exists:
        library.save("travis", data=NEW, create=True)
    assert exists.value.code == "exists" and exists.value.status == 409
    with pytest.raises(PatternRefused) as stale:
        library.save("travis", data=NEW, base="0123456789ab")
    assert stale.value.code == "stale"
    library.save("travis", data={**NEW, "name": "Travis 2"}, base=digest)
    versions = library.versions("travis")
    assert len(versions) == 1 and library._source.version("travis", versions[0]["version"]) == text
    restored = library.restore("travis", versions[0]["version"][:20])
    assert restored["message"].startswith("restored patterns/travis.yaml from version ")
    assert library.read("travis")[0] == text and len(library.versions("travis")) == 2
    gone = library.delete("travis")
    assert gone["message"].startswith("deleted patterns/travis.yaml; kept as version ")
    assert library.find("travis") is None and len(library.versions("travis")) == 3
    with pytest.raises(PatternRefused):
        library.restore("travis", "1999")


def test_a_pattern_a_layout_plays_is_not_deleted(library):
    class Layout:
        name = "Guitar picker"

        class definition:
            class performer:
                pattern, slots = "Travis pick", ("strum", None)
    library.users = lambda pattern_id: users_of(pattern_id, [Layout], library.names())
    for pattern_id in ("travis", "strum"):
        with pytest.raises(PatternRefused) as refused:
            library.delete(pattern_id)
        assert refused.value.code == "in_use" and refused.value.problem.startswith("Guitar picker plays ")
    assert library.delete("waltz")["id"] == "waltz"


def test_every_shipped_pattern_round_trips_through_its_canonical_text():
    shipped = PatternLibrary(PatternFiles(ROOT / "patterns"))
    for pattern_id, result in shipped.compiled().items():
        again = shipped.compile_text(pattern_text(result.pattern, result.file), result.file)
        assert again.valid and again.pattern == result.pattern, pattern_id


def test_the_edited_pattern_plays_live_from_the_next_step_and_a_save_makes_it_the_files(library):
    rig = Rig(GUITAR, patterns=library)
    rig.play(NoteOn(3, 57, 100))
    rig.until(STEP + 0.01)
    rig.sent()
    data = rig.service.state()["pattern"]["data"]
    edited = {**data, "lanes": {**data["lanes"], "3": "x x x x | x x x x"}}
    answer = rig.service.change(pattern_data=edited, edits="arpeggio-manual-bass")
    assert answer["message"] == "playing 1-2-3 + bass as edited (not saved)" and answer["pattern"]["edited"]
    assert answer["running"] and answer["step"] == 2                         # no restart
    rig.until(2 * STEP + 0.01)
    assert (3, 57) in [(m.channel, m.note) for m in rig.sent() if isinstance(m, NoteOn)]   # step 3 hits string 3 now
    with pytest.raises(PatternRefused):
        rig.service.change(pattern_data={**data, "lanes": {"1": "x"}}, edits="arpeggio-manual-bass")
    saved = rig.service.save_pattern("arpeggio-manual-bass", data=edited, base=answer["pattern"]["hash"],
                                     edits="arpeggio-manual-bass")
    state = rig.service.state()
    assert saved["message"].startswith("saved patterns/arpeggio-manual-bass.yaml") and not state["pattern"]["edited"]
    copy = rig.service.save_pattern("my-copy", data={**edited, "name": "My copy"}, create=True)
    assert copy["id"] == "my-copy" and rig.service.state()["pattern"]["id"] == "arpeggio-manual-bass"
    rig.service.change(pattern="my-copy")
    rig.service.delete_pattern("my-copy")
    assert rig.service.state()["pattern"]["id"] == "arpeggio"                # the first valid one goes on


# --- unsaved edits, kept per pattern for the session -----------------------------------------------------------
def travis_edited(rig):
    data = rig.service.state()["pattern"]["data"]
    assert data["name"] == "Travis pick"
    return {**data, "length": 16, "lanes": {key: f"{row} | {row}" for key, row in data["lanes"].items()}}


def test_an_edit_is_kept_when_another_pattern_is_chosen_and_plays_again_by_any_route(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)          # travis plays; slots 1, 2 and 4
    edited = travis_edited(rig)
    answer = rig.service.change(pattern_data=edited, edits="travis")
    assert answer["pattern"]["edited"] and answer["pattern"]["length"] == 16
    revision = answer["pattern_revision"]
    rig.service.select_slot(1)                                              # the unit's slot pad, or the page's
    state = rig.service.state()
    assert state["pattern"]["id"] == "arpeggio-manual-bass" and not state["pattern"]["edited"]
    assert state["pattern_revision"] > revision                              # the page's draft follows this
    assert state["edits"] == [{"id": "travis", "name": "Travis pick", "new": False}]
    assert [row["id"] for row in state["patterns"] if row["edited"]] == ["travis"]
    assert [slot["edited"] for slot in state["slots"] if slot] == [False, True, False]
    back = rig.service.select_slot(2)
    assert back["pattern"]["edited"] and back["pattern"]["length"] == 16 and back["message"] == \
        "pattern Travis pick (edited, not saved)"
    assert rig.service._core.pattern.length == 16                            # what plays is what the page shows
    rig.service.change(pattern="waltz")
    assert rig.service.change(pattern="travis")["pattern"]["length"] == 16   # the page's select, the API, the CLI


def test_an_edit_of_a_pattern_that_is_not_playing_is_refused_as_stale(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)
    edited = travis_edited(rig)
    rig.service.select_slot(1)                                              # the unit switched; the page has not yet
    with pytest.raises(PatternRefused) as stale:
        rig.service.change(pattern_data=edited, edits="travis")
    assert (stale.value.status, stale.value.code) == (409, "stale")
    assert stale.value.problem == 'this edit is of "travis", but "arpeggio-manual-bass" plays now'
    state = rig.service.state()
    assert state["pattern"]["id"] == "arpeggio-manual-bass" and state["edits"] == []


def test_save_drops_the_edit_revert_plays_the_file_and_a_write_from_elsewhere_keeps_it(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)
    edited = travis_edited(rig)
    base = rig.service.state()["pattern"]["hash"]
    rig.service.change(pattern_data=edited, edits="travis")
    reverted = rig.service.change(revert="travis")
    assert not reverted["pattern"]["edited"] and reverted["pattern"]["length"] == 8 and reverted["edits"] == []
    assert reverted["message"] == "travis: the unsaved edit dropped" and rig.service._core.pattern.length == 8
    assert rig.service.change(pattern_data=rig.service.state()["pattern"]["data"], edits="travis")["edits"] == []
    rig.service.change(pattern_data=edited, edits="travis")                 # an edit equal to its file is the file
    assert rig.service.state()["pattern"]["hash"] == base                    # the base a Save sends
    library.save("travis", data={**edited, "name": "Travis by CLI"}, base=base)   # changed on disk meanwhile
    rig.service._after_write("travis")
    state = rig.service.state()
    assert state["pattern"]["edited"] and state["pattern"]["hash"] == base and rig.service._core.pattern.length == 16
    with pytest.raises(PatternRefused) as conflict:
        rig.service.save_pattern("travis", data=edited, base=base, edits="travis")
    assert conflict.value.code == "stale"                                    # the page's Save: refused, edit kept
    fresh = library.read("travis")[1]
    rig.service.save_pattern("travis", data=edited, base=fresh, edits="travis")
    state = rig.service.state()
    assert not state["pattern"]["edited"] and state["edits"] == [] and state["pattern"]["hash"] == library.read("travis")[1]


def test_a_new_pattern_is_kept_as_the_sessions_one_and_save_as_makes_it_a_file_that_plays(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)
    answer = rig.service.change(pattern_data=NEW, edits=None)
    assert answer["pattern"]["id"] is None and answer["pattern"]["new"] and answer["slot"] is None
    assert answer["edits"] == [{"id": None, "name": "My pick", "new": True}]
    rig.service.select_slot(2)
    assert rig.service.state()["pattern"]["id"] == "travis"
    again = rig.service.change(new_pattern=True)
    assert again["pattern"]["new"] and again["message"] == "pattern My pick (new, not saved)"
    rig.service.save_pattern("my-pick", data=NEW, create=True, edits=None)
    state = rig.service.state()
    assert state["pattern"]["id"] == "my-pick" and not state["pattern"]["edited"] and state["edits"] == []
    with pytest.raises(DomainInvariantError):
        rig.service.change(new_pattern=True)


def test_save_as_of_an_edit_plays_the_new_file_and_delete_drops_an_edit(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)
    edited = travis_edited(rig)
    rig.service.change(pattern_data={**edited, "name": "Travis long"}, edits="travis")
    rig.service.save_pattern("travis-long", data={**edited, "name": "Travis long"}, create=True, edits="travis")
    state = rig.service.state()
    assert state["pattern"]["id"] == "travis-long" and state["edits"] == []
    rig.service.change(pattern="waltz")
    rig.service.change(pattern_data={**rig.service.state()["pattern"]["data"], "swing": 60}, edits="waltz")
    rig.service.delete_pattern("waltz")
    state = rig.service.state()
    assert state["edits"] == [] and state["pattern"]["id"] == "arpeggio" and not state["pattern"]["edited"]


def test_a_held_note_is_let_go_cleanly_when_a_kept_edit_plays_again(library):
    rig = Rig(PICKER.format(tuning="e-standard"), patterns=library)
    rig.service.select_slot(1)
    data = rig.service.state()["pattern"]["data"]
    rig.service.change(pattern_data={**data, "manual": [5, 6], "lanes": {**data["lanes"], "4": "x . . . x . . ."}},
                       edits="arpeggio-manual-bass")
    rig.service.change(pattern="waltz")
    rig.play(NoteOn(4, 52, 100))
    rig.service.select_slot(1)                                              # the edit again: string 4 is the pattern's
    rig.play(NoteOff(4, 52))
    rig.until(10.0)
    assert not rig.service.state()["running"] and rig.service._core.pressed() == ()
