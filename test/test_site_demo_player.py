"""The sound demo on the Waverider page (`site/js/demo-player.js`): its level columns are the
recording's, and the drawn screen shows what has played. Regenerate `data-peaks` with
`python test/test_site_demo_player.py` after replacing the recording."""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import wave

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "site/waverider.html"
DEMO = re.compile(r'<div class="demo" data-demo([^>]*)>', re.S)
COLS = 96


def attrs() -> dict[str, str]:
    return dict(re.findall(r'data-([a-z]+)="([^"]*)"', DEMO.search(PAGE.read_text(encoding="utf-8")).group(1)))


def peaks_of(path: pathlib.Path) -> tuple[str, float]:
    """the level of each of COLS equal parts (RMS, 2 decimals), and the length in seconds"""
    with wave.open(str(path)) as w:
        n, rate = w.getnframes(), w.getframerate()
        x = np.frombuffer(w.readframes(n), "<i2").astype(np.float64) / 32768
    per = n // COLS
    return ",".join(f"{np.sqrt((x[i * per:(i + 1) * per] ** 2).mean()):.2f}".lstrip("0") for i in range(COLS)), n / rate


def test_peaks_are_the_recordings():
    a = attrs()
    want, seconds = peaks_of(ROOT / "site" / re.search(r'<audio[^>]*src="([^"]+)"', PAGE.read_text(encoding="utf-8")).group(1))
    assert a["peaks"] == want, "rerun: python test/test_site_demo_player.py"
    assert abs(float(a["duration"]) - seconds) < 0.01
    for span in a["solos"].split(","):
        lo, hi = map(float, span.split("-"))
        assert 0 <= lo < hi <= float(a["duration"])


def test_the_screen_shows_what_has_played():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    a = attrs()
    script = ("import('./site/js/demo-player.js').then(({frame, W}) => {"
              f"const cfg = {{title: 'DEMO', peaks: '{a['peaks']}'.split(',').map(Number), solos: [[0, 58]]}};"
              "const lit = (px, x) => { let n = 0; for (let y = 24; y < 52; y++) n += px[y * W + x]; return n; };"
              "const out = {};"
              "for (const t of [0, 60.245]) { const px = frame(cfg, t, 120.49);"
              "  out[t] = {left: lit(px, 30), right: lit(px, 100), header: px[0]}; }"
              "console.log(JSON.stringify(out)); })")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    start, half = got["0"], got["60.245"]
    assert start["header"] == 1
    assert half["left"] > start["left"]          # column 14 has played at half way: solid, not dotted
    assert half["right"] == start["right"]       # column 84 has not: dotted either way


if __name__ == "__main__":
    text = PAGE.read_bytes().decode("utf-8")          # keeps the page's line endings
    src = re.search(r'<audio[^>]*src="([^"]+)"', text).group(1)
    peaks, seconds = peaks_of(ROOT / "site" / src)
    text = re.sub(r'(data-demo[^>]*data-peaks=")[^"]*"', lambda m: m.group(1) + peaks + '"', text, count=1)
    PAGE.write_bytes(text.encode("utf-8"))
    print(f"data-peaks rewritten ({seconds:.2f} s)", file=sys.stderr)
