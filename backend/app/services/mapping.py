"""Propose a mapping; approve one; replay the batch it unblocks.

This is the service behind `AGENTS.md` rule 6 — *"Never guess plant, model,
colour, zone, or column mapping. Propose -> Admin approve -> replay.
Similarity scores are advisory."* The rule is enforced by the shape of this
module rather than by a flag, with one named amendment:

* :meth:`MappingService.propose` writes **one row, to one table**,
  ``proposed_mapping``. For ``COLUMN`` and ``ZONE`` it still writes **no
  alias** and parses **nothing**.
* **Identity amendment (spec A2):** ``ALIAS_COLOR`` and rostered
  ``ALIAS_MODEL`` are applied in the same Engineer propose transaction
  (:meth:`MappingService._apply_identity`). Leftover programs (J73 / CX743 /
  V363 / U704) may bind onto that program's own catalogue; they are 422
  onto Ranger. A committed batch that cannot replay still keeps the alias
  (remainder teaching). COLUMN and ZONE still need Admin :meth:`approve`.
* :meth:`MappingService.approve` remains the Admin path for COLUMN / ZONE
  and for any identity proposal that is still ``PROPOSED``.
* ``similarity`` is carried, stored and shown. Nothing here reads it. A test
  greps this file for the word to make sure that stays true.

**Four kinds.** `COLUMN` (a header spelling) and `ALIAS_MODEL` (a model
spelling) are what an unknown WaveScan template actually needs. **T29 adds
`ZONE`**: one proposal is one complete, owner-proved checkpoint set for one
plant and one ``ref_model`` catalogue, approved all or nothing. It does not
close D5; approving an FVL set stores maps and onboards no plant.
**`ALIAS_COLOR` is identity only**
(finish-batch spec H6 / S12): a plant-scoped spelling maps onto an existing
`ref_color.color_name`. It does not close D2; colour-family / standards stay
501. **T41 adds `ALIAS_CHECKZONE`** (D-31): an Engineer maps one panel
spelling at one plant x model onto an **existing** zone on that model's
catalogue, applied in the propose transaction like `ALIAS_COLOR`. It writes
one `ref_plant_zone_map` row (`ENGINEER_ALIAS`), never a zone and never a
pack. `ALIAS_PLANT` and `ALIAS_PAINTLINE` still answer **501**.

**One transaction per approval.** The status change, the alias, the audit row
and the replay enqueue all commit together or not at all. A unique-key
conflict on the alias rolls back the status change with it, so a proposal is
never left `APPROVED` with nothing applied.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.domain.film import film_model_options
from app.domain.film import REASON_FILM_MODEL_UNRESOLVED
from app.domain.mapping_engine import extract_position
from app.domain.references import normalise_alias
from app.domain.ws_plant_gold import gold_key
from app.domain.leftover_models import (
    is_leftover_program,
    leftover_maps_to_own_program,
)
from app.repositories import audit, batches
from app.repositories import batches as batch_repo
from app.repositories import mappings as repo
from app.repositories.filmthickness import load_film_reference
from app.schemas.mappings import (
    IMPLEMENTED_KINDS,
    CheckzoneAliasPayload,
    ColorAliasPayload,
    ColumnPayload,
    FilmModelPayload,
    ModelAliasPayload,
    ProposalCreate,
    ZonePanelMatchPayload,
    ZoneSetPayload,
)
from app.services.ingest import IngestError, IngestService

log = logging.getLogger("app.mapping")

#: Which strict payload model validates which kind.
PAYLOAD_MODEL = {
    "COLUMN": ColumnPayload,
    "ALIAS_MODEL": ModelAliasPayload,
    "ALIAS_COLOR": ColorAliasPayload,
    "ZONE": ZoneSetPayload,
    "ALIAS_CHECKZONE": CheckzoneAliasPayload,
    "FILM_MODEL": FilmModelPayload,
}

#: The key that tells T86's guided panel-match set apart from T29's
#: owner-proved pack. Both are `ZONE`; both are atomic. A pack carries
#: `mappings` (the whole catalogue, with a proof hash), a match set carries
#: `matches` (N pairs a person confirmed on the screen). Discriminating on
#: a key rather than adding a flag to `ZoneSetPayload` is deliberate: every
#: `ZONE` row already in `proposed_mapping` keeps validating unchanged.
PANEL_MATCH_KEY = "matches"


def is_panel_match(payload: dict) -> bool:
    """True when this `ZONE` payload is a T86 guided match set."""
    return isinstance(payload, dict) and PANEL_MATCH_KEY in payload

#: Kinds applied in the Engineer's propose transaction (spec A2, T41).
IDENTITY_KINDS = ("ALIAS_COLOR", "ALIAS_MODEL", "ALIAS_CHECKZONE")


class MappingError(RuntimeError):
    """A mapping request was refused. `status_code` is the answer's code."""

    status_code = 409

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class KindNotImplemented(MappingError):
    status_code = 501


class ProposalInvalid(MappingError):
    status_code = 422


class ProposalNotFound(MappingError):
    status_code = 404


class AlreadyDecided(MappingError):
    status_code = 409


class AliasConflict(MappingError):
    status_code = 409


class ReplayRefused(MappingError):
    status_code = 409


