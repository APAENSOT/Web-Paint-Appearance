"""Leftover programs are not P703 spellings (G1 D-07 / H7)."""

from app.domain.leftover_models import (
    is_leftover_program,
    leftover_maps_to_own_program,
)


def test_leftover_programs_are_not_p703():
    for raw in ("CX743", "cx743", "V363", "J73 DBL", "U704", "j73"):
        assert is_leftover_program(raw)
    for raw in ("P703", "P703 DBL", "P703 RAP", "P703 DBL RANGER", ""):
        assert not is_leftover_program(raw)


def test_leftover_maps_to_own_catalogue_only():
    assert leftover_maps_to_own_program("CX743", "CX743")
    assert leftover_maps_to_own_program("cx743", "CX743")
    assert leftover_maps_to_own_program("V363", "V363")
    assert leftover_maps_to_own_program("J73 DBL", "J73 DBL")
    assert leftover_maps_to_own_program("U704", "U704")
    assert not leftover_maps_to_own_program("CX743", "P703 DBL RANGER")
    assert not leftover_maps_to_own_program("V363", "CX743")
    assert not leftover_maps_to_own_program("P703", "P703 DBL RANGER")
