"""T97 -- a name that names exactly one canonical panel loads.

The complement T94 left open, measured on the owner's live trial: on
``P703 DBL RANGER`` at FTM, ``12LCPILLAR`` is **specific** under D-94-1
because its name names exactly one canonical panel (``LCPILLAR``) -- and
then the resolver still held it, asking for an alias row that is not
there. Two parts of the system read the same name and disagreed about
whether it says anything.

**D-97-1** closes that: a label whose name, leading number dropped, names
exactly one canonical panel of that ``(plant, model)`` resolves to it, with
no alias and no question. **D-97-2** guards it exactly as D-96-2 guards
D-96-1 -- only against the model's **own** canonical list, so a pair with
no canonical list resolves nothing new. **D-97-3** runs it **last**, after
T58's gold label -> global alias -> ``ref_plant_zone_map`` order, so an
approved alias, a taught zone map row and a batch confirmation all still
win.

Pure, no database and no application. No row is written or deleted (D-97-7).
"""

from __future__ import annotations

from app.domain.cleaner import CleanRow, Cleaner
from app.domain.reader import read_sheet
from app.domain.references import ReferenceData
from app.domain.ws_plant_gold import gold_key
from tests.test_t26_semantic_clean_layer import ALIAS_MAP, HEADERS, sheet_bytes
from tests.test_t90_panel_walk import CANONICAL_NAMES

PLANT = "FTM"
MODEL = "P703 DBL RANGER"

#: The T58 numbered block, still live beside the canonical 32 (D-97-7: the
#: catalogue is not touched). This is what made ``01HOOD`` read "Ready to
#: add" before T94, and it must stay unreachable by a rough label.
NUMBERED_BLOCK = tuple(f"{index:02d}HOOD" for index in range(1, 6))


def reference(
    *,
    canonical: bool = True,
    numbered_is_canonical: bool = False,
    zone_map: dict | None = None,
) -> ReferenceData:
    """FTM's canonical 32 plus the live numbered block, no alias rows.

    ``plant_gold`` is keyed on ``gold_key`` exactly as the loader builds it
    from ``ref_plant_ws_point``; ``model_zone`` is the model's own
    catalogue, and the intersection of the two is what
    `Cleaner.canonical_panels` calls canonical (D-97-2).
    """
    gold = {gold_key(name): name for name in CANONICAL_NAMES + NUMBERED_BLOCK}
    catalogue = CANONICAL_NAMES + (NUMBERED_BLOCK if numbered_is_canonical else ())
    return ReferenceData(
        plant={"ftm": PLANT},
        model={"p703 dbl ranger": MODEL},
        model_zone=(
            frozenset({(MODEL, name) for name in catalogue})
            if canonical
            else frozenset()
        ),
        plant_gold={(PLANT, MODEL): gold},
        plant_zone_map=zone_map or {},
        color={"3hc traction green": "Traction Green"},
        paintline={"booth1": "BOOTH1"},
        requires_serial={PLANT: True},
        known_plants=frozenset({PLANT}),
        active_plants=frozenset({PLANT}),
        offered_models={(PLANT, MODEL): True},
        offered_colors={(PLANT, "Traction Green"): True},
        expected_zones={MODEL: 32},
    )


def cleaner(ref: ReferenceData | None = None) -> Cleaner:
    return Cleaner(ref or reference(), (PLANT,), expected_plant=PLANT)


def sheet(*labels: str):
    """Real WaveScan rows, one per label, so `clean_all` classifies them."""
    rows = [
        {"Plant": PLANT, "Model": MODEL, "Checkzone": label, "Serial No": "T97-1"}
        for label in labels
    ]
    return list(
        read_sheet(sheet_bytes(HEADERS, rows), "PasteData", ALIAS_MAP, "t97.xlsx")
    )


# =====================================================================
# D-97-1 -- exactly one is specific, and now it loads
# =====================================================================
def test_the_pillar_resolves_to_its_one_canonical_panel_with_no_alias_row():
    """The owner's row, with `ref_plant_zone_map` empty (D-97-1)."""
    assert cleaner().resolve_checkzone(PLANT, MODEL, "12LCPILLAR") == "LCPILLAR"
    assert cleaner().resolve_checkzone(PLANT, MODEL, "15RCPILLAR") == "RCPILLAR"


def test_the_file_spelling_is_kept_beside_the_stored_position():
    """D-97-4: ``checkzone`` is the long name, ``src_zone_text`` the file's."""
    [row] = cleaner().clean_all(sheet("12LCPILLAR")).clean
    assert isinstance(row, CleanRow)
    assert row.checkzone == "LCPILLAR"
    assert row.src_zone_text == "12LCPILLAR"
    assert row.src_zone_no == 12


