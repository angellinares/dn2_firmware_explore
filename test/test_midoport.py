"""Probe transport regressions; no MIDI device or RtMidi installation needed."""
from collections import deque
import itertools
from pathlib import Path
import struct
import sys

import mido
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dn2probe
import midoport
import winmidi


class Input:
    def __init__(self):
        self.messages = deque()
        self.repeated = None
        self.closed = False

    def poll(self):
        return self.messages.popleft() if self.messages else self.repeated

    def close(self):
        self.closed = True


class Output:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


class Backend:
    def __init__(self):
        self.ins = ['Other input', 'Elektron Digitone II']
        self.outs = ['Elektron Digitone II', 'Other output']
        self.incoming, self.outgoing = Input(), Output()
        self.opened = []

    def get_input_names(self):
        return self.ins

    def get_output_names(self):
        return self.outs

    def open_input(self, name):
        self.opened.append(('in', name))
        return self.incoming

    def open_output(self, name, *, autoreset):
        assert autoreset is False
        self.opened.append(('out', name))
        return self.outgoing


@pytest.fixture
def backend(monkeypatch):
    backend = Backend()

    def factory(name, **kwargs):
        assert name == 'mido.backends.rtmidi'
        assert kwargs == {'api': 'MACOSX_CORE', 'use_environ': False, 'load': True}
        return backend

    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(mido, 'Backend', factory)
    return backend


def test_directional_port_order_and_selection(backend):
    assert midoport.ports() == (backend.ins, backend.outs)
    port = midoport.Port()
    assert backend.opened == [('in', backend.ins[1]), ('out', backend.outs[0])]
    port.close()


def test_one_explicit_index_only_resolves_other_direction(backend):
    backend.ins = ['Unrelated input', 'Another input']
    port = midoport.Port(i=1)
    assert backend.opened == [('in', 'Another input'), ('out', 'Elektron Digitone II')]
    port.close()


def test_exact_name_wins_over_longer_substring(backend):
    backend.ins = ['Digitone II', 'Digitone II extra']
    backend.outs = ['Digitone II extra', 'Digitone II']
    port = midoport.Port()
    assert backend.opened == [('in', 'Digitone II'), ('out', 'Digitone II')]
    port.close()


@pytest.mark.parametrize('names,index,error', [
    ([], None, 'no MIDI'),
    (['Elektron Digitone'], None, 'no MIDI'),
    (['DN2 Digitone II A', 'DN2 Digitone II B'], None, 'more than one'),
    (['Digitone II', 'Digitone II'], None, 'more than one'),
    (['Digitone II', 'Digitone II'], 1, 'duplicate'),
    (['Digitone II'], -1, 'index -1'),
    (['Digitone II'], 1, 'index 1'),
])
def test_ambiguous_or_invalid_ports_open_nothing(backend, names, index, error):
    backend.ins = names
    with pytest.raises(OSError, match=error):
        midoport.Port(i=index)
    assert backend.opened == []


def test_invalid_output_opens_nothing(backend):
    with pytest.raises(OSError, match='out index -1'):
        midoport.Port(o=-1)
    assert backend.opened == []


def test_sysex_framing_and_early_reply(backend):
    port = midoport.Port()
    request = dn2probe.req_hello(0x201)
    port.send(request)
    assert bytes(backend.outgoing.sent[0].bytes()) == request
    first, second = b'\xf0\x7d\x01\xf7', b'\xf0\x7d\x02\xf7'
    backend.incoming.messages.extend([
        mido.Message('clock'), mido.Message('note_on'),
        mido.Message.from_bytes(first), mido.Message.from_bytes(second)])
    assert port.receive(1, until=lambda messages: messages == [first]) == [first]
    assert len(backend.incoming.messages) == 1
    assert port.receive(1, until=bool) == [second]
    port.close()


@pytest.mark.parametrize('raw', [b'', b'\x90\x40\x7f', b'\xf0\x7d',
                               b'\xf0\x80\xf7', b'\xf0\x7d\xf7\xf8'])
def test_invalid_or_non_sysex_send_is_rejected(backend, raw):
    port = midoport.Port()
    with pytest.raises(ValueError):
        port.send(raw)
    assert backend.outgoing.sent == []
    port.close()


@pytest.mark.parametrize('traffic', [None, mido.Message('clock')])
def test_receive_deadline_with_silence_or_continuous_short_messages(backend, monkeypatch, traffic):
    port = midoport.Port()
    backend.incoming.repeated = traffic
    ticks = itertools.count(0, 0.01)
    monkeypatch.setattr(midoport.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(midoport.time, 'sleep', lambda seconds: None)
    assert port.receive(0.05) == []
    port.close()


def test_output_open_failure_closes_input(backend, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('output unavailable')
    monkeypatch.setattr(backend, 'open_output', fail)
    with pytest.raises(OSError, match='output unavailable'):
        midoport.Port()
    assert backend.incoming.closed


def test_close_attempts_both_even_if_input_close_fails(backend, monkeypatch):
    port = midoport.Port()
    def fail():
        raise OSError('close failed')
    monkeypatch.setattr(backend.incoming, 'close', fail)
    with pytest.raises(OSError, match='close failed'):
        port.close()
    assert backend.outgoing.closed
    port.close()  # idempotent, including after a failure


def test_cli_hello_uses_existing_codec_and_closes_ports(backend, capsys):
    payload = struct.pack('>HI', 3, 123) + b'mac-test\0'
    def reply(seq, cmd):
        raw = dn2probe.HEADER + dn2probe.pack7(struct.pack('>HBB', seq, cmd, 0) + payload) + b'\xf7'
        return mido.Message.from_bytes(raw)
    backend.incoming.messages.extend([
        reply(0x200, 0x81), reply(0x201, 0x82), reply(0x201, 0x81)])
    assert dn2probe.main(['hello']) == 0
    assert 'mac-test' in capsys.readouterr().out
    assert bytes(backend.outgoing.sent[0].bytes()) == dn2probe.req_hello(0x201)
    assert backend.incoming.closed and backend.outgoing.closed


def test_cli_ports(backend, capsys):
    assert dn2probe.main(['ports', '--backend', 'rtmidi']) == 0
    text = capsys.readouterr().out
    assert '1 Elektron Digitone II' in text and '0 Elektron Digitone II' in text
    assert backend.opened == []


def test_optional_packages_missing_but_selftest_still_works(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'mido', None)
    assert dn2probe.main(['selftest']) == 0
    assert dn2probe.main(['ports', '--backend', 'rtmidi']) == 1
    assert "pip install -e '.[midi]'" in capsys.readouterr().out


def test_windows_auto_keeps_existing_backend(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'mido', None)
    assert dn2probe.midi_backend('auto') is winmidi


def test_cli_command_failure_still_closes_ports(backend, monkeypatch, capsys):
    def fail(*args):
        raise TimeoutError('no answer')
    monkeypatch.setitem(dn2probe.COMMANDS, 'hello', fail)
    assert dn2probe.main(['hello']) == 1
    assert 'no answer' in capsys.readouterr().out
    assert backend.incoming.closed and backend.outgoing.closed
