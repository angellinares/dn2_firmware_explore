"""dnfw.sharccycles: each rule on a step stream built by hand."""

import numpy as np

from dnfw.sharccycles import btb, cache, computefield as cf, costs, fit, forms, model, regions
from dnfw.sharccycles.events import DAG, IMM, LOAD, MOVE, Step


def S(**kw):
    base = dict(form="2a", length_sw=3, computes=(), dag_uses=())
    base.update(kw)
    return forms.Static(**base)


NOP = S()


def run(steps):
    return model.count(steps)


# -- regions ---------------------------------------------------------------------------

def test_regions_datasheet_tables():
    assert regions.data_region(0x2DE6C0) == "l1b1"          # Waverider's gain word
    assert regions.data_region(0x25C48C) == "l1b0"          # the frame copy
    assert regions.data_region(0x000B0004) == "l1b1"        # block 1, normal word
    assert regions.data_region(0x20080000) == "l2"
    assert regions.data_region(0x80001000) == "ddr"
    assert regions.data_region(0x282C0000) == "l1sys"
    assert regions.data_region(0x2FFF00) == "l1b1"          # the stack, in block 1's window
    assert regions.data_region(0x31002000) == "smmr"        # SPORT0
    assert regions.code_region(0x16EB00) == "l1b1"          # the reader
    assert regions.code_region(0x1C2712) == "l1b3"          # frame unpack
    assert regions.code_region(0xB88ABB) == "l2"            # the idle loop


# -- compute fields -------------------------------------------------------------------

def test_compute_decode_units_and_registers():
    # F4 = F0 * F4: multiplier, float (0x30), Rn 4, Rx 0, Ry 4
    c = cf.decode((1 << 20) | (0x30 << 12) | (4 << 8) | (0 << 4) | 4)
    assert (c.unit, c.float_op, c.dests, c.srcs) == ("mul", True, (4,), (0, 4))
    # R0 = R1 + R2: ALU fixed
    c = cf.decode((0x01 << 12) | (0 << 8) | (1 << 4) | 2)
    assert (c.unit, c.float_op, c.dests, c.srcs) == ("alu", False, (0,), (1, 2))
    # COMP(R1, R2) writes nothing
    assert cf.decode((0x0A << 12) | (1 << 4) | 2).dests == ()
    # F1 = FLOAT R11 BY R15 (0xDA): float path, two sources
    c = cf.decode((0xDA << 12) | (1 << 8) | (11 << 4) | 15)
    assert c.float_op and c.dests == (1,) and c.srcs == (11, 15)
    # F0 = PASS F3 (0xA1): single operand
    assert cf.decode((0xA1 << 12) | (3 << 4)).single_operand
    # R4 = LSHIFT R4 BY R2: shifter, fixed
    c = cf.decode((2 << 20) | (4 << 8) | (4 << 4) | 2)
    assert (c.unit, c.float_op, c.dests) == ("shift", False, (4,))
    assert cf.decode(0) is None


# -- forms ----------------------------------------------------------------------------

def test_forms_dag_and_branch_fields():
    s = forms.classify("4a", 6, {"i[2:0]": 1, "g": 0, "d": 0, "u": 0, "cond[4:0]": 31,
                                 "data[5:5]": 0, "data[4:0]": 0, "dreg[3:0]": 4,
                                 "compute[22:16]": 0, "compute[15:0]": 0})
    assert s.dag_uses == (1,) and not s.pm_data and s.computes == ()
    s = forms.classify("1a", 6, {"dmd": 0, "dmi[2:0]": 2, "dmm[2:0]": 6, "pmd": 0, "dmdreg[3:0]": 0,
                                 "pmi[2:2]": 1, "pmi[1:0]": 0, "pmm[2:0]": 0, "pmdreg[3:0]": 0,
                                 "compute[22:16]": 0, "compute[15:0]": 0})
    assert s.dag_uses == (2, 12) and s.pm_data
    s = forms.classify("8a_rel", 6, {"b": 0, "a": 0, "cond[4:0]": 0, "j": 1, "ci": 0,
                                     "reladdr[23:16]": 0, "reladdr[15:0]": 4})
    assert s.branch == forms.JUMP and s.conditional and s.delayed
    s = forms.classify("5b_move", 4, {"srcureghigh[4:0]": 0, "cond[4:0]": 31, "srcureglow[1:1]": 0,
                                      "srcureglow[0:0]": 1, "dstureg[6:0]": 0x10})
    assert s.ireg_move


# -- cache and BTB --------------------------------------------------------------------

def test_cache_lru_two_way():
    c = cache.Cache(size=256, line=64, ways=2)          # 2 sets
    for a in (0, 128, 0, 256, 128):                     # 0, 128, 256 share set 0
        c.access(a)
    assert (c.hits, c.misses) == (1, 4)                 # 0 hits once; 256 evicts 128


