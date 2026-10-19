"""T83: retire the T54-copied RAPCAP / SGL / Raptor Film lists at AAT, FVL, SAP.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-07

D-FT-08c says ``P703 RAPCAP`` and ``P703 SGL`` exist **only at FTM**, and the
owner decided on 2026-10-07 that ``P703 DBL RAPTOR`` Film is FTM-only too for
now. T54 (migration 0019) mechanically cross-joined the T46/T47 model
catalogue onto every plant, so AAT, FVL and SAP each still carry a RAPCAP
(93), a Single CAP (58) and a Raptor (94) Film gold list -- 735 rows that no
plant ever walks.

**Data only, retire only.** No DDL, no grant, no code. Nothing is deleted
(ADR 0005): the rows take the ``retired_at`` / ``retired_reason`` pair T57
(migration 0021) added, so a fact that ever named one keeps its FK target
while no reader resolves or lists it. ``ref_film_model_alias``,
``ref_plant_model``, every other plant's and model's gold list, and every
fact are untouched. FTM's four lists are untouched.

**Target set** -- ``ref_plant_film_point`` rows that are all of:
``retired_at IS NULL``, ``plant_code IN ('AAT','FVL','SAP')``,
``model_code IN ('P703 RAPCAP','P703 SGL','P703 DBL RAPTOR')``,
``note = 'T54 copy of the T46/T47 model catalogue'`` and
``proof_hash IS NULL``. The note and the null hash are part of the predicate
on purpose: this revision retires **T54's mechanical copy** and nothing a
later owner decision ever proved.

**Guard -- raises and changes nothing unless** the target count is exactly
735, **no** ``filmthickness`` row (active or superseded) names a target
``(plant, model)``, and **no** ``ref_film_model_alias`` row at those plants
maps to those models. The alias check is the one that matters for T78: the
Film vocabulary a model choice may come from is derived from
``ref_film_model_alias`` alone (D-78-32), so retiring a gold list that an
alias still pointed at would leave Choose model offering a model with no
list. All three were verified on the standing cluster while this revision was
written: 735 / 0 / 0.

``ref_film_location_map`` rows at those plants for those models are retired
the same way, with the same reason (expected 0; the live AAT and FTM maps
were already retired by T54 and T57, and no map at these plants ever named
these models).

**Post-asserts.** 0 live rows left in the target set; FTM's four lists still
94 live each; every other ``(plant, model)`` live count unchanged.

``downgrade()`` clears the pair on rows carrying **exactly** this revision's
reason, so it cannot revive what T54, T57 or anything else retired. The
partial unique index ``uq_plant_film_point_no_live`` is safe across the round
trip because a whole list is retired and restored at once, so no live row
holds those ``(plant, model, point_no)`` meanwhile. The audit row stays:
``audit_event`` is append-only.
"""

from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

PLANTS = ("AAT", "FVL", "SAP")
MODELS = ("P703 RAPCAP", "P703 SGL", "P703 DBL RAPTOR")
#: Exactly what 0019 wrote on every cross-joined row.
T54_NOTE = "T54 copy of the T46/T47 model catalogue"
EXPECTED = 735
FTM = "FTM"
FTM_MODELS = ("P703 DBL RANGER", "P703 DBL RAPTOR", "P703 RAPCAP", "P703 SGL")
FTM_POINTS = 94
ACTION = "catalogue.plant_film_point.retire_t54_copy"
REASON = (
    "T83 (D-FT-08c, owner 2026-10-07): T54 copy; RAPCAP/SGL/Raptor Film lists "
    "exist only at FTM"
)

#: The target set, as one SQL predicate, written once.
TARGET = (
    "retired_at IS NULL AND plant_code = ANY(:plants) "
    "AND model_code = ANY(:models) AND note = :note AND proof_hash IS NULL"
)
ARGS = {"plants": list(PLANTS), "models": list(MODELS), "note": T54_NOTE}


def _live_counts(conn) -> dict[tuple[str, str], int]:
    """Live gold rows per ``(plant, model)``: what the post-assert compares."""
    return {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            text(
                "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
                "WHERE retired_at IS NULL GROUP BY 1, 2"
            )
        ).all()
    }


