"""T91 -- the two gaps, and the template that carries its own safety.

Three claims, and the first is the one the task turns on:

* **D-91-2.** A spelling this plant has already confirmed as a *different*
  panel can never be a permanent alias again, **whatever this sheet's own
  specificity test says**. `13LFRDOOR` is `LCPILLAR` in August and
  `LCRDOOR` in September; both files are believed about themselves
  (D-91-1), and that is precisely why the name alone identifies nothing at
  FTM any more. D-90-3 could not see this, because rough-or-specific is a
  property of ONE SHEET and identity is a property of the PLANT. The same
  spelling confirmed to the *same* panel twice is not refused;
* **D-91-3.** The template carries its binding in a data field. A row that
  declares none, declares an unknown one, or declares `alias` in the
  per-batch half refuses the whole file by line number. A `batch` row never
  reaches `ref_plant_zone_map`;
* **D-91-4.** D-89-4's order still holds: retirement before aliasing is
  still refused.

Every batch, proposal and map row is this module's own and is removed
again. The owner's trial batches are never touched, no standard is ever
published, and nothing here applies the real template.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.domain.panel_walk import (
    BINDING_ALIAS,
    BINDING_BATCH,
    SPECIFICITY_ROUGH,
    SPECIFICITY_SPECIFIC,
)
from tests.test_t04_ingest import cleanup, wait_for  # noqa: F401
from tests.test_t39_uploader_worksheet import (  # noqa: F401
    HEADERS,
    admin,
    book,
    engineer,
    ingest_apps,
    sent,
)
from tests.test_t89_one_picker import (  # noqa: F401
    _zone_set,
    held_sheet,
)
from tests.test_t90_walk_memory import (  # noqa: F401
    MARKER,
    MODEL,
    PANEL_MATCH,
    PLANT,
    PROPOSALS,
    sheet_bytes,
    walk_labels,
    walk_of,
)

from tests.test_t04_ingest import forget_proposals
from tests.conftest import SUITE_STARTED, row_keys

pytestmark = pytest.mark.ingest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


# =====================================================================
# D-91-3 -- the template says how far each pair may travel, in the data
# =====================================================================
def _template(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _apply_script():
    import importlib.util
    import sys

    scripts = BACKEND_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "t91_apply_canonical", scripts / "t91_apply_canonical.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed: a frozen dataclass resolves its own
    # module while the class body runs, and a module that is not in
    # sys.modules yet cannot be found.
    sys.modules.setdefault("t91_apply_canonical", module)
    spec.loader.exec_module(module)
    return module


def test_a_template_row_that_declares_no_binding_refuses_the_whole_file(tmp_path):
    script = _apply_script()
    path = _template(
        tmp_path,
        "no-binding.csv",
        "model_code,source_checkzone,canonical_zone_code,binding\n"
        "P703 DBL RANGER,06LFFFEND,LFFENDER,alias\n"
        "P703 DBL RANGER,16LFBOXS,LRBOX\n",
    )
    with pytest.raises(script.TemplateRefused) as refused:
        script.read_template(path, expect=BINDING_ALIAS, has_convention=False)
    assert "line 3" in str(refused.value)
    assert "16LFBOXS" in str(refused.value)


def test_an_unknown_binding_is_refused_rather_than_guessed_at(tmp_path):
    script = _apply_script()
    path = _template(
        tmp_path,
        "odd-binding.csv",
        "model_code,source_checkzone,canonical_zone_code,binding\n"
        "P703 DBL RANGER,06LFFFEND,LFFENDER,probably\n",
    )
    with pytest.raises(script.TemplateRefused) as refused:
        script.read_template(path, expect=BINDING_ALIAS, has_convention=False)
    assert "'probably'" in str(refused.value)


def test_a_batch_row_in_the_permanent_half_refuses_the_file(tmp_path):
    """The two halves are not interchangeable (D-90-11)."""
    script = _apply_script()
    path = _template(
        tmp_path,
        "mixed.csv",
        "model_code,source_checkzone,canonical_zone_code,binding\n"
        "P703 DBL RANGER,01HOOD,RRHOOD,batch\n",
    )
    with pytest.raises(script.TemplateRefused) as refused:
        script.read_template(path, expect=BINDING_ALIAS, has_convention=False)
    assert "ref_plant_zone_map" in str(refused.value)


def test_one_spelling_offered_as_two_permanent_aliases_is_refused(tmp_path):
    script = _apply_script()
    path = _template(
        tmp_path,
        "two-targets.csv",
        "model_code,source_checkzone,canonical_zone_code,binding\n"
        "P703 DBL RANGER,13LFRDOOR,LCPILLAR,alias\n"
        "P703 DBL RANGER,13LFRDOOR,LCRDOOR,alias\n",
    )
    pairs = script.read_template(path, expect=BINDING_ALIAS, has_convention=False)
    with pytest.raises(script.TemplateRefused) as refused:
        script.refuse_two_targets(pairs)
    assert "LCPILLAR" in str(refused.value)
    assert "LCRDOOR" in str(refused.value)
    assert "D-91-2" in str(refused.value)


def test_a_batch_row_never_reaches_matches(tmp_path):
    """The whole of D-91-3's point: only `alias` rows can be learned."""
    script = _apply_script()
    aliases = script.read_template(
        _template(
            tmp_path,
            "aliases.csv",
            "model_code,source_checkzone,canonical_zone_code,binding\n"
            "P703 DBL RANGER,12LCPILLAR,LCPILLAR,alias\n",
        ),
        expect=BINDING_ALIAS,
        has_convention=False,
    )
    per_batch = script.read_template(
        _template(
            tmp_path,
            "walk.csv",
            "model_code,convention,source_checkzone,canonical_zone_code,binding\n"
            "P703 DBL RANGER,september,01HOOD,RRHOOD,batch\n",
        ),
        expect=BINDING_BATCH,
        has_convention=True,
    )
    body = script.build_set(
        plant=PLANT,
        model=MODEL,
        convention="september",
        load_id=1,
        walk_rows=[
            {
                "raw_zone_text": "12lcpillar",
                "specificity": SPECIFICITY_SPECIFIC,
                "rule": "group_ordinal",
                "attention": "red",
                "binding": BINDING_ALIAS,
                "binding_reason": None,
            },
            {
                "raw_zone_text": "01hood",
                "specificity": SPECIFICITY_ROUGH,
                "rule": "group_ordinal",
                "attention": "red",
                "binding": BINDING_BATCH,
                "binding_reason": "rough",
            },
        ],
        aliases=aliases,
        batch_pairs=per_batch,
        fingerprint="HOOD|PILLAR",
        confirmed_by="T91 test owner",
    )
    assert [row["raw_zone_text"] for row in body["payload"]["matches"]] == [
        "12LCPILLAR"
    ]
    assert {pair["raw_zone_text"] for pair in body["payload"]["walk"]["pairs"]} == {
        "12lcpillar",
        "01hood",
    }