def test_btb_learns_a_loop_branch():
    b = btb.BTB()
    seq = [b.outcome(0x100, True, True) for _ in range(3)]
    assert seq == ["br_wrong_taken", "br_taken_ok", "br_taken_ok"]
    assert b.outcome(0x100, True, False) == "br_wrong_nottaken"
    assert b.outcome(0x200, True, False) is None
    assert b.outcome(0x300, False, True) == "br_uncond_miss"
    assert b.outcome(0x300, False, True) == "br_uncond_hit"
    assert b.outcome(0x300, False, True, masked=True) == "br_uncond_miss"


# -- the rules ------------------------------------------------------------------------

def test_dag_load_to_use_by_distance():
    load = Step(0, S(form="3a", dag_uses=(6,)), reads=(0x2C0000,), ireg_writes=((0, LOAD),))
    use = Step(3, S(form="4a", dag_uses=(0,)), reads=(0x2C0100,))
    assert run([load, use])["dag_load_use"] == 4
    assert run([load, Step(1, NOP), use])["dag_load_use"] == 3
    assert run([load] + [Step(1, NOP)] * 4 + [use])["dag_load_use"] == 0
    move = Step(0, S(form="5b_move", ireg_move=True), ireg_writes=((0, MOVE),))
    c = run([move, Step(1, NOP), use])
    assert c["dag_move_use"] == 3 and c["dag_load_use"] == 0
    imm = Step(0, S(form="17a", ireg_imm=True), ireg_writes=((0, IMM),))
    post = Step(0, S(form="4a", dag_uses=(0,)), ireg_writes=((0, DAG),))
    assert run([imm, use])["dag_move_use"] == 0 and run([post, use])["dag_load_use"] == 0


def test_cjump_then_i6_but_not_i7():
    cj = Step(0, S(form="25a_direct", branch=forms.CJUMP, delayed=True))
    i7 = Step(3, S(form="4a", dag_uses=(7,)), writes=(0x2FFF00,))
    i6 = Step(3, S(form="4a", dag_uses=(6,)), reads=(0x2FFF00,))
    assert run([cj, i7, i7])["cjump_i6_use"] == 0
    assert run([cj, i7, i6])["cjump_i6_use"] == 5


def test_float_forwarding_and_anomaly_72():
    fmul = cf.Compute("mul", True, (4,), (0, 4))
    uses4 = cf.Compute("alu", True, (6,), (6, 4))
    other = cf.Compute("alu", True, (6,), (6, 5))
    assert run([Step(0, S(computes=(fmul,))), Step(3, S(computes=(uses4,)))])["fwd_float"] == 1
    assert run([Step(0, S(computes=(fmul,))), Step(3, S(computes=(other,)))])["fwd_float"] == 0
    to_f0 = cf.Compute("alu", True, (0,), (11, 15))
    single = cf.Compute("alu", False, (0,), (1,), True)
    assert run([Step(0, S(computes=(to_f0,))), Step(3, S(computes=(single,)))])["anomaly_20000072"] == 1


def test_branches_loops_and_memory():
    jmp = S(form="8a_rel", branch=forms.JUMP, conditional=True, delayed=False)
    c = run([Step(0x10, jmp, taken=True), Step(0x10, jmp, taken=True)])
    assert c["br_wrong_taken"] == 1 and c["br_taken_ok"] == 1
    c = run([Step(0x10, jmp, taken=True, in_loop=True)] * 2)
    assert c["br_wrong_taken"] == 2                       # masked in a hardware loop
    assert run([Step(0, NOP, loop_exit=True)])["loop_exit"] == 1
    c = run([Step(0, NOP, reads=(0x2C0000, 0x2C0004)), Step(3, NOP, reads=(0x240000, 0x2C0000))])
    assert c["l1_same_block"] == 1
    c = run([Step(0, NOP, reads=(0x80000000,)), Step(3, NOP, reads=(0x80000020,)),
             Step(6, NOP, writes=(0x31002000,))])
    assert (c["ddr_miss_rd"], c["ddr_hit_rd"], c["smmr_wr"]) == (1, 1, 1)
    c = run([Step(0xB88ABB, NOP)] * 2)
    assert c["icache_miss_l2"] == 1


def test_estimate_prices_counts():
    total, parts, unpriced = costs.estimate({"instructions": 100, "br_wrong_taken": 2, "x": 1},
                                            costs.DEFAULTS)
    assert total == 100 + 22 and parts["br_wrong_taken"] == 22 and unpriced == ["x"]


# -- the fit --------------------------------------------------------------------------

def test_nnls_matches_a_known_solution():
    a = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    x = fit.nnls(a, np.array([2.0, -1.0, 1.0]))
    assert x[1] == 0 and abs(x[0] - 1.5) < 1e-9


def test_fit_recovers_a_memory_latency():
    table = dict(costs.DEFAULTS)
    true_ddr = 140.0
    pairs = []
    for n_miss, n_instr in ((100, 2000), (300, 5000), (50, 900)):
        counts = {"instructions": n_instr, "ddr_miss_rd": n_miss}
        pairs.append(fit.Pair(f"case{n_miss}", counts, n_instr + n_miss * true_ddr, sigma=10))
    new, before, after = fit.fit(pairs, table, ["ddr_miss_rd"], lam=1e-6)
    assert abs(new["ddr_miss_rd"] - true_ddr) < 0.5
    assert max(map(abs, after)) < max(map(abs, before))
