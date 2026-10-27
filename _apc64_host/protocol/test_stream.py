import random

from _apc64_host.protocol.conftest import capture
from _apc64_host.protocol.stream import MidiStreamSplitter


def test_any_chunking_gives_back_the_captured_messages_in_order():
    captured = [raw for port, raw in capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")]
    stream = b"".join(captured)
    rng = random.Random(3)
    for _ in range(20):
        splitter, out, i = MidiStreamSplitter(), [], 0
        while i < len(stream):
            size = rng.randint(1, 40)
            out += splitter.feed(stream[i:i + size])
            i += size
        assert out == captured


def test_running_status_is_expanded_and_stray_data_dropped():
    assert MidiStreamSplitter().feed(bytes.fromhex("1290357F3600")) == [bytes.fromhex("90357F"),
                                                                        bytes.fromhex("903600")]
    assert MidiStreamSplitter().feed(bytes.fromhex("C005 06")) == [bytes.fromhex("C005"), bytes.fromhex("C006")]


def test_realtime_bytes_come_out_alone_even_inside_a_sysex():
    assert MidiStreamSplitter().feed(bytes.fromhex("F04700F8 5319000100F7")) == [
        b"\xf8", bytes.fromhex("F0470053 19000100F7")]


def test_a_sysex_cut_short_by_a_status_byte_is_dropped():
    assert MidiStreamSplitter().feed(bytes.fromhex("F0470053 96007F")) == [bytes.fromhex("96007F")]
