"""The Rust packer (tools/aplibpack) gives the bytes of the Python packer.

`aplibpack.pack` uses the Rust packer when it is built, so every build and most tests pack with
it. `pack_python` stays the reference: the site's JS packer and the Rust packer must each equal
it byte for byte (test_js_codec.py for JS). Same bytes, not only a valid stream, because the
size, the offset window and the match lengths all follow from the exact parse.
"""

import random

import pytest

from dnfw.codec import aplib, aplibpack


@pytest.fixture(scope="module")
def rust():
    found = aplibpack.rust_packer()
    if found is None:
        pytest.skip("the Rust packer is not built: run cargo build --release in tools/aplibpack")
    return found


def _edge_inputs():
    rng = random.Random(20261110)
    noise = bytes(rng.randrange(256) for _ in range(300_000))
    words = b" ".join(rng.choice([b"LFO", b"DEST", b"0x4000", b"\x00\x00\x00\x01", b"move.l"])
                      for _ in range(60_000))
    far = bytes(rng.randrange(256) for _ in range(6_000))
    return {
        "empty": b"", "one byte": b"\x7f", "two bytes": b"ab", "zeros": bytes(5_000),
        "a run longer than MAX_MATCH": b"\xff" * 10_000, "noise": noise, "words": words,
        # one block twice, 6,000 bytes apart: the match is far (over FAR_THRESHOLD)
        "far repeat": far + b"x" * 7 + far,
        "code-like": bytes(rng.choice([0x4E, 0x75, 0x20, 0x6F, 0x00, 0x04]) for _ in range(200_000)),
    }


@pytest.mark.parametrize("name", list(_edge_inputs()))
def test_rust_gives_the_python_bytes(rust, name):
    data = _edge_inputs()[name]
    got = aplibpack.pack(data)
    assert got == aplibpack.pack_python(data), name
    assert not data or aplib.depack(got) == data         # depack refuses an empty stream


@pytest.mark.parametrize("depth, max_offset", [(1, aplibpack.PACK_MAX_OFFSET), (8, 4_000), (32, 100)])
def test_the_options_reach_the_rust_packer(rust, depth, max_offset):
    data = _edge_inputs()["far repeat"] + _edge_inputs()["words"][:50_000]
    assert aplibpack.pack(data, depth, max_offset) == aplibpack.pack_python(data, depth, max_offset)


def test_every_stock_section(rust, dn2):
    """The Python side takes about 95 s here, once: MAIN OS alone is 71 s."""
    for section in dn2.container.sections:
        content = section.unpack()
        if content is not None:
            assert aplibpack.pack(content) == aplibpack.pack_python(content), f"section {section.id}"


def test_python_is_the_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("DNFW_APLIBPACK", "python")
    assert aplibpack.rust_packer() is None
    monkeypatch.setenv("DNFW_APLIBPACK", str(tmp_path / "no-such-packer"))
    assert aplibpack.rust_packer() is None
    assert aplib.depack(aplibpack.pack(b"fallback " * 100)) == b"fallback " * 100
