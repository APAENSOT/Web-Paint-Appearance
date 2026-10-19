"""FVL leftover catalogues are 32 unique Panel cells, not Ranger codes."""

from app.domain.fvl_leftover_identity import (
    CX743_PANELS,
    V363_PANELS,
    leftover_checkzones,
    leftover_panel_group,
    leftover_tolerance,
)


def test_leftover_catalogues_are_32_unique_panels():
    for panels in (CX743_PANELS, V363_PANELS):
        assert len(panels) == 32
        assert {pos for pos, _raw in panels} == set(range(1, 33))
        assert len({raw for _pos, raw in panels}) == 32
        for _pos, raw in panels:
            leftover_panel_group(raw)
            leftover_tolerance(raw)


def test_leftover_checkzones_keep_panel_text_as_zone_code():
    codes = {row[0] for row in leftover_checkzones()}
    assert "1HOOD" in codes
    assert "17LIFGATE" in codes
    assert "17SWINGGAT" in codes
    assert "RRHOOD" not in codes
    assert "LFFENDER" not in codes
