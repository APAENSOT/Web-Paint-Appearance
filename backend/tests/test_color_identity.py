"""Unique colour identity fold (not D2, not Levenshtein)."""

from app.domain.color_identity import unique_colour_identity

CATALOGUE = [
    "Acacia Green",
    "Agate Black",
    "Aluminum Metallic",
    "Arctic White",
    "Blue Lightning",
    "Carbonized Grey",
    "Chill Grey",
    "Code Orange",
    "Command Grey",
    "Cyclone Terra Green",
    "Desert Island Blue",
    "Diffused Silver",
    "Frozen White",
    "Iconic Silver",
    "Ignite Orange",
    "Lucid Red",
    "Meteor Grey",
    "Pearl White",
    "Seismic Tan",
    "Shadow Black",
    "Traction Green",
    "Vapor Blue",
]


def test_sap_august_spellings_fold_uniquely():
    expected = {
        "Frozen White 7VTAWWA": "Frozen White",
        "M7_Carbonized_Gray": "Carbonized Grey",
        "UM_Agate_Black_Met": "Agate Black",
        "Cyclone terra green 4GREWHA": "Cyclone Terra Green",
        "IGNITE ORANGE 3C": "Ignite Orange",
        "command grey 5ZTAWHA": "Command Grey",
        "ACACIA GREEN 5GREWHA": "Acacia Green",
        "JS_Iconic_Silver": "Iconic Silver",
        "D4 Lucid Red TC": "Lucid Red",
        "chill grey solid 5ZQAWHA-1": "Chill Grey",
        "diffused silver JTQEWHA": "Diffused Silver",
    }
    for raw, name in expected.items():
        assert unique_colour_identity(raw, CATALOGUE) == name, raw


def test_fvl_prefixes_fold_when_the_catalogue_already_has_the_name():
    assert unique_colour_identity("FW - Frozen White", CATALOGUE) == "Frozen White"
    assert unique_colour_identity("IS - Iconic Silver", CATALOGUE) == "Iconic Silver"
    assert unique_colour_identity("VB - Vapor Blue", CATALOGUE) == "Vapor Blue"
    assert unique_colour_identity("IO - Ignite Orange", CATALOGUE) == "Ignite Orange"
    assert unique_colour_identity("DS - Difused Silver", CATALOGUE) == "Diffused Silver"


def test_unknown_or_ambiguous_spellings_stay_held():
    assert unique_colour_identity("AB - Absolute Black", CATALOGUE) is None
    assert unique_colour_identity("PR - Pace Red", CATALOGUE) is None
    assert unique_colour_identity("MG - Magnetic", CATALOGUE) is None
    assert unique_colour_identity("Not A Colour", CATALOGUE) is None
    assert unique_colour_identity("Green", CATALOGUE) is None
    assert unique_colour_identity("3HC Traction abcdef12", CATALOGUE) is None


def test_a_new_catalogue_name_is_enough_for_the_file_spelling():
    extra = CATALOGUE + ["Absolute Black", "Pace Red", "Magnetic"]
    assert unique_colour_identity("AB - Absolute Black", extra) == "Absolute Black"
    assert unique_colour_identity("PR - Pace Red", extra) == "Pace Red"
    assert unique_colour_identity("MG - Magnetic", extra) == "Magnetic"
