from app.domain.held_label_copy import (
    display_group_for,
    is_empty_identity_sentinel,
    operator_message_for,
)


def test_empty_sentinels_only():
    for raw in (None, "", "  ", "None", "none", "(None)", "(none)", "null", "NULL"):
        assert is_empty_identity_sentinel(raw)
    for raw in ("01HOOD", "P703 DBL", "Arctic White", "U704", "FW - Frozen White"):
        assert not is_empty_identity_sentinel(raw)


def test_empty_beats_model_reason():
    assert display_group_for("UNKNOWN_MODEL", "(None)") == "empty_identity"
    assert "will not load" in operator_message_for("empty_identity", "(None)").lower()


def test_real_spellings_keep_their_group():
    assert display_group_for("UNKNOWN_COLOR", "3HC Traction abc") == "colour"
    assert display_group_for("UNKNOWN_MODEL", "P703 DBL") == "model"
    assert display_group_for("UNKNOWN_CHECKZONE", "01HOOD") == "zone"
    assert display_group_for("BAD_DATE", "") == "date"
    assert display_group_for("UNREVIEWED_HEADER", "style") == "header"


def test_not_offered_is_plant_offer_group():
    assert display_group_for("COLOR_NOT_OFFERED", "Ignite Orange") == "plant_offer"
    assert display_group_for("MODEL_NOT_OFFERED", "P703 DBL RANGER") == "plant_offer"
    assert "not on this plant's list" in operator_message_for(
        "plant_offer", "Ignite Orange"
    ).lower()


def test_empty_still_beats_not_offered_reason():
    assert display_group_for("COLOR_NOT_OFFERED", "(None)") == "empty_identity"