def test_an_alias_row_the_screen_calls_per_batch_is_refused_by_name(tmp_path):
    """The template's claim is checked against the sheet it describes."""
    script = _apply_script()
    aliases = script.read_template(
        _template(
            tmp_path,
            "aliases.csv",
            "model_code,source_checkzone,canonical_zone_code,binding\n"
            "P703 DBL RANGER,13LFRDOOR,LCRDOOR,alias\n",
        ),
        expect=BINDING_ALIAS,
        has_convention=False,
    )
    with pytest.raises(script.TemplateRefused) as refused:
        script.build_set(
            plant=PLANT,
            model=MODEL,
            convention="september",
            load_id=1,
            walk_rows=[
                {
                    "raw_zone_text": "13lfrdoor",
                    "specificity": SPECIFICITY_SPECIFIC,
                    "rule": "group_ordinal",
                    "attention": "red",
                    "binding": BINDING_BATCH,
                    "binding_reason": "this plant has already confirmed it as LCPILLAR",
                }
            ],
            aliases=aliases,
            batch_pairs=[],
            fingerprint="DOOR",
            confirmed_by="T91 test owner",
        )
    assert "13LFRDOOR" in str(refused.value)
    assert "LCPILLAR" in str(refused.value)


# =====================================================================
# D-91-2 -- against the running application
# =====================================================================
def _confirm(walk: dict, load_id: int, note: str, *, matches, swap=()) -> dict:
    """A ZONE set: `matches` as given, `walk` from the screen's own reading.

    `swap` is a pair of spellings whose confirmed targets are exchanged in
    the walk block -- a person picking something other than the proposal,
    which is the only way one spelling comes to mean two panels at one
    plant in the first place.
    """
    rows = [row for row in walk["walk"]["rows"] if row["proposed_zone_code"]]
    targets = {row["raw_zone_text"]: row["proposed_zone_code"] for row in rows}
    if swap:
        left, right = swap
        targets[left], targets[right] = targets[right], targets[left]
    return {
        "kind": "ZONE",
        "load_id": load_id,
        "payload": {
            "plant_code": PLANT,
            "model_code": MODEL,
            "load_id": load_id,
            "matches": matches,
            "walk": {
                "fingerprint": walk["walk"]["fingerprint"],
                "pairs": [
                    {
                        "raw_zone_text": row["raw_zone_text"],
                        "zone_code": targets[row["raw_zone_text"]],
                        "specificity": row["specificity"],
                        "rule": row["rule"],
                        "attention": row["attention"],
                    }
                    for row in rows
                ],
            },
            "decided_by": "T91 test operator",
            "method": "T91 cross-sheet contradiction test",
            "note": f"T91 {note}",
        },
    }


