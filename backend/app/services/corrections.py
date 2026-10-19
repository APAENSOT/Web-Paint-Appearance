"""Correct a measurement; retire a batch. Neither deletes anything.

ADR 0005 and `01-DATA-MODEL.md` §5 settled the mechanism long before T09:
`wavescan` is insert-only, a correction is a **new row plus a supersession
record**, and a batch is retired by **changing its status**. T02 built all of
it -- the side table, the `AFTER INSERT` trigger that sets `is_superseded`,
the `BEFORE INSERT` trigger that refuses a pre-flagged row, the column-scoped
grant on `load_batch`. This module is the part that calls it.

So the interesting question is not how a correction is written but what this
service refuses:

* a measurement that does not exist -> **404**;
* one that exists but is not current -- already corrected, flagged duplicate,
  or owned by a batch that is not `COMMITTED` -> **409**, saying which;
* a batch that is not `COMMITTED` -> **409**;
* a replacement batch that is missing, not committed, a different plant, or
  the batch itself -> **409**.

Every refusal happens before anything is written, and everything that is
written happens in the caller's single transaction -- the row, the
supersession record and the `audit_event` commit together or not at all
(`AGENTS.md` §2).

**Engineer commit still does not auto-supersede.** `02-PIPELINE.md` §3 says a
new hash with a known name and plant means the old batch should be retired,
and §7 makes that an **Admin** action. T04 recorded the gap deliberately;
T09 fills it with this route and does not touch commit. Nothing in
`services/ingest.py` calls anything here, and a test asserts it.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.repositories import audit, batches, measurements
from app.repositories import corrections as repo
from app.repositories.measurements import MeasurementFilter
from app.schemas.corrections import (
    AbandonCreate,
    CorrectionCreate,
    RestoreCreate,
    SupersedeCreate,
)

log = logging.getLogger("app.corrections")

STATUS_SUPERSEDED = "SUPERSEDED"

#: T21: the statuses a sheet may be abandoned from. None of them has
#: produced a measurement; RUNNING is mid-parse and is not a decision yet.
ABANDONABLE_STATUSES = ("PENDING_REVIEW", "REJECTED_TEMPLATE", "FAILED")


class CorrectionError(RuntimeError):
    """A correction or supersede was refused. `status_code` is the answer."""

    status_code = 409

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MeasurementNotFound(CorrectionError):
    status_code = 404


class NotCorrectable(CorrectionError):
    status_code = 409


class BatchNotFound(CorrectionError):
    status_code = 404


class BatchNotSupersedable(CorrectionError):
    status_code = 409


class BatchNotAbandonable(CorrectionError):
    status_code = 409


class BatchNotRestorable(CorrectionError):
    status_code = 409


#: T25: the two statuses a batch can be brought back from, and what each
#: returns to. An abandoned sheet goes back to the status it left from; a
#: retired one goes back to COMMITTED, its facts untouched in `wavescan`.
RESTORABLE_STATUSES = (batches.STATUS_ABANDONED, STATUS_SUPERSEDED)

#: The reason written when the door is an identical-file upload rather than
#: the restore route (T25 locked decision 9).
IDENTICAL_UPLOAD_REASON = "Reopened by identical-file upload"


# =====================================================================
class CorrectionService:
    def correct(
        self,
        conn: Connection,
        measurement_id: int,
        body: CorrectionCreate,
        *,
        actor_user_id: str,
        scope: MeasurementFilter,
        correlation_id: str | None = None,
    ) -> dict:
        """Insert the corrected reading and retire the one it replaces.

        Order matters and is not interchangeable:

        1. does the measurement exist at all -- 404 if not;
        2. re-read it through the **active view**, so the thing being
           corrected is the thing the plant table is showing;
        3. insert the new row, copying identity from the original in SQL;
        4. insert the supersession record, which is what retires the original
           -- via the trigger, never by this code;
        5. write the audit event.

        Doing 4 before 3 would retire a measurement with nothing to replace
        it, and a failure in between would leave it retired for good, because
        a supersession cannot be withdrawn.

        There is no row lock. Taking one would need `UPDATE` on `wavescan`,
        which the application role does not have and must not get, so two
        simultaneous corrections of the same reading are serialised by
        `uq_supersession_once` instead: the second blocks on that unique
        index, fails, and its half-written row rolls back with it. That is
        handled below and answered 409.
        """
        if not repo.exists(conn, measurement_id):
            raise MeasurementNotFound(f"No measurement {measurement_id}.")

        active = measurements.get_active(conn, measurement_id, scope)
        if active is None:
            raise NotCorrectable(self._why_not_correctable(conn, measurement_id))

        new_id = repo.insert_correction(
            conn,
            original_id=measurement_id,
            patch=body.patch,
            reason=body.reason.strip(),
            actor_user_id=actor_user_id,
        )
        try:
            supersession_id = repo.record_supersession(
                conn,
                superseded_measurement_id=measurement_id,
                superseded_by_measurement_id=new_id,
                reason=body.reason.strip(),
                actor_user_id=actor_user_id,
            )
        except IntegrityError as exc:
            # `uq_supersession_once`: another transaction retired this
            # measurement first. This is the whole concurrency story -- see
            # the note above about why there is no row lock. The correction
            # row written a moment ago rolls back with this transaction, so
            # nothing is left pointing at a measurement somebody else retired.
            raise NotCorrectable(
                f"measurement {measurement_id} was retired by another "
                f"correction while this one was being written. Nothing was "
                f"changed; correct the row that replaced it."
            ) from exc

        corrected = measurements.get_active(conn, new_id, scope)
        if corrected is None:  # pragma: no cover - would mean the view is wrong
            raise CorrectionError(
                f"the correction was written as measurement {new_id} but does "
                f"not read back as active. Nothing was committed."
            )

        audit.record(
            conn,
            action="measurement.correct",
            entity_type="wavescan",
            entity_id=measurement_id,
            actor_user_id=actor_user_id,
            before={
                "measurement_id": measurement_id,
                **{k: str(active[k]) for k in body.patch if active.get(k) is not None},
            },
            after={
                "measurement_id": new_id,
                "corrects_measurement_id": measurement_id,
                "supersession_id": supersession_id,
                "reason": body.reason.strip(),
                **{k: (str(v) if v is not None else None) for k, v in body.patch.items()},
            },
            correlation_id=correlation_id,
        )
        log.info(
            "measurement corrected",
            extra={"detail": f"{measurement_id} -> {new_id} fields={sorted(body.patch)}"},
        )
        return {
            "measurement": corrected,
            "superseded_measurement_id": measurement_id,
            "supersession_id": supersession_id,
        }

    def _why_not_correctable(self, conn: Connection, measurement_id: int) -> str:
        """Turn "absent from the active view" into a sentence.

        The view cannot say why a row is missing from it, so this reads the
        two things that can: the supersession side table, and the batch's own
        status. Neither re-implements the predicate -- one is the evidence
        table, the other is a status compared in Python.
        """
        row = repo.find_any(conn, measurement_id)
        if row is None:  # pragma: no cover - the existence check already ran
            raise MeasurementNotFound(f"No measurement {measurement_id}.")

        retired = repo.supersession_of(conn, measurement_id)
        if retired:
            replacement = retired["superseded_by_measurement_id"]
            return (
                f"measurement {measurement_id} was already retired on "
                f"{retired['occurred_at']:%Y-%m-%d %H:%M:%S%z}"
                + (f" and replaced by measurement {replacement}" if replacement else "")
                + f". Reason: {retired['reason']}. Correct the row that "
                f"replaced it, not this one -- a retirement is recorded once "
                f"and cannot be withdrawn."
            )

        if row["batch_status"] != batches.STATUS_COMMITTED:
            return (
                f"measurement {measurement_id} belongs to batch "
                f"{row['load_id']}, which is {row['batch_status']}. Only a "
                f"measurement from a committed batch is current, so there is "
                f"nothing to correct yet."
            )

        # Not retired, batch committed, still absent: the remaining reason the
        # active view can exclude a row is the duplicate flag ingest sets.
        return (
            f"measurement {measurement_id} is in batch {row['load_id']} but is "
            f"not a current reading -- ingest recorded it as a duplicate of "
            f"another row for the same vehicle and checkzone. Correct the row "
            f"that was kept."
        )

    # -----------------------------------------------------------------
    def supersede_batch(
        self,
        conn: Connection,
        load_id: int,
        body: SupersedeCreate,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Retire a committed batch. One column changes; no fact moves.

        This is not a bulk correction. It writes **no**
        `measurement_supersession` rows, because retiring a batch does not
        claim that each of its readings was replaced by a better one -- it
        claims the batch should not have been published. The active-data
        predicate already tests the batch's status, so the rows stop being
        read the moment the status changes (`01-DATA-MODEL.md` §5).
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise BatchNotFound(f"No batch {load_id}.")

        previous = batch["status"]
        if previous != batches.STATUS_COMMITTED:
            raise BatchNotSupersedable(
                f"batch {load_id} is {previous}, not {batches.STATUS_COMMITTED}"
                + (
                    ". It is already retired; a batch is superseded once."
                    if previous == STATUS_SUPERSEDED
                    else ". Only a batch whose rows are being read as current can "
                         "be retired -- one that never committed has no facts in "
                         "production, and cancelling or re-parsing it is a "
                         "different route."
                )
            )

        replacement = self._checked_replacement(conn, batch, body.replacement_load_id)
        hidden = repo.count_rows_for_batch(conn, load_id)

        repo.supersede_batch(
            conn, load_id, status=STATUS_SUPERSEDED, superseded_by=replacement
        )
        audit.record(
            conn,
            action="batch.supersede",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before={"status": previous, "superseded_by": batch["superseded_by"]},
            after={
                "status": STATUS_SUPERSEDED,
                "superseded_by": replacement,
                "reason": body.reason.strip(),
                "measurements_hidden": hidden,
            },
            correlation_id=correlation_id,
        )
        log.info(
            "batch superseded",
            extra={"detail": f"load_id={load_id} rows={hidden} replacement={replacement}"},
        )
        return {
            "load_id": load_id,
            "status": STATUS_SUPERSEDED,
            "previous_status": previous,
            "superseded_by": replacement,
            "reason": body.reason.strip(),
            "measurements_hidden": hidden,
        }

    # -----------------------------------------------------------------
    def abandon_batch(
        self,
        conn: Connection,
        load_id: int,
        body: AbandonCreate,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Remove a sheet that never became measurements from review (T21).

        The pre-commit sibling of `supersede_batch`, and deliberately beside
        it rather than in `services/ingest.py`: nothing the parser does can
        end a batch's review, the same way nothing it does can retire one.

        Refusals, in the order that makes the answer true:

        1. no such batch -> 404;
        2. **any `wavescan` row** -> 409, whatever the status says. The row
           count is the thing itself; a status is a column somebody could
           have got wrong, and an abandoned batch with facts would be a
           silent retirement nobody chose;
        3. COMMITTED -> 409, pointing at supersede;
        4. RUNNING, ABANDONED, SUPERSEDED -> 409.

        Allowed from PENDING_REVIEW, REJECTED_TEMPLATE and FAILED. The status
        and the `audit_event` are written in the caller's one transaction;
        nothing else changes.
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise BatchNotFound(f"No batch {load_id}.")

        previous = batch["status"]
        facts = batches.count_facts(conn, load_id)
        if facts:
            raise BatchNotAbandonable(
                f"batch {load_id} is {previous} and has {facts} wavescan "
                f"row(s). A batch that produced measurements is never "
                f"abandoned; retire it with POST /api/v1/batches/{load_id}/"
                f"supersede and a reason. Nothing was changed."
            )
        if previous not in ABANDONABLE_STATUSES:
            if previous == batches.STATUS_COMMITTED:
                why = (
                    "It is committed, so its rows are current measurements: "
                    f"retire it with POST /api/v1/batches/{load_id}/supersede "
                    "and a reason instead."
                )
            elif previous == batches.STATUS_RUNNING:
                why = "It is still being parsed; wait for the worker to finish."
            else:
                why = "It has already left the review queue."
            raise BatchNotAbandonable(
                f"batch {load_id} is {previous}, so it cannot be abandoned. "
                f"{why} Nothing was changed."
            )

        repo.abandon_batch(conn, load_id, status=batches.STATUS_ABANDONED)
        audit.record(
            conn,
            action="batch.abandon",
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before={"status": previous},
            after={
                "status": batches.STATUS_ABANDONED,
                "reason": body.reason.strip(),
                "file_hash": str(batch["file_hash"]).strip(),
                "review_revision": (
                    str(batch["review_revision"]).strip()
                    if batch["review_revision"] else None
                ),
            },
            correlation_id=correlation_id,
        )
        log.info("batch abandoned", extra={"detail": f"load_id={load_id} from={previous}"})
        return {
            "load_id": load_id,
            "status": batches.STATUS_ABANDONED,
            "previous_status": previous,
            "reason": body.reason.strip(),
        }

    # -----------------------------------------------------------------
    def restore_batch(
        self,
        conn: Connection,
        load_id: int,
        body: RestoreCreate,
        *,
        actor_user_id: str,
        correlation_id: str | None = None,
    ) -> dict:
        """Bring one ABANDONED or SUPERSEDED sheet back (T25).

        The reverse of `abandon_batch` and `supersede_batch`, and beside them
        for the same reason: ending or resuming a batch's life is a decision
        with a reason and an actor, never a side effect of parsing. Two doors
        reach it -- `POST /api/v1/batches/{load_id}/restore` and an
        identical-bytes `POST /uploads` -- and both are this method.

        * From `SUPERSEDED` -> `COMMITTED`, `superseded_by` cleared, audit
          `batch.restore`. Its `wavescan` rows were never touched; they read
          as current again because `v_wavescan_active` tests the batch's
          status. Nothing is re-inserted.
        * From `ABANDONED` -> the `before.status` of the latest
          `batch.abandon` audit event (`PENDING_REVIEW`, `REJECTED_TEMPLATE`
          or `FAILED`), or `PENDING_REVIEW` if that event is missing. Audit
          `batch.reopen`. It still has zero `wavescan` rows, and a test says
          so.
        * Anything else -> 409. Missing -> 404.

        `load_batch.status` (and `superseded_by`) plus one `audit_event`, in
        the caller's one transaction. No `wavescan` statement of any kind.

        The role check is the caller's: the restore route is Admin, and the
        upload route only reaches this for a SUPERSEDED sheet when the caller
        is an Admin (T25 locked decision 5).
        """
        batch = batches.get_batch_for_update(conn, load_id)
        if batch is None:
            raise BatchNotFound(f"No batch {load_id}.")

        previous = batch["status"]
        if previous not in RESTORABLE_STATUSES:
            raise BatchNotRestorable(
                f"batch {load_id} is {previous}, so there is nothing to "
                f"restore. Only an ABANDONED or SUPERSEDED batch can be "
                f"brought back. Nothing was changed."
            )

        reason = body.reason.strip()
        if previous == STATUS_SUPERSEDED:
            target = batches.STATUS_COMMITTED
            action = "batch.restore"
            repo.restore_batch(conn, load_id, status=target, clear_superseded_by=True)
        else:
            facts = batches.count_facts(conn, load_id)
            if facts:  # pragma: no cover - abandon refuses a batch with facts
                raise BatchNotRestorable(
                    f"batch {load_id} is ABANDONED but owns {facts} wavescan "
                    f"row(s), which abandon never allows. Refusing to reopen "
                    f"it until somebody explains how. Nothing was changed."
                )
            target = self._status_before_abandon(conn, load_id)
            action = "batch.reopen"
            repo.restore_batch(conn, load_id, status=target, clear_superseded_by=False)

        visible = repo.count_rows_for_batch(conn, load_id)
        audit.record(
            conn,
            action=action,
            entity_type="load_batch",
            entity_id=load_id,
            actor_user_id=actor_user_id,
            before={"status": previous, "superseded_by": batch["superseded_by"]},
            after={
                "status": target,
                "superseded_by": None,
                "reason": reason,
                "file_hash": str(batch["file_hash"]).strip(),
                "wavescan_rows": visible,
            },
            correlation_id=correlation_id,
        )
        log.info(
            "batch restored",
            extra={"detail": f"load_id={load_id} {previous}->{target} via {action}"},
        )
        return {
            "load_id": load_id,
            "status": target,
            "previous_status": previous,
            "reason": reason,
            "audit_action": action,
        }

    def _status_before_abandon(self, conn: Connection, load_id: int) -> str:
        """Where an abandoned sheet was when it was abandoned.

        Read from the latest `batch.abandon` audit event rather than a new
        column: that event is already the record of the transition. A value
        outside the three statuses abandon allows -- or no event at all -- is
        answered with PENDING_REVIEW, the one status from which every review
        action is still available.
        """
        event = audit.latest_action(conn, "load_batch", load_id, "batch.abandon")
        before = (event or {}).get("before") or {}
        status = before.get("status") if isinstance(before, dict) else None
        if status in ABANDONABLE_STATUSES:
            return status
        return batches.STATUS_PENDING_REVIEW

    def _checked_replacement(
        self, conn: Connection, batch: dict, replacement_load_id: int | None
    ) -> int | None:
        """A replacement must be a real, committed batch for the same plant.

        Pointing at a batch that was never committed, or at another plant's,
        would leave `superseded_by` naming something a reader cannot use --
        worse than leaving it null, because it looks like an answer.
        """
        if replacement_load_id is None:
            return None
        if replacement_load_id == batch["load_id"]:
            raise BatchNotSupersedable(
                f"batch {batch['load_id']} cannot replace itself."
            )

        other = batches.get_batch(conn, replacement_load_id)
        if other is None:
            raise BatchNotSupersedable(
                f"replacement_load_id {replacement_load_id} does not exist."
            )
        if other["status"] != batches.STATUS_COMMITTED:
            raise BatchNotSupersedable(
                f"batch {replacement_load_id} is {other['status']}, so it "
                f"cannot replace batch {batch['load_id']}. A replacement has "
                f"to be readable as current."
            )
        if other["plant_code"] != batch["plant_code"]:
            raise BatchNotSupersedable(
                f"batch {replacement_load_id} belongs to plant "
                f"{other['plant_code'] or '(none)'} and batch "
                f"{batch['load_id']} to {batch['plant_code'] or '(none)'}. A "
                f"batch is replaced by another send of the same plant's data."
            )
        return replacement_load_id
