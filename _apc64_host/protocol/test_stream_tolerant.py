"""Contract 2 T15 (a33): the splitter's channel_in_sysex mode, used only by the session's SysEx tap."""
from _apc64_host.protocol.stream import MidiStreamSplitter

DUMP = bytes([0xF0, 0x47, 0x00, 0x53, 0x14, 0x00, 0x04, 0x07, 0x01, 0x02, 0x03, 0xF7])
TURN = bytes.fromhex("B0 5A 01")


def test_a_channel_message_inside_a_sysex_comes_out_on_its_own_and_the_sysex_goes_on():
    splitter = MidiStreamSplitter(channel_in_sysex=True)
    stream = DUMP[:6] + TURN + DUMP[6:9] + TURN + bytes([0xF8]) + DUMP[9:]
    out = []
    for i in range(0, len(stream), 2):                        # chunked like rawmidi reads
        out += splitter.feed(stream[i:i + 2])
    assert out == [TURN, TURN, bytes([0xF8]), DUMP]


def test_other_status_bytes_still_cut_the_sysex_short_and_the_default_is_unchanged():
    tolerant = MidiStreamSplitter(channel_in_sysex=True)
    assert tolerant.feed(DUMP[:6] + bytes([0xF0]) + DUMP[1:]) == [DUMP]     # a new F0 restarts it
    assert tolerant.feed(DUMP[:6] + TURN[:2] + bytes([0xF7])) == [DUMP[:6] + bytes([0xF7])]   # half a message dropped
    plain = MidiStreamSplitter()
    out = plain.feed(DUMP[:6] + TURN + DUMP[6:])
    assert out[0] == TURN and DUMP not in out                                 # contract 1: the dump is cut short
