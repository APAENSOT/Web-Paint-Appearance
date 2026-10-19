"""T115 (D-115-4): Attach reloads the sheets a Removed model held.

"Remove from <plant>" holds every new Wave Scan and Film row of that model as
`MODEL_NOT_OFFERED` (`domain/cleaner.py`, `domain/film.py`). Uploading the
same file again is refused while its batch is live, so before T115 the only
way back after an Attach was Abandon, then upload again.

Now the Attach request itself reloads them: every batch at the plant that is
replayable, has no facts and holds a `MODEL_NOT_OFFERED` row
(`repositories.batches.held_for_model_offer`) goes back through
`IngestService.replay_batch` -- the stored bytes, the one pipeline, never a
commit. The same rule template publish replays by (`services/ingest.py`). A
batch also held for something else re-derives and stays held for that.

ADR 0005: nothing here updates or deletes a fact, an upload or a batch; a
replay refuses a batch with facts by itself.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from app.repositories import batches
from app.services.ingest import IngestError, IngestService

log = logging.getLogger(__name__)


def reload_held(
    conn: Connection,
    ingest: IngestService,
    *,
    plants: list[str],
    model_code: str,
    actor_user_id: str,
    correlation_id: str | None,
) -> dict:
    """Replay this plant's model-held batches; one refusal never undoes the Attach."""
    reloaded: list[int] = []
    refused: list[dict] = []
    for plant in plants:
        reason = f"model {model_code} attached at {plant}"
        for load_id in batches.held_for_model_offer(conn, plant):
            try:
                ingest.replay_batch(
                    conn, load_id,
                    actor_user_id=actor_user_id,
                    reason=reason,
                    correlation_id=correlation_id,
                )
            except IngestError as exc:
                # The publish pattern: the decision stands, the batch stays
                # exactly where it was, and the response says which and why.
                log.info(
                    "batch not reloaded after attach",
                    extra={"detail": f"load_id={load_id}: {exc}"},
                )
                refused.append({"load_id": load_id, "reason": str(exc)})
                continue
            reloaded.append(load_id)
    return {"reloaded_load_ids": reloaded, "reload_refused": refused}
