"""`audit_event`: append-only, written in the same transaction as the change.

`AGENTS.md` §2 and `01-DATA-MODEL.md` §6.2. No role holds UPDATE or DELETE on
this table -- not the application, not the migrator -- so the only way an
audit row can be wrong is if it is never written. That is why `record()`
takes the same connection as the mutation and is called inside its
transaction, never after it.
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, text

ACTOR_USER = "user"
ACTOR_SYSTEM = "system"


def record(
    conn: Connection,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int,
    actor_user_id: str | None,
    actor_type: str = ACTOR_USER,
    before: dict | None = None,
    after: dict | None = None,
    correlation_id: str | None = None,
) -> int:
    """Write one audit row. Returns its id so a caller can assert on it."""
    return int(
        conn.execute(
            text(
                """
                INSERT INTO audit_event
                    (actor_user_id, actor_type, action, entity_type, entity_id,
                     before, after, correlation_id)
                VALUES (:actor_user_id, :actor_type, :action, :entity_type,
                        :entity_id, CAST(:before AS jsonb), CAST(:after AS jsonb),
                        :correlation_id)
                RETURNING id
                """
            ),
            {
                "actor_user_id": actor_user_id,
                "actor_type": actor_type,
                "action": action,
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "before": json.dumps(before, default=str) if before else None,
                "after": json.dumps(after, default=str) if after else None,
                "correlation_id": correlation_id,
            },
        ).scalar_one()
    )


def for_entity(conn: Connection, entity_type: str, entity_id: str | int) -> list[dict]:
    rows = conn.execute(
        text(
            "SELECT id, occurred_at, actor_user_id, actor_type, action, "
            "       entity_type, entity_id, before, after, correlation_id "
            "FROM audit_event WHERE entity_type = :t AND entity_id = :i "
            "ORDER BY id"
        ),
        {"t": entity_type, "i": str(entity_id)},
    ).mappings().all()
    return [dict(r) for r in rows]


def latest_action(
    conn: Connection, entity_type: str, entity_id: str | int, action: str
) -> dict | None:
    """The most recent audit row of one action for one entity, or None.

    T25 reads the latest `batch.abandon` to learn which status an abandoned
    sheet left from, so reopening it returns it to where it was rather than
    to a guess. The audit row is the only place that fact is kept; a new
    column would be a second copy of it.
    """
    row = conn.execute(
        text(
            "SELECT id, occurred_at, actor_user_id, action, before, after "
            "FROM audit_event "
            "WHERE entity_type = :t AND entity_id = :i AND action = :a "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"t": entity_type, "i": str(entity_id), "a": action},
    ).mappings().first()
    return dict(row) if row else None