def test_a_label_that_names_nothing_still_holds():
    """D-97-1 is "exactly one", not "anything with a number on it".

    ``13LFRDOOR`` names no canonical panel at FTM (that is the T96 shape),
    so it is still held for the uploader -- nothing is minted.
    """
    assert cleaner().resolve_checkzone(PLANT, MODEL, "13LFRDOOR") is None


# =====================================================================
# The guard: D-97-1 did not eat T94
# =====================================================================
def test_01hood_is_unchanged_still_rough_and_still_asks():
    """D-94-1 (a) / D-94-2, with a **live** panel spelled ``01HOOD``.

    Five canonical hoods, so the name names none of them: rough, and a rough
    label is never resolved by the catalogue, whatever the catalogue holds.
    D-97-1 cannot reach it -- `resolve_checkzone` answers a rough label from
    the batch's confirmations alone.
    """
    clean = cleaner()
    result = clean.clean_all(sheet("01HOOD", "12LCPILLAR"))
    assert "01hood" in clean.rough_panels[MODEL]
    assert "12lcpillar" not in clean.rough_panels[MODEL]
    assert clean.resolve_checkzone(PLANT, MODEL, "01HOOD") is None
    assert [row.checkzone for row in result.clean] == ["LCPILLAR"]
    assert [reject.column for reject in result.rejects] == ["checkzone"]
    assert [reject.value for reject in result.rejects] == ["01HOOD"]


def test_a_batch_confirmation_still_wins_over_the_name():
    """D-97-3, on the only label both rules can reach.

    ``06LFFENDER`` names exactly one canonical panel (``LFFENDER``), so
    D-97-1 would resolve it -- but with ``07`` and ``08LFFENDER`` on the
    sheet all three are rough under D-94-1 (b), and a rough label takes only
    the answer a person confirmed for this upload. The confirmation wins and
    the name is not consulted.
    """
    clean = Cleaner(
        reference(),
        (PLANT,),
        expected_plant=PLANT,
        confirmed_panels={(MODEL, "06LFFENDER"): "LCFENDER"},
    )
    clean.clean_all(sheet("06LFFENDER", "07LFFENDER", "08LFFENDER"))
    assert clean.resolve_checkzone(PLANT, MODEL, "06LFFENDER") == "LCFENDER"
    assert clean.resolve_checkzone(PLANT, MODEL, "07LFFENDER") is None
    # Alone on a sheet the same label is specific, and then the name answers
    # it -- which is D-97-1, not the confirmation.
    assert cleaner().resolve_checkzone(PLANT, MODEL, "06LFFENDER") == "LFFENDER"


def test_a_taught_zone_map_row_still_wins_over_the_name():
    """D-97-3: ``ref_plant_zone_map`` is read before D-97-1, as T58 locks."""
    taught = reference(zone_map={(PLANT, MODEL, "12lcpillar"): "RCPILLAR"})
    assert cleaner(taught).resolve_checkzone(PLANT, MODEL, "12LCPILLAR") == "RCPILLAR"


def test_a_pair_with_no_canonical_list_resolves_nothing_new():
    """D-97-2: no ``ref_model_zone`` rows, so nothing is claimed.

    FVL / ``P703 DBL RANGER``, SAP / ``J73 DBL`` and SAP /
    ``P703 DBL RANGER`` are this case (T89 Part 1), and they are unchanged.
    """
    bare = cleaner(reference(canonical=False))
    assert bare.canonical_panels(PLANT, MODEL) == frozenset()
    assert bare.resolve_checkzone(PLANT, MODEL, "12LCPILLAR") is None


def test_a_canonical_numbered_name_still_resolves_by_the_gold_list():
    """FVL ``CX743`` / ``V363`` are unchanged (T58 rule 1).

    Their 32 canonical names all lead with a digit, so the label **is** the
    gold label and resolution ends at rule 1 -- D-97-1 is never reached, and
    the stored ``checkzone`` is still the plant's own spelling.
    """
    fvl_like = reference(numbered_is_canonical=True)
    clean = cleaner(fvl_like)
    clean.clean_all(sheet("01HOOD", "02HOOD"))
    assert clean.rough_panels == {}
    assert clean.resolve_checkzone(PLANT, MODEL, "01HOOD") == "01HOOD"
    assert clean.resolve_checkzone(PLANT, MODEL, "1HOOD") == "01HOOD"
