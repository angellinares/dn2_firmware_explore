"""Optional Mido/RtMidi transport for dn2probe; CoreMIDI on macOS.

Same ports/Port/send/receive/close surface as winmidi. Imports and port opens
are lazy, so the probe codec and selftest need no MIDI packages or device.
"""
import sys
import time


def _backend():
    try:
        import mido
        backend = mido.Backend('mido.backends.rtmidi',
                               api='MACOSX_CORE' if sys.platform == 'darwin' else None,
                               use_environ=False, load=True)
    except ImportError as exc:
        raise OSError("RtMidi backend needs optional MIDI packages: "
                      "python -m pip install -e '.[midi]'") from exc
    return mido, backend


def ports():
    """-> (input names, output names), each in the backend's own order."""
    _, backend = _backend()
    return backend.get_input_names(), backend.get_output_names()


def _pick(names, name, index, kind):
    if index is None:
        hits = [k for k, n in enumerate(names) if n == name]
        if not hits:
            hits = [k for k, n in enumerate(names) if name in n]
        if len(hits) != 1:
            listing = '; '.join('%d %s' % pair for pair in enumerate(names)) or 'none'
            raise OSError('%s MIDI %s port matching %r. Ports: %s. Use --in/--out.'
                          % ('no' if not hits else 'more than one', kind, name, listing))
        index = hits[0]
    if not 0 <= index < len(names):
        raise OSError('no MIDI %s index %d: there are %d ports' % (kind, index, len(names)))
    selected = names[index]
    if names.count(selected) != 1:
        # Mido opens by name, so an index cannot disambiguate identical names.
        raise OSError('duplicate MIDI %s name %r: rename or disconnect one endpoint'
                      % (kind, selected))
    return selected


class Port:
    def __init__(self, name='Digitone II', i=None, o=None):
        mido, backend = _backend()
        nin = _pick(backend.get_input_names(), name, i, 'in')
        nout = _pick(backend.get_output_names(), name, o, 'out')
        self._message = mido.Message
        self._input = backend.open_input(nin)
        try:
            self._output = backend.open_output(nout, autoreset=False)
        except BaseException:
            self._input.close()
            raise

    def send(self, data):
        if self._output is None:
            raise OSError('MIDI port is closed')
        message = self._message.from_bytes(data)
        if message.type != 'sysex':
            raise ValueError('probe transport sends SysEx only')
        self._output.send(message)

    def receive(self, seconds=1.0, until=None):
        """Collect complete F0..F7 messages; short MIDI never extends the deadline."""
        if self._input is None:
            raise OSError('MIDI port is closed')
        messages, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            message = self._input.poll()
            if message is None:
                time.sleep(0.002)
            elif message.type == 'sysex':
                messages.append(bytes(message.bytes()))
                if until and until(messages):
                    break
        return messages

    def close(self):
        incoming, outgoing = self._input, self._output
        self._input = self._output = None
        try:
            if incoming is not None:
                incoming.close()
        finally:
            if outgoing is not None:
                outgoing.close()
