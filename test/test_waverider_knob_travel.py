"""Waverider's short lists turn as stock's own short lists do (docs/waverider-knob-travel.md)."""

from dnfw.mods import waverider
from dnfw.waverider import pages


def test_every_short_list_is_a_named_list_or_prst():
    assert set(pages.SHORT_LISTS) == set(pages.VALUE_NAMES) | {249}
    assert pages.TBL_IDS[0] not in pages.SHORT_LISTS        # the pool's 130 tables keep their travel


def test_the_encoder_handler_asks_waverider_for_the_descriptor():
    site = [e for e in waverider.SPEC["edits"] if e["va"] == pages.KNOB_DESC_SITE]
    assert len(site) == 1
    assert site[0]["stock"] == "4eb9" + f"{pages.KNOB_DESC:08x}"
    assert site[0]["new"] == "4eb9" + f"{waverider.SPEC['layout']['wr_knob_desc']:08x}"