def _forget(
    admin_conn, plant: str, model: str, labels: list[str], since=SUITE_STARTED
) -> None:
    """T95 D-95-1: keyed on all three of plant, model and spelling.

    The `note LIKE 'T91 %'` proposal delete moved to
    `_t92_proposal_cleanup` below: the product writes the same notes, so a
    note prefix is not a scope (D-95-2). It removed a genuine approved
    proposal from the owner's trial.

    **T98 (D-98-2).** Plant and model are not enough on their own: this
    module writes real spellings at a real plant and model, so a row the
    owner taught before the run matched the delete too (the
    `ref_plant_zone_map` row T97 lost). ``since`` floors the delete at the
    moment this suite started, so it reaches only rows this run inserted.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ref_plant_zone_map WHERE plant_code = %s"
            "   AND model_code = %s AND raw_zone_text = ANY(%s)"
            "   AND created_at >= %s",
            (plant, model, [label.lower() for label in labels], since),
        )


@pytest.fixture
def two_sheets(engineer, cleanup, admin_conn):  # noqa: F811
    """The same walk, uploaded twice: one plant, one model, two files.

    The two specific names of this walk are its pillars. The first file
    confirms them **crossed** -- each pillar's own spelling onto the other
    pillar -- which is a person's pick, not a rule's. That is the whole
    shape of August and September in miniature: after it, each of those two
    spellings has been confirmed as a panel that the second file's own
    reading will disagree with.
    """
    labels = walk_labels(admin_conn)
    pillars = [
        label for label, zone, _o in labels if "PILLAR" in zone.upper()
    ]
    if len(pillars) < 2:
        pytest.skip("this walk has fewer than two pillars, so nothing to cross")
    first_tag = uuid.uuid4().hex[:6]
    second_tag = uuid.uuid4().hex[:6]
    [first] = sent(
        engineer, cleanup, admin_conn, f"t91-first-{first_tag}.xlsx",
        sheet_bytes(labels, first_tag), PLANT,
    )
    [second] = sent(
        engineer, cleanup, admin_conn, f"t91-second-{second_tag}.xlsx",
        sheet_bytes(labels, second_tag), PLANT,
    )
    try:
        yield {
            "labels": labels,
            "pillars": pillars,
            "first": first,
            "second": second,
            "first_load": first["batch"]["load_id"],
            "second_load": second["batch"]["load_id"],
            "first_file": f"t91-first-{first_tag}.xlsx",
        }
    finally:
        _forget(admin_conn, PLANT, MODEL, [label for label, _z, _o in labels])


def _confirm_crossed(engineer, two_sheets) -> dict:  # noqa: F811
    """Record the crossed walk on the FIRST file. No permanent alias at all."""
    body = walk_of(engineer, two_sheets["first_load"])
    request = _confirm(
        body,
        two_sheets["first_load"],
        "crossed pillars on the first file",
        matches=[],
        swap=(two_sheets["pillars"][0], two_sheets["pillars"][1]),
    )
    created = engineer.post(PROPOSALS, json=request)
    assert created.status_code == 201, created.text
    return request["payload"]["walk"]


def test_a_spelling_this_plant_calls_another_panel_cannot_be_learned(
    engineer, two_sheets, admin_conn  # noqa: F811
):
    """D-91-2, the gap D-90-3 left open. Refused by name, nothing written."""
    crossed = _confirm_crossed(engineer, two_sheets)
    spelling = two_sheets["pillars"][0]
    confirmed_as = next(
        pair["zone_code"]
        for pair in crossed["pairs"]
        if pair["raw_zone_text"] == spelling
    )

    body = walk_of(engineer, two_sheets["second_load"])
    row = next(
        row
        for row in body["walk"]["rows"]
        if row["raw_zone_text"] == spelling
    )
    # This sheet's own reading, and it is SPECIFIC here -- so D-90-3 has
    # nothing to say and only D-91-2 can refuse it.
    assert row["specificity"] == SPECIFICITY_SPECIFIC
    assert row["proposed_zone_code"] != confirmed_as

    request = _confirm(
        body,
        two_sheets["second_load"],
        "offering a contradicted spelling forever",
        matches=[
            {
                "raw_zone_text": spelling,
                "zone_code": row["proposed_zone_code"],
            }
        ],
    )
    response = engineer.post(PROPOSALS, json=request)
    assert response.status_code == 422, response.text
    message = response.json()["message"]
    assert spelling.lower() in message.lower()
    assert confirmed_as in message
    assert two_sheets["first_file"] in message
    assert "identity is a property of the plant" in message
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ref_plant_zone_map WHERE raw_zone_text = %s",
            (spelling.lower(),),
        )
        assert cur.fetchone()[0] == 0


def test_the_same_spelling_confirmed_to_the_same_panel_twice_is_not_refused(
    engineer, two_sheets  # noqa: F811
):
    """The rule is about a CONTRADICTION, not about repetition."""
    crossed = _confirm_crossed(engineer, two_sheets)
    spelling = two_sheets["pillars"][0]
    confirmed_as = next(
        pair["zone_code"]
        for pair in crossed["pairs"]
        if pair["raw_zone_text"] == spelling
    )
    body = walk_of(engineer, two_sheets["second_load"])
    request = _confirm(
        body,
        two_sheets["second_load"],
        "the same answer twice",
        matches=[{"raw_zone_text": spelling, "zone_code": confirmed_as}],
        swap=(two_sheets["pillars"][0], two_sheets["pillars"][1]),
    )
    response = engineer.post(PROPOSALS, json=request)
    assert response.status_code == 201, response.text


def test_the_contradiction_is_recorded_on_the_zone_audit_row(
    engineer, admin, two_sheets, admin_conn  # noqa: F811
):
    """The per-batch half is deliberately not in the map, so it lives here."""
    _confirm_crossed(engineer, two_sheets)
    body = walk_of(engineer, two_sheets["second_load"])
    request = _confirm(
        body,
        two_sheets["second_load"],
        "audited contradiction",
        matches=[],
    )
    created = engineer.post(PROPOSALS, json=request)
    assert created.status_code == 201, created.text
    proposal_id = created.json()["id"]
    approved = admin.post(f"{PROPOSALS}/{proposal_id}/approve", json={})
    assert approved.status_code == 200, approved.text

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT after FROM audit_event"
            " WHERE action = 'mapping.approve' AND entity_id = %s",
            (proposal_id,),
        )
        after = cur.fetchone()[0]
    contradicted = after["walk_contradicted"]
    assert sorted(contradicted) == sorted(
        label.lower() for label in two_sheets["pillars"][:2]
    ), contradicted


def test_the_screen_says_per_batch_before_the_owner_presses_confirm(
    engineer, two_sheets  # noqa: F811
):
    """D-91-3's binding, in the read model, with the reason in plain words."""
    before = walk_of(engineer, two_sheets["second_load"])["walk"]
    pillar_rows = {
        row["raw_zone_text"]: row
        for row in before["rows"]
        if row["raw_zone_text"] in two_sheets["pillars"]
    }
    # Nothing confirmed yet, so a specific name may still be learned.
    for row in pillar_rows.values():
        assert row["binding"] == BINDING_ALIAS, row
        assert row["binding_reason"] is None
    rough = next(
        row for row in before["rows"]
        if row["specificity"] == SPECIFICITY_ROUGH
    )
    assert rough["binding"] == BINDING_BATCH
    assert "core is shared" in rough["binding_reason"]

    _confirm_crossed(engineer, two_sheets)

    after = walk_of(engineer, two_sheets["second_load"])["walk"]
    for spelling in two_sheets["pillars"][:2]:
        row = next(
            row for row in after["rows"] if row["raw_zone_text"] == spelling
        )
        assert row["specificity"] == SPECIFICITY_SPECIFIC
        assert row["binding"] == BINDING_BATCH, row
        assert two_sheets["first_file"] in row["binding_reason"]
        assert "D-91-2" in row["binding_reason"]