def upgrade() -> None:
    conn = op.get_bind()
    before = _live_counts(conn)

    # --- guard 1: the target set is T54's 735 copied rows ---------------
    per_model = {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            text(
                "SELECT plant_code, model_code, count(*) FROM ref_plant_film_point "
                f"WHERE {TARGET} GROUP BY 1, 2"
            ),
            ARGS,
        ).all()
    }
    found = sum(per_model.values())
    if found != EXPECTED:
        raise RuntimeError(
            f"T83 refused: the target set is {found} rows, expected {EXPECTED}. "
            f"Per (plant, model): {per_model}. Nothing was changed. Re-verify the "
            f"live count and explain it in "
            f"docs/reports/T83-RETIRE-COPIED-FILM-LISTS.md before changing it."
        )

    # --- guard 2: no fact names a target (plant, model) ----------------
    facts = conn.execute(
        text(
            "SELECT plant, model, count(*) FROM filmthickness "
            "WHERE plant = ANY(:plants) AND model = ANY(:models) GROUP BY 1, 2"
        ),
        {"plants": list(PLANTS), "models": list(MODELS)},
    ).all()
    if facts:
        raise RuntimeError(
            f"T83 refused: filmthickness holds facts on a target (plant, model): "
            f"{[tuple(r) for r in facts]}. A walked list is not a T54 leftover. "
            f"Nothing was changed."
        )

    # --- guard 3: no Film alias maps to a target (plant, model) --------
    aliases = conn.execute(
        text(
            "SELECT plant_code, raw_token, model_code FROM ref_film_model_alias "
            "WHERE plant_code = ANY(:plants) AND model_code = ANY(:models) "
            "ORDER BY 1, 2"
        ),
        {"plants": list(PLANTS), "models": list(MODELS)},
    ).all()
    if aliases:
        raise RuntimeError(
            f"T83 refused: {len(aliases)} ref_film_model_alias row(s) still map to "
            f"a target (plant, model): {[tuple(r) for r in aliases]}. The Film "
            f"vocabulary comes from that table (D-78-32), so Choose model would "
            f"offer a model with no list. Retire the alias decision first. "
            f"Nothing was changed."
        )

    # --- the change ----------------------------------------------------
    retired = conn.execute(
        text(
            "UPDATE ref_plant_film_point SET retired_at = now(), retired_reason = :why "
            f"WHERE {TARGET}"
        ),
        {**ARGS, "why": REASON},
    ).rowcount
    maps = conn.execute(
        text(
            "UPDATE ref_film_location_map SET retired_at = now(), retired_reason = :why "
            "WHERE retired_at IS NULL AND plant_code = ANY(:plants) "
            "AND model_code = ANY(:models)"
        ),
        {"plants": list(PLANTS), "models": list(MODELS), "why": REASON},
    ).rowcount

    conn.execute(
        text(
            "INSERT INTO audit_event "
            "(actor_user_id, actor_type, action, entity_type, entity_id, "
            " before, after, correlation_id) "
            "VALUES (NULL, 'system', :action, 'ref_plant_film_point', :entity, "
            "        CAST(:before AS jsonb), CAST(:after AS jsonb), NULL)"
        ),
        {
            "action": ACTION,
            "entity": "AAT,FVL,SAP:P703 RAPCAP,P703 SGL,P703 DBL RAPTOR",
            # Counts only. This cluster's audit_event TOAST files are missing
            # (reported in T77), so an out-of-line value raises UndefinedFile;
            # the per-row list is reproducible from the predicate above anyway.
            "before": json.dumps(
                {
                    "live_per_model": {
                        f"{p}|{m}": n for (p, m), n in sorted(per_model.items())
                    }
                }
            ),
            "after": json.dumps(
                {
                    "revision": "0030",
                    "retired_gold_rows": retired,
                    "retired_location_maps": maps,
                    "note_matched": T54_NOTE,
                    "reason": REASON,
                    "owner_decided": "2026-10-07",
                    "decision": "D-FT-08c",
                }
            ),
        },
    )

    # --- post-asserts --------------------------------------------------
    if retired != EXPECTED:
        raise RuntimeError(f"T83 retired {retired} gold rows, expected {EXPECTED}")
    left = conn.execute(
        text(f"SELECT count(*) FROM ref_plant_film_point WHERE {TARGET}"), ARGS
    ).scalar_one()
    if left:
        raise RuntimeError(f"T83 post-check: {left} live row(s) left in the target set")

    after = _live_counts(conn)
    ftm = {m: after.get((FTM, m)) for m in FTM_MODELS}
    if ftm != {m: FTM_POINTS for m in FTM_MODELS}:
        raise RuntimeError(f"T83 post-check: FTM's gold lists changed: {ftm}")
    want = {
        k: v
        for k, v in (
            (k, 0 if (k[0] in PLANTS and k[1] in MODELS) else v)
            for k, v in before.items()
        )
        if v
    }
    if after != want:
        changed = {
            k: (before.get(k), after.get(k))
            for k in set(before) | set(after)
            if want.get(k, 0) != after.get(k, 0)
        }
        raise RuntimeError(
            f"T83 post-check: a list outside the target set moved: {changed}"
        )

    print(
        f"T83: retired {retired} T54-copied gold rows "
        f"({', '.join(PLANTS)} x {', '.join(MODELS)}) and {maps} location map "
        f"row(s); FTM's four lists unchanged at {FTM_POINTS} each"
    )


def downgrade() -> None:
    """Un-retire only the rows carrying exactly this revision's reason."""
    conn = op.get_bind()
    gold = conn.execute(
        text(
            "UPDATE ref_plant_film_point SET retired_at = NULL, retired_reason = NULL "
            "WHERE retired_reason = :why"
        ),
        {"why": REASON},
    ).rowcount
    maps = conn.execute(
        text(
            "UPDATE ref_film_location_map SET retired_at = NULL, retired_reason = NULL "
            "WHERE retired_reason = :why"
        ),
        {"why": REASON},
    ).rowcount
    print(
        f"T83 downgrade: {gold} gold row(s) and {maps} location map row(s) live again"
    )
