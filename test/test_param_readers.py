"""Stock's parameter-table readers on an lfo4 build, in digikit's emulator (scripts/emu_param_readers.py).

Entries 0..320 must answer as on stock, and LFO4's ten must read LFO4's own records. Skipped
without stock 1.11 or digikit's cf_call (EMU_CF_CALL, or the path the script names).
"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import emu_param_readers as E                            # noqa: E402

CF_CALL = pathlib.Path(os.environ.get("EMU_CF_CALL", E.CF_CALL))


def test_the_stock_readers_on_lfo4(tmp_path):
    if not (E.STOCK.exists() and CF_CALL.exists()):
        pytest.skip("stock 1.11 or digikit's cf_call is not here")
    from dnfw.cli.files import read_image
    out = tmp_path / "lfo4_DN2_1.11.syx"
    done = subprocess.run([sys.executable, "-c", "import sys; from dnfw.cli.main import main; sys.exit(main(sys.argv[1:]))",
                           "mods", "apply", "--mod", "lfo4", str(E.STOCK), "-o", str(out)],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    pcs, problems, _sources, blind = E.check(read_image(out), read_image(E.STOCK), CF_CALL)
    assert len(pcs) == 17 and not problems, problems[:5]
    assert blind == [0x400C243C]
