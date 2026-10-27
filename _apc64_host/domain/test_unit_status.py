import pytest

from _apc64_host.domain.unit_status import (
    Absent, Asking, Busy, Consent, ConsentSource, Decline, Declined, Held, Holder, HolderChanged, MaybeStuck,
    NoPermission, OpenFailed, OpenFailure, Opened, Presence, Released, ReleaseReason, StaleMarker, Unplugged,
    transition,
)

BITWIG = Holder("Bitwig Studio")


def run(status, *observations):
    for observation in observations:
        status = transition(status, observation)
    return status


def test_appearing_unit_is_asked_about_and_a_second_one_is_ignored():
    assert run(Absent(), Presence(True)) == Asking()
    assert run(Absent(), Presence(True, ignored=1)).notices == ("second APC64 ignored",)
    assert run(Asking(), Presence(False)) == Absent()


def test_consent_alone_changes_nothing_and_an_open_decides():
    assert run(Asking(), Consent(ConsentSource.BANNER)) == Asking()
    held = run(Asking(), Opened(ConsentSource.BANNER))
    assert held.held and held.text == "Held"
    assert run(Asking(), Opened(ConsentSource.AUTO_ACCEPT)).text == "Held (taken automatically)"
    assert run(Asking(), Opened(ConsentSource.AGENT)).text == "Held (taken by command-line tool)"
    warned = run(Asking(), Opened(ConsentSource.BANNER, "untested firmware 1.2.2.0"))
    assert warned.firmware_warning == "untested firmware 1.2.2.0"


@pytest.mark.parametrize("failure, expected, text", [
    (OpenFailed(OpenFailure.BUSY, BITWIG), Busy(holder=BITWIG), "Busy: held by Bitwig Studio"),
    (OpenFailed(OpenFailure.NO_PERMISSION), NoPermission(), "No permission to open APC64"),
    (OpenFailed(OpenFailure.NO_REPLY), Asking(("No APC64 identity reply",)), "Take control of APC64?"),
    (OpenFailed(OpenFailure.GONE), Absent(), "APC64 not connected"),
])
def test_open_failures_map_to_their_status(failure, expected, text):
    status = run(Asking(), failure)
    assert status == expected and status.text == text


def test_a_device_that_is_not_an_apc64_keeps_the_question_open_with_why():
    assert run(Asking(), OpenFailed(OpenFailure.NOT_AN_APC64, detail="not an APC64 (product 0x51)")).notices == (
        "not an APC64 (product 0x51)",)


def test_busy_follows_the_holder_and_asks_again_when_it_lets_go():
    busy = run(Asking(), HolderChanged(BITWIG))
    assert busy == Busy(holder=BITWIG)
    assert run(busy, HolderChanged(None)) == Asking()


def test_a_decline_leaves_the_unit_alone_even_when_another_program_takes_it():
    declined = run(Asking(), Decline())
    assert declined == Declined() and declined.text == "Not held"
    assert run(declined, HolderChanged(BITWIG)) == Declined()
    assert run(declined, Presence(False), Presence(True)) == Asking()


def test_releases_ask_again_and_unplug_and_fault_say_why():
    held = Held(by=ConsentSource.BANNER)
    assert run(held, Released(ReleaseReason.RELEASE)) == Asking()
    assert run(held, Released(ReleaseReason.STOP)) == Asking()
    assert run(held, Released(ReleaseReason.UNPLUG)).text == "APC64 unplugged: released"
    assert run(held, Released(ReleaseReason.FAULT)).notices == ("Released after an internal error",)
    assert run(held, Presence(False)) == Unplugged()
    assert run(held, Presence(False), Presence(True)) == Asking()
    assert run(Asking(), Released(ReleaseReason.RELEASE)) == Asking()


def test_a_stale_marker_warns_that_the_unit_may_still_be_in_daw_mode():
    stuck = run(Absent(), Presence(True), StaleMarker())
    assert stuck == MaybeStuck() and stuck.status == "maybe_stuck"
    assert stuck.text == "APC64 may still be in DAW mode: Take to reset, or replug it"
    assert run(stuck, Opened(ConsentSource.BANNER)).held


def test_every_status_has_its_api_name():
    assert {s.STATUS for s in (Absent, Asking, Declined, Busy, NoPermission, Held, Unplugged, MaybeStuck)} == {
        "absent", "asking", "declined", "busy", "no_permission", "held", "unplugged", "maybe_stuck"}
    with pytest.raises(TypeError):
        transition(Absent(), object())
