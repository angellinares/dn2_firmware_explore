"""The per-block call in digikit's native SHARC engine: the Python runner's result, about 20 times faster.

    import sharc_native
    engine = sharc_native.Engine(lib, image_memory, python_runner)    # after fx.bind()
    engine.block_call(frame_bytes)
    kind, info, steps = engine.run(8_000_000, hooks, stop_at=m4.UNPACK_RETURN)

digikit's `native/sharc` is its Python core (`tools/sharc_core`) transpiled to Rust, so it
has the Python core's gaps and none of `sharc_dn2_fixups.py`. Measured on 277760a
(2026-10-14) over the Waverider block call: of the fix-ups that fire there, the SIMD
two-pass (G1) no longer changes any output word, form by form or all off together, and
G3 on Type 4b was our own mistake (Type 4b has no long word; see sharc_dn2_fixups.py).
One still does, a register write after the step, so it is applied here from the host:

  G2  `Rn = data32` in SIMD also sets Sn
  G3 (Type 3b's long-word pairs), G4, G11  carried the same way (an NW address into an
      I register; FEXT (SE) unmasked); none fired in the frames checked, so these three
      are untested here

Not carried: G5 (two addresses the core decodes at the wrong width: refused here), G6/G8
(a conditional form the core stops on: the engine stops too, and the run says so), G12 to
G14 (bit-reverse, Type 1a in SIMD, fixed-point CLIP: the engine does without them, so code
that needs one stops or differs). The library must decode our image at run time (option 4):
it was generated with the stock image's instructions built in, and without the option it
runs stock's instruction wherever we patched one.

So a native run is trusted only where it is compared: `scripts/sharc_native_check.py`
runs both engines over the same blocks, bit for bit, with a control; the Waverider tests
compare the machine's output with the model whichever engine ran.

The engine steps one instruction per call (the fix-ups need the address before each
step), about 0.6 s a block against 11 s. With G2 in digikit's core it could run a
block in one call, about 0.04 s.
"""

from __future__ import annotations

import ctypes
import struct
import types

import sharc_dn2_fixups as fx
import sharc_waverider_m4 as m4


OPT_PERIPHERAL_MODEL = 22      # digikit main's native option: IIR0 (the Rust twin of sharc_core/iir.py)
IIR0_DMASTAT = 0x310C4004      # IIR0 + 0x04