# =====================================================================
class MappingService:
    def __init__(self, ingest: IngestService) -> None:
        # The same ingest service the upload route and the worker use. Replay
        # has to go through it or `02-PIPELINE.md` §10's "two parsers = drift"
        # is exactly what T08 would have built.
        self.ingest = ingest

    # -----------------------------------------------------------------
    def propose(
        self,
        conn: Connection,
        body: ProposalCreate,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Record what an Engineer thinks a header or a spelling means.

        Writes `proposed_mapping` and `audit_event`. For COLUMN and ZONE
        writes **no alias** and parses **nothing**. Identity kinds
        (`ALIAS_COLOR`, rostered `ALIAS_MODEL`) are applied in this
        transaction (spec A2).
        """
        self._require_implemented(body.kind)
        payload = self._validated_payload(body.kind, body.payload)

        # `load_id` is required for every kind but ZONE (the request model
        # enforces that); a ZONE set for FVL has no committable batch.
        batch = None
        if body.load_id is not None:
            batch = batches.get_batch(conn, body.load_id)
            if batch is None:
                raise ProposalInvalid(
                    f"batch {body.load_id} does not exist, so there is nothing "
                    f"to replay once this proposal is approved."
                )

        if body.kind == "ZONE":
            # Everything that can be refused is refused here, before the
            # proposal is recorded, and again at approve time -- the
            # catalogue or the batch can change in between.
            if is_panel_match(payload):
                self._require_valid_panel_match(conn, payload, batch)
            else:
                self._require_complete_zone_set(conn, payload, batch)

        if body.kind == "ALIAS_MODEL":
            # Checked at propose time so the Engineer finds out now rather
            # than when an Admin tries to approve it. Checked again at
            # approve time, because the model list can change in between.
            self._require_known_model(conn, payload["model_code"])
            self._refuse_leftover_onto_foreign(payload)

        if body.kind == "ALIAS_COLOR":
            self._require_known_color(conn, payload["color_name"])
            self._require_color_plant(conn, payload, batch)

        if body.kind == "ALIAS_CHECKZONE":
            self._require_checkzone_target(conn, payload, batch)

        if body.kind == "FILM_MODEL":
            # Checked now so the Engineer is told immediately, and again at
            # approve time, because the vocabulary and the batch can change
            # in between.
            self._require_film_model_choice(conn, payload, batch, body.load_id)

        proposal = repo.insert_proposal(
            conn,
            kind=body.kind,
            payload=payload,
            load_id=body.load_id,
            similarity=body.similarity,
            proposed_by=actor_user_id,
        )
        audit.record(
            conn,
            action="mapping.propose",
            entity_type="proposed_mapping",
            entity_id=proposal["id"],
            actor_user_id=actor_user_id,
            after={
                "kind": body.kind,
                "load_id": body.load_id,
                "status": repo.PROPOSED,
                "payload": payload,
                "applied": False,
            },
            correlation_id=correlation_id,
        )
        log.info(
            "mapping proposed",
            extra={"detail": f"kind={body.kind} load_id={body.load_id}"},
        )
        if body.kind in IDENTITY_KINDS:
            return self._apply_identity(
                conn,
                proposal,
                payload,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            )
        return proposal

    # -----------------------------------------------------------------
    def _apply_identity(
        self,
        conn: Connection,
        proposal: dict,
        payload: dict,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Engineer identity apply: alias + audit; replay if the batch allows.

        A committed remainder cannot replay (ADR 0005). The alias still
        lands so the next file and any PENDING sibling can LOAD (spec R4).
        """
        applied_to = self._apply(conn, proposal, payload, actor_user_id)
        decided = repo.decide(
            conn, proposal["id"], status=repo.APPROVED, decided_by=actor_user_id
        )
        audit.record(
            conn,
            action="mapping.apply",
            entity_type="proposed_mapping",
            entity_id=proposal["id"],
            actor_user_id=actor_user_id,
            before={"status": proposal["status"]},
            after={
                "status": repo.APPROVED,
                "kind": proposal["kind"],
                "applied_to": applied_to,
                "payload": payload,
                "load_id": proposal["load_id"],
            },
            correlation_id=correlation_id,
        )
        if proposal.get("load_id") is not None:
            try:
                self.ingest.replay_batch(
                    conn,
                    proposal["load_id"],
                    actor_user_id=actor_user_id,
                    reason=(
                        f"{proposal['kind']} mapping {proposal['id']} "
                        f"applied by Engineer"
                    ),
                    correlation_id=correlation_id,
                )
            except IngestError:
                log.info(
                    "identity alias applied; batch not replayed",
                    extra={
                        "detail": (
                            f"id={proposal['id']} load_id={proposal['load_id']}"
                        )
                    },
                )
        log.info(
            "identity mapping applied",
            extra={
                "detail": (
                    f"id={proposal['id']} kind={proposal['kind']} "
                    f"-> {applied_to}"
                )
            },
        )
        return decided

    # -----------------------------------------------------------------
    def approve(
        self,
        conn: Connection,
        proposal_id: str,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Apply the alias, record the decision, and queue the replay.

        All four in one transaction, in an order chosen so a failure cannot
        leave a half-decision: the alias is written **before** the status
        moves, so a unique conflict aborts while the proposal is still
        `PROPOSED`.
        """
        proposal = repo.get_proposal_for_update(conn, proposal_id)
        if proposal is None:
            raise ProposalNotFound(f"No mapping proposal {proposal_id}.")

        if proposal["status"] != repo.PROPOSED:
            raise AlreadyDecided(
                f"proposal {proposal_id} is already {proposal['status']}"
                + (
                    f", decided at {proposal['decided_at']:%Y-%m-%d %H:%M:%S%z}."
                    if proposal["decided_at"]
                    else "."
                )
                + " A decision is recorded once; propose a new mapping instead."
            )

        self._require_implemented(proposal["kind"])
        # Re-validated on the way out of the database, not trusted from the
        # way in: the row could predate this code, and T04 writes `COLUMN`
        # rows of its own with a diagnostic payload that carries no mapping
        # at all. Those are a header diff for a person to read, not something
        # to apply.
        payload = self._validated_payload(
            proposal["kind"], proposal["payload"], approving=True
        )
        if proposal["kind"] == "ALIAS_MODEL":
            self._refuse_leftover_onto_foreign(payload)

        if proposal["kind"] == "FILM_MODEL":
            batch = (
                batches.get_batch(conn, proposal["load_id"])
                if proposal.get("load_id") is not None
                else None
            )
            self._require_film_model_choice(
                conn, payload, batch, proposal["load_id"]
            )

        applied_to = self._apply(conn, proposal, payload, actor_user_id)
        # T91 (D-91-2): the spellings this walk confirms that the plant has
        # already confirmed to a DIFFERENT panel. They are never in
        # `matches` -- a set that offered one was refused -- so this audit
        # row is the only place the contradiction is stated, beside the
        # rough count D-90-3 put there for the same reason: the half of a
        # walk deliberately kept out of `ref_plant_zone_map` still has to
        # be findable afterwards.
        walk_contradicted: list[str] = []
        if proposal["kind"] == "ZONE" and is_panel_match(payload):
            walk_pairs = (payload.get("walk") or {}).get("pairs") or []
            walk_contradicted = [
                raw
                for raw, _said, _elsewhere in self._cross_sheet_contradictions(
                    conn,
                    payload["plant_code"],
                    payload["model_code"],
                    {
                        pair["raw_zone_text"]: pair["zone_code"]
                        for pair in walk_pairs
                    },
                )
            ]
        decided = repo.decide(
            conn, proposal_id, status=repo.APPROVED, decided_by=actor_user_id
        )
        audit.record(
            conn,
            action="mapping.approve",
            entity_type="proposed_mapping",
            entity_id=proposal_id,
            actor_user_id=actor_user_id,
            before={"status": proposal["status"]},
            after={
                "status": repo.APPROVED,
                "kind": proposal["kind"],
                "applied_to": applied_to,
                "payload": payload,
                "load_id": proposal["load_id"],
                **_zone_audit(
                    proposal["kind"], payload, walk_contradicted=walk_contradicted
                ),
            },
            correlation_id=correlation_id,
        )

        replay = None
        if proposal["load_id"] is not None:
            try:
                replay = self.ingest.replay_batch(
                    conn,
                    proposal["load_id"],
                    actor_user_id=actor_user_id,
                    reason=f"{proposal['kind']} mapping {proposal_id} approved",
                    correlation_id=correlation_id,
                )
            except IngestError as exc:
                # The alias is good and the decision is real; it is the batch
                # that cannot be replayed. Refusing the whole approval keeps
                # the two consistent -- an Admin who is told "approved" and
                # then finds the batch untouched has been told the wrong
                # thing. Rolling back loses nothing: the proposal can be
                # approved again once the batch is in a replayable state.
                raise ReplayRefused(str(exc)) from exc

        log.info(
            "mapping approved",
            extra={"detail": f"id={proposal_id} kind={proposal['kind']} -> {applied_to}"},
        )
        return {"proposal": decided, "applied_to": applied_to, "replay": replay}

    # -----------------------------------------------------------------
    # internals
    # -----------------------------------------------------------------
    def _apply(
        self, conn: Connection, proposal: dict, payload: dict, actor_user_id: str
    ) -> str:
        """Write the one alias row this proposal stands for."""
        kind = proposal["kind"]
        table = repo.ALIAS_TABLE_BY_KIND[kind]
        if kind == "ZONE":
            if is_panel_match(payload):
                self._apply_panel_match(conn, proposal, payload, actor_user_id)
            else:
                self._apply_zone_set(conn, proposal, payload, actor_user_id)
            return table
        if kind == "ALIAS_CHECKZONE":
            batch = (
                batches.get_batch(conn, proposal["load_id"])
                if proposal.get("load_id") is not None
                else None
            )
            self._require_checkzone_target(conn, payload, batch)
            self._apply_checkzone_alias(conn, proposal, payload, actor_user_id)
            return table
        if kind == "FILM_MODEL":
            return self._apply_film_model(conn, proposal, payload)
        try:
            if kind == "COLUMN":
                domain = payload.get("domain", "WAVESCAN")
                # RO18: the same header already meaning the same field is a
                # confirmation, not a conflict (as ALIAS_COLOR, T39): nothing is
                # inserted and the batch is still replayed. A different field
                # still raises below (409).
                if repo.column_alias(
                    conn, domain, payload["raw_header"]
                ) != payload["logical_field"]:
                    repo.insert_column_alias(
                        conn,
                        raw_header=payload["raw_header"],
                        logical_field=payload["logical_field"],
                        proposed_by=proposal["proposed_by"],
                        approved_by=actor_user_id,
                        # RO18: a Film header is taught in the Film vocabulary.
                        domain=domain,
                    )
            elif kind == "ALIAS_COLOR":
                self._require_known_color(conn, payload["color_name"])
                batch = (
                    batches.get_batch(conn, proposal["load_id"])
                    if proposal.get("load_id") is not None
                    else None
                )
                self._require_color_plant(conn, payload, batch)
                plant_code = payload["plant_code"]
                # T39: the same spelling already meaning the same colour at
                # this plant is not a conflict -- the Engineer is confirming
                # it again so the plant can offer it. A different colour
                # still is (IntegrityError below -> 409).
                if repo.plant_color_alias(
                    conn, plant_code, payload["raw_value"]
                ) != payload["color_name"]:
                    repo.insert_color_alias(
                        conn,
                        raw_value=payload["raw_value"],
                        color_name=payload["color_name"],
                        plant_code=plant_code,
                        note=(
                            f"approved from mapping proposal {proposal['id']}"
                            + f" for plant {plant_code}"
                            + (f": {payload['note']}" if payload.get("note") else "")
                        ),
                    )
                # ADR 0013 decision 10 (D-32): confirming an existing
                # catalogue name this plant does not list yet offers it
                # there. Never a new colour name -- `_require_known_color`
                # above refuses that, and minting stays Admin.
                if not repo.plant_offers_color(conn, plant_code, payload["color_name"]):
                    before = repo.offer_color_at_plant(
                        conn, plant_code, payload["color_name"]
                    )
                    audit.record(
                        conn,
                        action="catalogue.plant_color.offer",
                        entity_type="ref_plant_color",
                        entity_id=f"{plant_code}:{payload['color_name']}",
                        actor_user_id=actor_user_id,
                        before=before,
                        after={
                            "is_offered": True,
                            "via": f"mapping proposal {proposal['id']}",
                            "raw_value": payload["raw_value"],
                        },
                    )
            else:
                self._require_known_model(conn, payload["model_code"])
                # T26 (spec S11): a proposal that came from a batch is about
                # a spelling *that plant* wrote, so the alias is scoped to
                # it. This is the door the task leaves open -- and it is
                # still only an alias. It cannot write a profile, a column
                # policy or `fixture_verified` (M6); those have no statement
                # in this module and no grant behind it.
                plant_code = _proposal_plant(conn, proposal)
                repo.insert_model_alias(
                    conn,
                    raw_value=payload["raw_value"],
                    model_code=payload["model_code"],
                    plant_code=plant_code,
                    note=(
                        f"approved from mapping proposal {proposal['id']}"
                        + (f" for plant {plant_code}" if plant_code else "")
                        + (f": {payload['note']}" if payload.get("note") else "")
                    ),
                )
        except IntegrityError as exc:
            # Same bytes of meaning, already decided. Refuse rather than
            # overwrite: the existing row is somebody's approval, and
            # repointing it would change how every future file is read
            # without anyone deciding to.
            raise AliasConflict(
                f"{table} already carries that mapping, so this proposal was "
                f"not applied and nothing was changed. If the existing alias "
                f"is wrong, that is a correction to it, not a second alias."
            ) from exc
        return table

    # -----------------------------------------------------------------
    # T29 -- ZONE sets
    # -----------------------------------------------------------------
    @staticmethod
    def _refuse_leftover_onto_foreign(payload: dict) -> None:
        raw = payload["raw_value"]
        model = payload["model_code"]
        if is_leftover_program(raw) and not leftover_maps_to_own_program(raw, model):
            raise ProposalInvalid(
                f"raw_value {raw!r} is a leftover program "
                f"(J73 / CX743 / V363 / U704). It is not teachable onto "
                f"{model!r}; bind it to that program's own catalogue "
                f"or leave it held (G1 D-07 / H7)."
            )

    # -----------------------------------------------------------------
    def _require_complete_zone_set(
        self, conn: Connection, payload: dict, batch: dict | None
    ) -> None:
        """Spec section 5.2: every refusal, before anything is written.

        The rule that matters most is completeness. A ZONE set is the whole
        of one model's catalogue or it is nothing: a 31-row set, a 33-row
        set, or 32 rows that drop `LTTAILGATE` and name a hood twice would
        each leave a panel mapped by nobody or by two labels -- which is the
        SAP tailgate Top/Bottom trap in another form.
        """
        plant = payload["plant_code"]
        model = payload["model_code"]
        if not repo.plant_exists(conn, plant):
            raise ProposalInvalid(f"plant {plant!r} is not in ref_plant.")
        family = repo.model_family(conn, model)
        if family is None:
            raise ProposalInvalid(
                f"model_code {model!r} is not in ref_model, and a zone set "
                f"never creates one."
            )
        self._require_known_model(conn, model)  # T46: 422 on a film-only model

        rows = payload["mappings"]
        expected_count = family[1]
        expected = repo.expected_zone_codes(conn, model)
        raws = [r["raw_zone_text"] for r in rows]
        zones = [r["zone_code"] for r in rows]
        problems: list[str] = []
        if len(rows) != expected_count:
            problems.append(
                f"{len(rows)} row(s) where {model} has {expected_count} zones"
            )
        duplicate_raws = sorted({r for r in raws if raws.count(r) > 1})
        if duplicate_raws:
            problems.append(
                "the same raw label twice (once normalised): "
                + ", ".join(repr(r) for r in duplicate_raws)
            )
        duplicate_zones = sorted({z for z in zones if zones.count(z) > 1})
        if duplicate_zones:
            problems.append("a zone mapped twice: " + ", ".join(duplicate_zones))
        missing = sorted(expected - set(zones))
        if missing:
            problems.append("zones no row maps: " + ", ".join(missing))
        foreign = sorted(set(zones) - expected)
        if foreign:
            problems.append(
                f"zones that are not positions on {model}: " + ", ".join(foreign)
            )
        if problems:
            raise ProposalInvalid(
                f"a ZONE set must map the whole {model} catalogue, each zone "
                f"once and each raw label once, or nothing: "
                + "; ".join(problems)
                + ". Nothing was written."
            )

        if batch is not None:
            if batch.get("plant_code") != plant:
                raise ProposalInvalid(
                    f"batch {batch['load_id']} is filed under plant "
                    f"{batch.get('plant_code')!r}, not {plant!r}. A zone set is "
                    f"proved for one plant, and replay would apply it to "
                    f"another."
                )
            if batch["status"] not in batches.REPLAYABLE_STATUSES:
                raise ProposalInvalid(
                    f"batch {batch['load_id']} is {batch['status']}; only a "
                    f"{' or '.join(batches.REPLAYABLE_STATUSES)} batch can be "
                    f"replayed after approval. Omit load_id to store the set "
                    f"without a replay."
                )

    def _apply_zone_set(
        self, conn: Connection, proposal: dict, payload: dict, actor_user_id: str
    ) -> None:
        """Spec section 5.3: insert, certify, or refuse the whole set.

        Runs inside the approving transaction, so the first conflict raises
        and every row already written in this loop is rolled back with the
        proposal's status. Three outcomes per row, and only three:

        * no row for this label -> INSERT, APPROVED, with the owner's proof;
        * a row saying the **same** zone with no proof, or with this very
          proof -> certify it in place;
        * a row saying a **different** zone, or carrying a different proof
          -> 409 for the whole set. `zone_code` is never updated -- it is not
          in the statement and not in the grant.

        Nothing here verifies a template profile (M6) or onboards a plant.
        """
        batch = (
            batches.get_batch(conn, proposal["load_id"])
            if proposal["load_id"] is not None
            else None
        )
        self._require_complete_zone_set(conn, payload, batch)

        plant = payload["plant_code"]
        model = payload["model_code"]
        common = {
            "method": payload["method"],
            "note": payload["note"],
            "proof_hash": payload["proof_hash"],
            "proof_document": payload["proof_document"],
            "named_owner": payload["named_owner"],
            "approved_by": actor_user_id,
        }
        for row in payload["mappings"]:
            raw = row["raw_zone_text"]
            existing = repo.get_zone_map_row_for_update(conn, plant, model, raw)
            if existing is None:
                repo.insert_zone_map_row(
                    conn,
                    plant_code=plant,
                    model_code=model,
                    raw_zone_text=raw,
                    raw_position=row.get("raw_position"),
                    zone_code=row["zone_code"],
                    **common,
                )
                continue
            if existing["zone_code"] != row["zone_code"]:
                raise AliasConflict(
                    f"{plant} / {model} already maps {raw!r} to "
                    f"{existing['zone_code']}, and this set says "
                    f"{row['zone_code']}. A mapping is never repointed by "
                    f"approving another one: nothing in this set was written. "
                    f"If the existing row is wrong, that is a correction the "
                    f"named owner makes explicitly (spec S15)."
                )
            proof = (existing["proof_hash"] or "").strip() or None
            if (proof is not None and proof != payload["proof_hash"]) or (
                existing["verified_by"] is not None
                and existing["verified_by"] != payload["named_owner"]
            ):
                raise AliasConflict(
                    f"{plant} / {model} {raw!r} is already proved by a "
                    f"different proof or owner. A proved mapping is not "
                    f"re-proved by another set: nothing in this set was "
                    f"written."
                )
            repo.certify_zone_map_row(
                conn,
                map_id=existing["map_id"],
                raw_position=row.get("raw_position"),
                **common,
            )

    # ----------------------------------------------------------------
    # T86 -- the guided panel match set (D-86-1..4)
    # ----------------------------------------------------------------
    def _require_valid_panel_match(
        self, conn: Connection, payload: dict, batch: dict | None
    ) -> None:
        """Every refusal of a T86 set, before anything is written.

        What is checked, and why each one is here rather than left to a
        constraint:

        * the plant and model exist, and the model is a WaveScan model;
        * the batch is this plant's and is replayable -- a set answers one
          file, so there is always a batch (the request model requires it);
        * each spelling appears once and each target panel appears once.
          Two spellings onto one panel is exactly August's 64-identity
          defect being created on purpose, so it is refused rather than
          warned about;
        * every target is a **live** panel of this plant x model. A retired
          panel is history, not somewhere new rows may land;
        * every target is on the model's `ref_model_zone` catalogue, which
          is what `ref_plant_zone_map.fk_pzm_model_zone` can reference. A
          live panel that is not on that catalogue is refused **by name**,
          with the reason said out loud -- promoting it would be minting a
          catalogue position, and that is not this screen's decision to make
          (`AGENTS.md` rule 6).
        * nothing in `retire` is also a target. Retiring the panel a pair
          points at would leave the map written and unread, because with a
          gold list present the cleaner only honours a map whose target is
          live (T58, D-58-09). That is a silent no-op, and a silent no-op in
          this platform is a defect.
        """
        plant = payload["plant_code"]
        model = payload["model_code"]
        if not repo.plant_exists(conn, plant):
            raise ProposalInvalid(f"plant {plant!r} is not in ref_plant.")
        if repo.model_family(conn, model) is None:
            raise ProposalInvalid(
                f"model_code {model!r} is not in ref_model, and a panel match "
                f"never creates one."
            )
        self._require_known_model(conn, model)

        if batch is None:
            raise ProposalInvalid(
                f"batch {payload['load_id']} does not exist, so there are no "
                f"held panel spellings to match."
            )
        if batch.get("plant_code") != plant:
            raise ProposalInvalid(
                f"batch {batch['load_id']} is filed under plant "
                f"{batch.get('plant_code')!r}, not {plant!r}. A panel match is "
                f"decided for one plant."
            )

        rows = payload["matches"]
        raws = [r["raw_zone_text"] for r in rows]
        zones = [r["zone_code"] for r in rows]
        live = repo.live_panel_codes(conn, plant, model)
        problems: list[str] = []

        duplicate_raws = sorted({r for r in raws if raws.count(r) > 1})
        if duplicate_raws:
            problems.append(
                "the same file spelling twice (once normalised): "
                + ", ".join(repr(r) for r in duplicate_raws)
            )
        duplicate_zones = sorted({z for z in zones if zones.count(z) > 1})
        if duplicate_zones:
            problems.append(
                "two spellings onto one panel, which is how one panel ends up "
                "with two identities: " + ", ".join(duplicate_zones)
            )
        not_live = sorted(set(zones) - live)
        if not_live:
            problems.append(
                f"panels that are not live at {plant} / {model}: "
                + ", ".join(not_live)
            )
        # T90 (D-90-3): the main safety rule of this task, enforced at the
        # write boundary rather than trusted to the screen. A ROUGH name is
        # one whose core is shared with another name of the same sheet --
        # one of five `HOOD`s -- so the NUMBER is doing the identifying and
        # the name alone names no position. Learning it as a permanent
        # alias would, the month the plant reshuffles its walk, file a hood
        # as the wrong hood with no error anywhere. The rough half of a
        # confirmed walk is recorded on the batch (D-90-11) and refused
        # here, by name.
        walk = payload.get("walk") or {}
        walk_pairs = {
            pair["raw_zone_text"]: pair
            for pair in walk.get("pairs") or []
            if pair.get("raw_zone_text")
        }
        rough_in_matches = sorted(
            raw
            for raw in raws
            if walk_pairs.get(raw, {}).get("specificity") == "rough"
        )
        if rough_in_matches:
            problems.append(
                "names this very walk calls rough, offered as permanent "
                "aliases: " + ", ".join(repr(r) for r in rough_in_matches)
                + ". A rough name shares its core with another name of this "
                "sheet, so its NUMBER is what identifies it -- learning it "
                "forever would file one of these panels as the wrong one the "
                "month the walk is reshuffled, with no error anywhere. It is "
                "confirmed on this batch instead and is not written to "
                "ref_plant_zone_map (D-90-3)"
            )
        contradicted = sorted(
            f"{row['raw_zone_text']!r} ({row['zone_code']} here, "
            f"{walk_pairs[row['raw_zone_text']]['zone_code']} in the walk)"
            for row in rows
            if row["raw_zone_text"] in walk_pairs
            and walk_pairs[row["raw_zone_text"]].get("zone_code")
            != row["zone_code"]
        )
        if contradicted:
            problems.append(
                "pairs the set and its own confirmed walk disagree about: "
                + ", ".join(contradicted)
                + ". One screen cannot send two answers for one name"
            )
        # T91 (D-91-2): the gap D-90-3 left open. Rough-or-specific is a
        # property of ONE SHEET -- `13LFRDOOR` shares its core with
        # `12LFRDOOR` in August, so it is rough there and refused above,
        # but in September nothing shares its core and the same spelling
        # passes as specific. Identity is a property of the PLANT, and at
        # FTM that one spelling is a pillar in August and a door in
        # September. Both files are believed (D-91-1); what cannot be
        # believed is the name on its own. So a spelling ever confirmed to
        # a different panel at this plant x model is per-batch for good,
        # whatever any single sheet's specificity test says.
        forever_batch = self._cross_sheet_contradictions(
            conn, plant, model, {r["raw_zone_text"]: r["zone_code"] for r in rows}
        )
        if forever_batch:
            problems.append(
                "names this plant has already confirmed to a DIFFERENT panel, "
                "offered as permanent aliases: "
                + "; ".join(
                    f"{raw!r} ({said} here, but "
                    + " and ".join(other)
                    + ")"
                    for raw, said, other in forever_batch
                )
                + ". One spelling meaning two different physical panels in two "
                "months is correct and expected -- each file is believed about "
                "itself -- but it means this name alone no longer identifies a "
                "panel here, so it is confirmed per upload on the batch and is "
                "never written to ref_plant_zone_map again. Specificity is a "
                "property of a sheet; identity is a property of the plant "
                "(D-91-2)"
            )
        retire = payload.get("retire") or {}
        retiring = list(retire.get("zone_codes") or [])
        overlap = sorted(set(retiring) & set(zones))
        if overlap:
            problems.append(
                "panels both matched onto and retired: " + ", ".join(overlap)
                + ". The map would be written and never read, because a map "
                "is only honoured while its target is live"
            )
        retire_not_live = sorted(set(retiring) - live)
        if retire_not_live:
            problems.append(
                f"panels to retire that are not live at {plant} / {model}: "
                + ", ".join(retire_not_live)
            )
        # T89 (D-89-4): ORDER. A spelling that lands on a panel only because
        # that panel is live stops resolving the moment it is retired --
        # `cleaner.resolve_checkzone` matches the text against the gold list
        # first, so retiring `11ROOF` without first saying what `11ROOF`
        # means instead makes the next upload worse, not better. The set is
        # atomic, so "aliases first, then retirement" is kept by refusing a
        # retirement this very set does not cover.
        orphaned = self._retirement_without_a_pair(
            conn, payload, batch, retiring, rows
        )
        if orphaned:
            problems.append(
                "panels to retire whose own name nothing here says the "
                "meaning of: "
                + "; ".join(f"{zone} ({why})" for zone, why in orphaned)
                + ". This file writes those names, and they resolve today "
                "only because those panels are live -- retiring them first "
                "would stop the names resolving and hold the next upload "
                "with nothing to pre-fill it from. A pair in this set's "
                "matches, a pair in this set's walk, or the same answer "
                "already confirmed on an earlier upload here all count "
                "(D-89-4, D-92-1)"
            )
        if problems:
            raise ProposalInvalid(
                "this panel match set was refused and nothing was written: "
                + "; ".join(problems)
                + "."
            )

        if batch["status"] not in batches.REPLAYABLE_STATUSES:
            raise ProposalInvalid(
                f"batch {batch['load_id']} is {batch['status']}; only a "
                f"{' or '.join(batches.REPLAYABLE_STATUSES)} batch can be "
                f"replayed after approval, and a panel match is only worth "
                f"anything once those rows are read again."
            )

    def _apply_panel_match(
        self, conn: Connection, proposal: dict, payload: dict, actor_user_id: str
    ) -> None:
        """Write the whole set and the retirement, or write nothing.

        Runs inside the approving transaction, so the first refusal rolls
        back every row this loop already wrote **and** the proposal's
        status. Three outcomes per pair, and only three:

        * no row for this spelling -> INSERT, APPROVED, `T86_PANEL_MATCH`;
        * a row already saying the **same** panel -> left exactly as it is.
          Approving a set twice is not a conflict, and it is not a rewrite
          either;
        * a row saying a **different** panel -> 409 for the whole set.
          `zone_code` is never updated here; repointing an existing map is a
          correction somebody makes deliberately, not a side effect of
          approving something else.
        """
        batch = (
            batches.get_batch(conn, proposal["load_id"])
            if proposal["load_id"] is not None
            else None
        )
        self._require_valid_panel_match(conn, payload, batch)

        plant = payload["plant_code"]
        model = payload["model_code"]
        note = (
            f"T86 panel match from proposal {proposal['id']}: decided by "
            f"{payload['decided_by']} -- {payload['method']}. "
            f"{payload['note']}"
        )
        for row in payload["matches"]:
            raw = row["raw_zone_text"]
            existing = repo.get_zone_map_row_for_update(conn, plant, model, raw)
            if existing is None:
                repo.insert_panel_match_row(
                    conn,
                    plant_code=plant,
                    model_code=model,
                    raw_zone_text=raw,
                    raw_position=row.get("raw_position"),
                    zone_code=row["zone_code"],
                    approved_by=actor_user_id,
                    # T88 (G-88-6): the note carries who, when and from
                    # which batch; `proposal_method` carries which signal
                    # proposed it, so the audit can find them by predicate.
                    note=f"{note} Proposed by: {row.get('proposed_by_signal') or 'none'}.",
                    signal=row.get("proposed_by_signal"),
                )
                continue
            if existing["zone_code"] != row["zone_code"]:
                raise AliasConflict(
                    f"{plant} / {model} already maps {raw!r} to "
                    f"{existing['zone_code']}, and this set says "
                    f"{row['zone_code']}. Nothing in this set was written. A "
                    f"map is never repointed by approving another one; if the "
                    f"existing row is wrong that is a correction to it."
                )

        retire = payload.get("retire") or {}
        if retire.get("zone_codes"):
            retired = repo.retire_plant_panels(
                conn,
                plant_code=plant,
                model_code=model,
                zone_codes=list(retire["zone_codes"]),
                reason=(
                    f"{retire['reason']} (T86 proposal {proposal['id']}, "
                    f"decided by {payload['decided_by']})"
                ),
            )
            audit.record(
                conn,
                action="catalogue.plant_ws_point.retire",
                entity_type="ref_plant_ws_point",
                entity_id=f"{plant}:{model}",
                actor_user_id=actor_user_id,
                before={"live": sorted(retire["zone_codes"])},
                after={
                    "retired": sorted(retired),
                    "retired_reason": retire["reason"],
                    "decided_by": payload["decided_by"],
                    "via": f"mapping proposal {proposal['id']}",
                },
            )

    # ----------------------------------------------------------------
    # T61 / T78: the Film sheet model choice (D-78-30..34)
    # ----------------------------------------------------------------
    def _film_model_options(self, conn: Connection, batch: dict):
        """The same server-derived options the held-label read published.

        Recomputed from the batch, never taken from the request: that is
        what makes "the client never sends free text" true at approve time
        as well as at propose time.
        """
        film = load_film_reference(conn)
        return film_model_options(
            batch["plant_code"],
            batch["source_file"],
            batch["source_sheet"],
            film.model_alias,
        )

    def _require_film_model_choice(
        self, conn: Connection, payload: dict, batch: dict | None, load_id: int | None
    ) -> None:
        """Every 422 in D-78-32/34, in one place, checked twice.

        A Film model is offered only through the plant's Film vocabulary
        (D-78-21), so one membership test covers a model outside that set, a
        leftover program with no Film list at this plant (F8 / D-55-09) and
        any WaveScan-only reading such as `RAP` meaning Raptor (D-FT-08).
        """
        if batch is None:
            raise ProposalInvalid(
                "a FILM_MODEL choice is about one held sheet, so load_id must "
                "name an existing batch."
            )
        if payload["load_id"] != load_id:
            raise ProposalInvalid(
                f"payload.load_id {payload['load_id']} is not the proposal's "
                f"load_id {load_id}. The payload names the sheet, so it names "
                f"its batch too."
            )
        if (batch.get("domain") or "") != "FILMTHICKNESS":
            raise ProposalInvalid(
                f"batch {load_id} is {batch.get('domain') or 'not a FilmThickness'} "
                f"data, and FILM_MODEL only answers a FilmThickness sheet. A "
                f"WaveScan model spelling is ALIAS_MODEL."
            )
        if payload["plant"] != batch["plant_code"]:
            raise ProposalInvalid(
                f"payload.plant {payload['plant']!r} is not batch {load_id}'s "
                f"plant {batch['plant_code']!r}."
            )
        if payload["source_sheet"] != batch["source_sheet"]:
            raise ProposalInvalid(
                f"batch {load_id} is sheet {batch['source_sheet']!r}, not "
                f"{payload['source_sheet']!r}. One batch is one sheet."
            )
        if not repo.film_model_hold_rows(conn, load_id):
            raise ProposalInvalid(
                f"sheet {batch['source_sheet']!r} of batch {load_id} is not held "
                f"{REASON_FILM_MODEL_UNRESOLVED}, so there is no model question "
                f"to answer on it."
            )

        options = self._film_model_options(conn, batch)
        model = payload["model_code"]
        if model not in options.choices:
            plant = batch["plant_code"]
            if is_leftover_program(model):
                raise ProposalInvalid(
                    f"{model!r} is a leftover program with no FilmThickness list "
                    f"at {plant}. It waits for its own catalogue; it is never "
                    f"folded onto a P703 list (F8, D-55-09). {plant}'s Film "
                    f"vocabulary is {list(options.choices)}."
                )
            raise ProposalInvalid(
                f"{model!r} is not in {plant}'s FilmThickness vocabulary "
                f"{list(options.choices)}. A Film model is offered only through "
                f"that list, and a WaveScan reading is never one of them "
                f"(D-FT-08: Film RAP is RAPCAP, never Raptor)."
            )

        token = payload.get("raw_token")
        if token is None:
            return
        if not options.teachable_tokens:
            raise ProposalInvalid(
                f"the file and tab name gave more than one model for this "
                f"sheet, so the choice resolves this sheet only and teaches no "
                f"alias: raw_token must be absent. {options.detail}."
            )
        if token not in options.teachable_tokens:
            raise ProposalInvalid(
                f"raw_token {token!r} is not one of this sheet's teachable "
                f"tokens {list(options.teachable_tokens)}. Tokens are derived "
                f"by the server from the file and tab name; free text is never "
                f"taught (D-78-30)."
            )

    def _apply_film_model(
        self, conn: Connection, proposal: dict, payload: dict
    ) -> str:
        """Teach the token if there is one. The sheet choice needs no row.

        D-78-31: the approved proposal itself is what replay reads for this
        `(load_id, source_sheet)`, so an ambiguous choice writes nothing and
        is still a complete record.
        """
        table = repo.ALIAS_TABLE_BY_KIND["FILM_MODEL"]
        token = payload.get("raw_token")
        if token is None:
            return f"{table} (none: sheet-only choice)"

        plant, model = payload["plant"], payload["model_code"]
        existing = repo.plant_film_model_alias(conn, plant, token)
        if existing == model:
            # T39's reasoning: the same token already meaning the same model
            # is the Engineer confirming it, not a conflict.
            return table
        if existing is not None:
            raise AliasConflict(
                f"{plant} already teaches Film token {token!r} as {existing!r}, "
                f"not {model!r}. An alias is never overwritten (D-78-33): "
                f"repointing a live token is a correction, not a second map. "
                f"Nothing was written."
            )
        note = (
            f"approved from mapping proposal {proposal['id']} for plant {plant}"
            + (f": {payload['note']}" if payload.get("note") else "")
        )
        repo.insert_film_model_alias(
            conn, plant_code=plant, raw_token=token, model_code=model, note=note,
        )
        return table

    def _prior_walk_targets(
        self, conn: Connection, plant: str, model: str
    ) -> dict[str, list[tuple[str, dict]]]:
        """Every panel each spelling has ever been confirmed as, here.

        One read of `mappings.confirmed_walk_sets` (T90's batch-side read),
        keyed by normalised spelling, so that the two questions T91 and T92
        ask of the plant's own history are asked of the same answer:

        * *has this spelling meant something else?* -- D-91-2's refusal to
          learn it forever (`_cross_sheet_contradictions`);
        * *has this spelling been given a meaning at all?* -- D-92-1's third
          path for retirement (`_retirement_without_a_pair`).

        Still a refusal path and never a resolution path (D-90-11): it runs
        in the API write boundary, and `domain/cleaner.py` has no route to
        a proposal or a batch.
        """
        prior: dict[str, list[tuple[str, dict]]] = {}
        for walk_set in repo.confirmed_walk_sets(
            conn, plant_code=plant, model_code=model
        ):
            for spelling, zone in walk_set["pairs"].items():
                prior.setdefault(normalise_alias(spelling), []).append(
                    (zone, walk_set)
                )
        return prior

    def _cross_sheet_contradictions(
        self,
        conn: Connection,
        plant: str,
        model: str,
        offered: dict[str, str],
    ) -> list[tuple[str, str, list[str]]]:
        """T91 (D-91-2): names a prior confirmed walk gives another panel.

        `offered` is spelling -> panel this set says. The answer is one
        tuple per contradicted spelling: the spelling, the panel this set
        says, and one sentence per disagreeing confirmation naming the
        panel and the file it was confirmed on. A spelling nobody has
        confirmed differently is not in the answer at all, so confirming
        the SAME pair twice is never refused (T91 section 5).

        The prior walks are read with `mappings.confirmed_walk_sets`, the
        same batch-side read T90 built for the pre-fill. That is a read of
        batch data on purpose and it does not weaken D-90-11: this runs in
        the API write path, which already reads batches, and never in
        `domain/cleaner.py`, which still resolves a panel from
        `ReferenceData` alone and has no route to a proposal or a batch.
        What travels here is a refusal, never a resolution.

        The set being approved is itself one of these confirmed walks by
        the time this is read, which costs nothing: it agrees with itself,
        and a pair it disagrees with its own walk about is refused a few
        lines above.
        """
        prior = self._prior_walk_targets(conn, plant, model)
        out: list[tuple[str, str, list[str]]] = []
        for raw in sorted(offered):
            said = offered[raw]
            others: dict[str, list[str]] = {}
            for zone, walk_set in prior.get(normalise_alias(raw), ()):
                if zone == said:
                    continue
                where = walk_set["source_file"] or (
                    f"batch {walk_set['load_id']}"
                )
                others.setdefault(zone, [])
                if where not in others[zone]:
                    others[zone].append(where)
            if others:
                out.append((
                    raw,
                    said,
                    [
                        f"{zone} was confirmed on " + " and ".join(
                            repr(w) for w in files
                        )
                        for zone, files in sorted(others.items())
                    ],
                ))
        return out

    def _retirement_without_a_pair(
        self,
        conn: Connection,
        payload: dict,
        batch: dict,
        retiring: list[str],
        rows: list[dict],
    ) -> list[tuple[str, str]]:
        """Panels this set retires without saying what their name means (D-89-4).

        A retirement is safe when nothing depends on that panel's own name
        resolving any more. The ways it is safe, and the panel is listed
        only when **none** of them holds:

        * this set carries a pair for that name in `matches`, so the alias
          and the retirement land in one transaction, alias first;
        * **T92 (D-92-1): this set's own `walk` block pairs that name.** A
          *rough* name can never be a permanent alias (D-90-3), so its
          meaning lives in the walk recorded on the batch (D-90-11) and
          nowhere else -- and before T92 the guard did not look there, which
          meant 28 of FTM's 32 numbered names could never be retired and
          audit finding 3 could never reach 0. A confirmed walk states a
          meaning; it states it for one upload instead of for ever, and the
          guard's question is whether a meaning was stated at all;
        * **T92 (D-92-1): a prior confirmed walk of this `(plant, model)`
          names it, and they all name the SAME panel.** The plant has
          already answered this name once and has not since disagreed;
        * this plant x model already has an approved map for that name;
        * no row of this file uses that name at all -- not a held row and
          not a loaded one -- so retiring the panel takes nothing away.

        **T92 (D-92-2):** if prior walks name **different** panels for one
        spelling -- FTM's `13LFRDOOR`, a pillar in August and a door in
        September -- the third path does **not** apply. A name the plant
        disagrees with itself about has not been explained by history, so
        only this set can state it. The contradiction is read with the same
        `_cross_sheet_contradictions` that refuses to learn such a name
        forever (D-91-2), so the two rules can never drift apart.

        What this does **not** change: nothing here makes a retired name
        resolve. A numbered name with no gold entry and no permanent alias
        is **held** on the next upload and pre-filled from the last
        confirmed walk (D-90-5, D-90-12, and D-92-3's proof). Held is the
        safe outcome; the thing this guard exists to prevent is a name
        silently resolving to a *different* panel, and a retirement cannot
        cause that.

        Each refused panel comes back with **which path was missing**, so a
        reader of the message can tell what to add rather than guessing.
        Compared on `gold_key`, which is the key the gold list itself is
        matched on (D-58-03), so ``01HOOD`` and ``1HOOD`` are one name.
        """
        if not retiring:
            return []
        plant = payload["plant_code"]
        model = payload["model_code"]
        load_id = int(batch["load_id"])
        taught_here = {
            gold_key(row["raw_zone_text"])
            for row in repo.taught_panel_pairs(conn, plant)
            if row["model_code"] == model and row["status"] == repo.APPROVED
        }
        in_this_set = {gold_key(r["raw_zone_text"]) for r in rows}
        # (b) the set's own walk. The pair has to carry a target: a walk row
        # with no answer is a question, not a meaning.
        walk_pairs = (payload.get("walk") or {}).get("pairs") or []
        in_this_walk = {
            gold_key(pair["raw_zone_text"])
            for pair in walk_pairs
            if pair.get("raw_zone_text") and pair.get("zone_code")
        }
        # (c) the plant's own history, minus anything it disagrees with
        # itself about (D-92-2).
        prior = self._prior_walk_targets(conn, plant, model)
        contradicted = {
            gold_key(spelling)
            for spelling, answers in prior.items()
            if len({zone for zone, _set in answers}) > 1
        }
        stated_before = {
            gold_key(spelling)
            for spelling, answers in prior.items()
            if answers and gold_key(spelling) not in contradicted
        }
        used_names = {
            gold_key(spelling)
            for spelling in batch_repo.file_panel_spellings(conn, load_id)
        }
        used_names |= {
            gold_key(spelling)
            for spelling in batch_repo.panels_already_used_by(
                conn, load_id, model
            ).values()
        }
        refused: list[tuple[str, str]] = []
        for zone in sorted(set(retiring)):
            key = gold_key(zone)
            if key not in used_names:
                continue
            if key in in_this_set or key in in_this_walk or key in taught_here:
                continue
            if key in stated_before:
                continue
            refused.append((
                zone,
                "this very name is confirmed as a different panel by an "
                "earlier upload here, so history does not explain it -- say "
                "what it means in this set's walk (D-92-2)"
                if key in contradicted
                else "no pair for this name in this set's matches, none in "
                "this set's walk, none confirmed on an earlier upload here, "
                "and no learned alias -- add the pair for it to this same "
                "set (D-92-1)",
            ))
        return refused

    def _require_checkzone_target(
        self, conn: Connection, payload: dict, batch: dict | None
    ) -> None:
        """T41: an existing model, on this plant's list, and a zone that
        model already has. Nothing here mints a zone or a model."""
        self._require_color_plant(conn, payload, batch)
        model = payload["model_code"]
        self._require_known_model(conn, model)
        if not repo.model_offered_at(conn, payload["plant_code"], model):
            raise ProposalInvalid(
                f"model {model!r} is not on {payload['plant_code']}'s list, so "
                f"its panels cannot be mapped there."
            )
        # T58 (D-58-10): the target must already be gold at this plant x model.
        zones = repo.plant_zone_codes(conn, payload["plant_code"], model)
        if payload["zone_code"] not in zones:
            raise ProposalInvalid(
                f"zone_code {payload['zone_code']!r} is not a panel of {model} at "
                f"{payload['plant_code']} (that plant's panel list). An Engineer "
                f"picks one of those existing panels; a new panel or a full ZONE "
                f"set is Admin / named owner (T29). Nothing was written."
            )
        # RO18 (B1): live here is enough -- `fk_pzm_plant_point` (revision
        # 0048) lets the map land on this plant x model's own panel.

    def _apply_checkzone_alias(
        self, conn: Connection, proposal: dict, payload: dict, actor_user_id: str
    ) -> None:
        """One row. The same spelling already meaning the same zone is not a
        conflict; a different zone is (409) -- repointing a live label is a
        correction, not a second map."""
        raw = normalise_alias(payload["raw_value"])
        existing = repo.get_zone_map_row_for_update(
            conn, payload["plant_code"], payload["model_code"], raw
        )
        if existing is not None:
            if (
                existing["zone_code"] == payload["zone_code"]
                and existing["confidence"] == "APPROVED"
            ):
                return
            raise AliasConflict(
                f"{payload['plant_code']} / {payload['model_code']} "
                f"{payload['raw_value']!r} already has a panel map "
                f"({existing['zone_code']}, {existing['confidence']}). It was "
                f"not changed; an Admin decides a correction."
            )
        repo.insert_engineer_zone_alias(
            conn,
            plant_code=payload["plant_code"],
            model_code=payload["model_code"],
            raw_zone_text=raw,
            raw_position=extract_position(payload["raw_value"]),
            zone_code=payload["zone_code"],
            approved_by=actor_user_id,
            note=(
                f"Engineer panel map from proposal {proposal['id']}"
                + (f": {payload['note']}" if payload.get("note") else "")
            ),
        )

    def _require_implemented(self, kind: str) -> None:
        if kind not in IMPLEMENTED_KINDS:
            raise KindNotImplemented(
                f"{kind} mapping proposals are reserved by the API contract "
                f"and not implemented. T08 implements "
                f"{' and '.join(IMPLEMENTED_KINDS)}; the rest wait on "
                f"decisions this platform has not made (docs/DEFERRED.md). "
                f"Your role is sufficient; the behaviour does not exist yet."
            )

    def _validated_payload(
        self, kind: str, payload: dict, *, approving: bool = False
    ) -> dict:
        model = PAYLOAD_MODEL[kind]
        if kind == "ZONE" and is_panel_match(payload):
            model = ZonePanelMatchPayload
        try:
            return model.model_validate(payload).model_dump()
        except ValidationError as exc:
            where = (
                "This proposal's payload does not describe a mapping that can "
                "be applied"
                if approving
                else f"payload is not a valid {kind} mapping"
            )
            raise ProposalInvalid(f"{where}: {_readable(exc)}") from exc

    def _require_known_model(self, conn: Connection, model_code: str) -> None:
        """`ref_model` is the list of models; this route does not extend it.

        T46 (F5): every kind here is a WaveScan mapping, so a FilmThickness-
        only model (`wavescan_ok = false`, P703 RAPCAP / P703 SGL) is 422 --
        not this domain -- and never a Ranger stand-in.
        """
        if repo.model_exists(conn, model_code):
            if repo.model_wavescan_ok(conn, model_code) is False:
                raise ProposalInvalid(
                    f"model_code {model_code!r} is a FilmThickness-only model "
                    f"(wavescan_ok = false). A WaveScan alias, zone set or "
                    f"panel map cannot name it: not this domain (T46 F5)."
                )
            return
        known = repo.known_models(conn)
        raise ProposalInvalid(
            f"model_code {model_code!r} is not in ref_model, and approving a "
            f"mapping never creates one -- onboarding a model is a separate "
            f"decision. Known models: {', '.join(known) or '(none)'}."
        )

    def _require_known_color(self, conn: Connection, color_name: str) -> None:
        """`ref_color` is the catalogue; this route does not extend it.

        T64 (ADR 0014): a merged name is refused; the spelling belongs on
        its canonical name, which is the one a plant offers.
        """
        if repo.color_exists(conn, color_name):
            canonical = repo.color_merged_into(conn, color_name)
            if canonical is not None:
                raise ProposalInvalid(
                    f"{color_name!r} is merged into {canonical!r}. Map the "
                    f"spelling onto {canonical!r} instead."
                )
            return
        known = repo.known_colors(conn)
        raise ProposalInvalid(
            f"color_name {color_name!r} is not in ref_color, and approving a "
            f"mapping never creates one -- a new colour name is a named-owner "
            f"catalogue decision. Known colours: "
            f"{', '.join(known) or '(none)'}."
        )

    def _require_color_plant(
        self, conn: Connection, payload: dict, batch: dict | None
    ) -> None:
        """Identity aliases are plant-scoped (S12). The named plant must exist,
        and when a batch is attached it must be that batch's plant."""
        plant = payload["plant_code"]
        if not repo.plant_exists(conn, plant):
            raise ProposalInvalid(f"plant {plant!r} is not in ref_plant.")
        if batch is not None and batch.get("plant_code") and batch["plant_code"] != plant:
            raise ProposalInvalid(
                f"payload.plant_code {plant!r} is not this batch's plant "
                f"{batch['plant_code']!r}."
            )


def _zone_audit(
    kind: str, payload: dict, *, walk_contradicted: list[str] | None = None
) -> dict:
    """The fields spec section 5.3 step 5 names for a ZONE approval."""
    if kind != "ZONE":
        return {}
    if is_panel_match(payload):
        # T86: what a reader of the audit log needs in order to answer
        # "who said this name is that panel, and what did it retire?"
        retire = payload.get("retire") or {}
        # T90: the walk the set was confirmed against, so the audit can
        # answer "which walk was this, and how much of it was rough?" --
        # the rough half is the half that is deliberately NOT in
        # ref_plant_zone_map, so the only record of it is the batch and
        # this line (D-90-3, D-90-11).
        walk = payload.get("walk") or {}
        walk_pairs = walk.get("pairs") or []
        return {
            "plant_code": payload["plant_code"],
            "model_code": payload["model_code"],
            "panel_match_count": len(payload["matches"]),
            "decided_by": payload["decided_by"],
            "method": payload["method"],
            "retired_zone_codes": list(retire.get("zone_codes") or []),
            "retired_reason": retire.get("reason"),
            "walk_fingerprint": walk.get("fingerprint"),
            "walk_pair_count": len(walk_pairs),
            "walk_rough_count": sum(
                1 for pair in walk_pairs if pair.get("specificity") == "rough"
            ),
            # T91 (D-91-2): per-batch for good, whatever this sheet's own
            # specificity test says, because another sheet of this plant
            # confirmed the same spelling as a different panel.
            "walk_contradicted": sorted(walk_contradicted or []),
        }
    return {
        "plant_code": payload["plant_code"],
        "model_code": payload["model_code"],
        "mapping_count": len(payload["mappings"]),
        "proof_hash": payload["proof_hash"],
        "named_owner": payload["named_owner"],
    }


def _proposal_plant(conn: Connection, proposal: dict) -> str | None:
    """The plant a proposal is about, or None when it is about no batch.

    Read from `load_batch.plant_code`, which T17 sets at create from the
    upload's declared scope and never re-derives from the rows. So the plant
    an alias is scoped to is the plant somebody filed the workbook under, not
    a plant inferred from what the cells happened to say.
    """
    if proposal.get("load_id") is None:
        return None
    batch = batches.get_batch(conn, proposal["load_id"])
    return batch.get("plant_code") if batch else None


def _readable(exc: ValidationError) -> str:
    """Pydantic's errors, flattened to one line a person can act on."""
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'payload'}: {e['msg']}"
        for e in exc.errors()
    )
