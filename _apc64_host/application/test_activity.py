from _apc64_host.application.activity import ActivityLog
from _apc64_host.domain.effects import ActivityEntry, ActivityResult


def sent(subject, note=None, at=None):
    return ActivityEntry(subject, ActivityResult.SENT, "note 36 ch 10", "MPC Live III MIDI 1", note=note, at=at)


def test_recent_returns_the_newest_200_newest_first():   # A127
    log = ActivityLog()
    for i in range(500):
        log.append(ActivityEntry(f"pad {i}", ActivityResult.UNBOUND, at=float(i)))
    recent = log.recent(200)
    assert len(recent) == 200
    assert recent[0].subject == "pad 499" and recent[-1].subject == "pad 300"
    assert len(log.recent(1000)) == 200 and [e.subject for e in log.recent(2)] == ["pad 499", "pad 498"]


def test_aftertouch_is_folded_into_its_notes_entry():   # q7
    log = ActivityLog()
    log.append(sent("note 53", note=53))
    log.append(sent("pad r1c1"))
    for pressure in range(1, 201):
        log.fold(53, pressure)
    recent = log.recent()
    assert len(recent) == 2
    assert recent[1].subject == "note 53" and recent[1].aftertouch == 200
    assert log.fold(99, 5) is None   # no entry for that note: nothing to fold into


def test_subscribers_get_every_new_or_updated_entry_in_order():   # s27.c2
    log, seen = ActivityLog(), []
    token = log.subscribe(seen.append)
    first = log.append(sent("note 53", note=53))
    log.fold(53, 10)
    log.append(sent("pad r1c1"))
    assert [(r.id, r.folded, r.entry.aftertouch) for r in seen] == [(first.id, False, None), (first.id, True, 10),
                                                                   (first.id + 1, False, None)]
    log.unsubscribe(token)
    log.append(sent("pad r1c2"))
    assert len(seen) == 3


def test_text_of_an_entry_reads_control_message_port_and_result():   # A120 text
    assert sent("pad r1c1").text() == "pad r1c1 → note 36 ch 10 → MPC Live III MIDI 1: sent"