class Engine:
    """One native engine holding the state. `state` is the engine itself, so the taps
    written for the Python runner (`m2.word(r.state, a)`, `m2.word_reg(r, "R12")`) read
    it unchanged."""

    def __init__(self, library, image_memory, python_runner, host_fixups: bool = True,
                 peripherals: bool = True):
        import sharc_transpile_run as tr  # noqa: PLC0415  (digikit's, importable after fx.bind)
        # the binding's own staleness check imports digikit's transpiler (and mypy); the
        # comparison with the Python runner is the check here
        tr.check_build_info = lambda info, path: None
        if peripherals:     # the engine refuses an MMR it has no value for: IIR0's DMASTAT starts at 0
            python_runner.state.mmrs.setdefault(IIR0_DMASTAT, fx.Const(0))
        self.core = tr.NativeCore(tr.pack_image(image_memory), str(library))
        tr.to_native(self.core, python_runner.state)
        self.core.set_option(tr.OPT_RUNTIME_DECODE, 1)
        if peripherals:     # IIR0 in the engine (digikit's peripheral model), so the Formant runs in every gate
            self.core.set_option(getattr(tr, "OPT_PERIPHERAL_MODEL", OPT_PERIPHERAL_MODEL), 1)
        self.library = self.core.info()
        self.decode = python_runner._decode
        self.host_fixups = host_fixups
        self.kind: dict = {}                    # pc -> None | pre(engine) -> post() | None
        self.counts = {"G2": 0, "G3 load": 0, "G3 store": 0, "G4": 0, "G11": 0}
        self.state = self

    # -- what the taps read ------------------------------------------------------------
    def native_word(self, addr: int) -> int | None:
        raw = self.core._lib.sharc_native_peek(self.core._handle, addr, 4)
        return raw & 0xFFFFFFFF if raw >> 32 > 0 else None

    def native_reg(self, code: int) -> int | None:
        raw = self.core._lib.sharc_native_get_reg(self.core._handle, code)
        return raw & 0xFFFFFFFF if raw >> 32 == 0xFFFFFFFF else None

    def set_reg(self, code: int, value: int) -> None:
        self.core._lib.sharc_native_set_reg(self.core._handle, code, 1, value & 0xFFFFFFFF, 0xFFFFFFFF)

    def poke(self, addr: int, value: int) -> None:
        if self.core.poke(addr, struct.pack("<I", value & 0xFFFFFFFF), 1) != 4:
            raise SystemExit(f"native poke {addr:#x} did not take")

    def simd(self) -> bool:
        return bool((self.native_reg(fx.UREG_CODES["MODE1"]) or 0) >> 21 & 1)

    # -- the host-side fix-ups ---------------------------------------------------------
    def classify(self, pc: int):
        if pc in fx.AS_2C:
            raise SystemExit(f"sw {pc:#x} needs fix-up G5 (decode width), which the native engine cannot take")
        if not self.host_fixups:
            return None
        insn = self.decode(pc)
        t, f, F = insn.type_name, insn.fields, fx.F
        if t in ("17a", "17b"):
            return self._imm(t, f)
        if t == "3b" and fx.Fixups.is_long(t, f):
            return self._long_word(t, f, pc)
        if t in fx.FEXT_SE_FORMS:
            got = fx.fext_se_fields(f)
            return self._fext_se(*got) if got else None
        return None

    def _imm(self, t, f):
        F = fx.F
        code = F(f, "ureg")
        value = ((F(f, "data[31:16]") << 16) | F(f, "data[15:0]")) if t == "17a" else \
            fx._signed(F(f, "data[15:0]"), 16) & 0xFFFFFFFF
        if code < 16:                           # G2
            def pre(e):
                if not e.simd():
                    return None

                def post():
                    e.set_reg(code + 80, value)
                    e.counts["G2"] += 1
                return post
            return pre
        if t == "17a" and 16 <= code < 32 and fx.NW_LO <= value < fx.NW_HI:      # G4
            def pre(e):
                def post():
                    e.set_reg(code, 4 * value)
                    e.counts["G4"] += 1
                return post
            return pre
        return None

    def _long_word(self, t, f, pc):
        F = fx.F
        if fx.cond_of(f) != 31:
            raise SystemExit(f"a conditional long-word transfer at sw {pc:#x}: not carried to the native engine")
        if F(f, "g"):
            return None

        def pre(e):
            iv = e.native_reg(16 + F(f, "i"))
            if iv is None:
                return None
            if t == "4b":
                off = fx._signed((F(f, "data[5:5]") << 5) | F(f, "data[4:0]"), 6) * 8
                code = F(f, "dreg")
            else:
                mv = e.native_reg(32 + F(f, "m"))
                if mv is None:
                    return None
                off = fx._signed(mv, 32) * 8
                code = F(f, "ureg")
            addr = iv if F(f, "u") else (iv + off) & 0xFFFFFFFF
            if F(f, "d"):
                _, values = fx.fm._lw_store_pair(_Regs(e), code)

                def post():
                    for k, v in enumerate(values):
                        if isinstance(v, fx.Const):
                            e.poke(addr + 4 * k, v.value)
                    e.counts["G3 store"] += 1
                return post
            codes = fx.fm._lw_load_codes(code)

            def post():
                for k, c in enumerate(codes):
                    v = e.native_word(addr + 4 * k)
                    if v is not None:
                        e.set_reg(c, v)
                e.counts["G3 load"] += 1
            return post
        return pre

    def _fext_se(self, rn, rx, pos, length):
        def pre(e):
            pairs = [(rn, rx)] + ([(rn + 80, rx + 80)] if e.simd() else [])
            before = {dst: e.native_reg(src) for dst, src in pairs}

            def post():
                for dst, src in before.items():
                    if src is None:
                        continue
                    buggy = fx._signed(src >> pos, min(length, 32)) & 0xFFFFFFFF if length else 0
                    right = fx.fext_se(src, pos, length)
                    if buggy != right and e.native_reg(dst) == buggy:
                        e.set_reg(dst, right)
                        e.counts["G11"] += 1
            return post
        return pre

    # -- running ------------------------------------------------------------------------
    def block_call(self, frame: bytes) -> "Engine":
        """`m4.unpack_call` on this engine: a fresh call of sw 0x1c2712 with FRAME in the
        frame source it copies from."""
        idx = self.native_word(m4.RX_INDEX) or 0
        # the caller's stack pointer, the same at every call (see m4.unpack_call)
        at_return = self.core._lib.sharc_native_get_pc(self.core._handle) == m4.UNPACK_RETURN
        i7 = self.native_reg(fx.UREG_CODES["I6" if at_return else "I7"])
        rx = m4.RX_BASE + (idx << 8)
        self.core.fresh_call(m4.UNPACK, m4.UNPACK_CALLER)
        for name, v in {"R4": 0x268438, "R8": m4.UNPACK_LOCAL, "R12": rx, "I6": i7, "I7": i7 - 16}.items():
            self.set_reg(fx.UREG_CODES[name], v)
        for k in range(10):
            self.poke(m4.UNPACK_LOCAL + 4 * k, 0)
        self.poke(i7 + 4, 0)
        self.poke(i7 + 8, m4.RX_PAGE + (idx << 11))
        if self.core.poke(rx, frame, 1) != len(frame):
            raise SystemExit("the frame did not go into the native engine's memory")
        return self

    def run(self, max_steps: int, hooks: dict, stop_at: int):
        """Step to STOP_AT, calling HOOKS[pc](engine) before the instruction at pc.
        -> ("halt", info, steps) as `fx.run` returns it: info.pc_sw is STOP_AT on arrival,
        else where it stopped, with info.reason."""
        lib, handle, kind = self.core._lib, self.core._handle, self.kind
        get_pc, step = lib.sharc_native_get_pc, lib.sharc_native_step
        for n in range(max_steps):
            pc = get_pc(handle)
            if pc == stop_at:
                return ("halt", types.SimpleNamespace(pc_sw=pc, reason="reached the stop address"), n)
            hook = hooks.get(pc)
            if hook:
                hook(self)
            try:
                pre = kind[pc]
            except KeyError:
                pre = kind[pc] = self.classify(pc)
            post = pre(self) if pre else None
            if step(handle, 1) != 1:
                buf = ctypes.create_string_buffer(512)
                size = lib.sharc_native_halt_reason(handle, buf, 512)
                why = buf.raw[:max(size, 0)].decode("utf-8", "replace") or "the native engine stopped"
                return ("halt", types.SimpleNamespace(pc_sw=get_pc(handle), reason=why), n)
            if post:
                post()
        return ("max", get_pc(handle), max_steps)


class _Regs:
    """The engine's registers as the mapping `forms_move._lw_store_pair` reads."""

    def __init__(self, engine):
        self.engine = engine

    def __getitem__(self, code):
        return self.engine.core.get_reg(code)

    def get(self, code, default=None):
        return self[code]