# =====================================================================
# D-91-4 -- the order is still a hard gate
# =====================================================================
def test_retirement_before_aliasing_is_still_refused(
    engineer, held_sheet, admin_conn  # noqa: F811
):
    """D-89-4's gate, re-asserted here because T91 is the task that retires.

    T89 built this claim; T91 adds a write-path refusal beside it and a
    `walk` block to the same payload, so the claim is re-run rather than
    assumed to have survived. The sheet has loaded rows onto `zone`, so
    that panel's own name is a name this file uses: retiring it while
    saying nothing about what the name means instead would stop it
    resolving on the next upload, and the set is refused whole.
    """
    mappable = [row[0] for row in held_sheet["live"] if row[3]]
    target = next(zone for zone in mappable if zone != held_sheet["zone"])
    response = engineer.post(
        PROPOSALS,
        json=_zone_set(
            held_sheet["load_id"],
            [{"raw_zone_text": held_sheet["panel"], "zone_code": target}],
            [held_sheet["zone"]],
        ),
    )
    assert response.status_code == 422, response.text
    assert "nothing here says the meaning of" in response.text  # T92 reworded; the claim is unchanged
    assert "D-89-4" in response.text
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT retired_at FROM ref_plant_ws_point WHERE plant_code = %s"
            "   AND model_code = %s AND zone_code = %s",
            (PLANT, MODEL, held_sheet["zone"]),
        )
        assert cur.fetchone()[0] is None, "a refused set retired a panel"


@pytest.fixture(autouse=True)
def _t92_proposal_cleanup(admin_conn):
    """T95 D-95-2: this module's own mapping proposals, removed by **id**.

    Replaces the `payload ->> 'note' LIKE` / `payload::text LIKE` delete
    this module's cleanup used to run. The product writes those same notes
    and payloads, so that statement removed a genuine approved proposal
    from the owner's trial database. Same shape as T88 and T29: snapshot
    first, delete only ids that were not there and that carry one of this
    module's markers, then fail loudly rather than leak (T87 D-87-8).
    """
    before = row_keys(admin_conn, "proposed_mapping", "id")
    yield
    forget_proposals(admin_conn, before, ["T91", MARKER], 'T91 canonical apply')
