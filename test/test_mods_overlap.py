"""dnfw.mods.overlap: our declared extents against a patchkit plan."""

from dnfw.mods import RAM, Extent, overlap

BASE = 0x40000400
PORT = {"region": [{"name": "cf.expansion", "cpu": "cf", "start": 0x46712000, "end": 0x47fe0000}]}


def plan(**over):
    p = {"modules": ["core/x@0.1.0"],
         "writes": [{"cpu": "cf", "addr": BASE + 0x100, "len": 4, "kind": "patch", "owner": "core/x@0.1.0", "what": "bound"}],
         "hooks": [{"module": "core/x@0.1.0", "anchor": "x.site", "cpu": "cf", "addr": BASE + 0x200, "site_len": 6}],
         "regions": {"cf.expansion": [0x1000, 0x100000]}}
    p.update(over)
    return p


def kinds(named, p=None):
    return [k for k, _ in overlap.collisions(overlap.ours(named, BASE), overlap.theirs(p or plan(), PORT))]


def test_disjoint_ranges_share_an_image():
    assert kinds([("m", [Extent(3, 0x300, 8), Extent(RAM, 0x46720000, 16)])]) == []


def test_the_same_bytes_a_hook_site_and_a_region_are_each_found():
    named = [("m", [Extent(3, 0x102, 2), Extent(3, 0x204, 4), Extent(RAM, 0x46712800, 16)])]
    assert sorted(kinds(named)) == sorted([overlap.SAME, overlap.HOOK, overlap.RAM_IN_REGION])


def test_a_range_that_only_touches_does_not_collide():
    assert kinds([("m", [Extent(3, 0x104, 4), Extent(RAM, 0x46713000, 4)])]) == []


def test_a_rebuilt_stream_collides_with_any_dsp_write_and_only_then():
    named = [("m", [Extent(7, 0, 836_956)])]
    dsp = {"cpu": "sharc", "addr": 0x20004a36, "len": 6, "kind": "patch", "owner": "core/y@0.1.0", "what": "hook"}
    assert kinds(named) == []
    assert kinds(named, plan(writes=[dsp])) == [overlap.STREAM]
