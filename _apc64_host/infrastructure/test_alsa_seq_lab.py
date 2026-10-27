"""Contract 2 T13: ALSA sequencer MIDI out, reused unchanged (inv13; s21 supplier, s22 our side).

The lab's played notes reach the routing target through contract 1's adapter: what the engine hands it is what
the sequencer client is given, byte for byte, and a missing port is reported unavailable. Uses contract 1's
sequencer double (no ALSA device is opened)."""
from _apc64_host.application.ports import SendResult
from _apc64_host.domain.midi import ChannelPressure, ControlChange, NoteOff, NoteOn, PolyAftertouch
from _apc64_host.infrastructure.test_alsa_seq import MPC, adapter, world


def outputs(seq):
    return [(c[1], c[2]) for c in seq.calls if c[0] == "output"]


def test_note_on_48_velocity_38_poly_aftertouch_and_cc_30_reach_mpc_unchanged():
    # A40 (MIDI-out side), A34's CC 30, s21.c1, s22.c1
    seq, at = world()
    sequencer = adapter(seq)
    messages = [NoteOn(1, 48, 38), PolyAftertouch(1, 48, 70), ChannelPressure(1, 70), ControlChange(1, 30, 65),
                NoteOff(1, 48, 0)]
    assert [sequencer.send(MPC, m) for m in messages] == [SendResult.SENT] * 5
    assert outputs(seq) == [(b"\x90\x30\x26", at["mpc"]), (b"\xa0\x30\x46", at["mpc"]), (b"\xd0\x46", at["mpc"]),
                            (b"\xb0\x1e\x41", at["mpc"]), (b"\x80\x30\x00", at["mpc"])]


def test_a_missing_target_reports_unavailable_and_sends_nothing():
    # s21.c2: 'port unavailable' (MISSING), shown in the activity list by the engine
    seq, _ = world()
    sequencer = adapter(seq)
    assert sequencer.send("Nord Stage", NoteOn(1, 48, 38)) is SendResult.MISSING
    assert outputs(seq) == []
