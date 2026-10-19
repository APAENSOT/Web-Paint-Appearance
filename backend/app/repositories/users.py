"""`app_user`: one row per authenticated person.

T01 granted the application `SELECT` here and withheld `INSERT` "until T04
implements the OIDC first-login flow that would need it". This is that flow's
storage half, and revision `0003` is the grant.

Roles are **not** stored. They come from the token (or the development
bypass) at request time, so they cannot drift from what the identity provider
says (`01-DATA-MODEL.md` §6.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text


def upsert(
    conn: Connection,
    *,
    entra_oid: str,
    upn: str,
    display_name: str,
) -> str:
    """Return the ``app_user.id`` for this identity, creating it if new.

    ``entra_oid`` is the key, not the UPN: a person's sign-in name changes
    when they marry or move country, and the object id does not. The UPN and
    display name are refreshed on every sign-in for exactly that reason --
    those three columns are the only ones the application may update.

    There is no DELETE, here or in the grant. An identity that has attributed
    a batch or an audit event has to stay resolvable.
    """
    row = conn.execute(
        text(
            """
            INSERT INTO app_user (id, entra_oid, upn, display_name, last_seen_at)
            VALUES (:id, :entra_oid, :upn, :display_name, now())
            ON CONFLICT (entra_oid) DO UPDATE
               SET upn = EXCLUDED.upn,
                   display_name = EXCLUDED.display_name,
                   last_seen_at = now()
            RETURNING id
            """
        ),
        {
            "id": uuid.uuid4(),
            "entra_oid": entra_oid,
            "upn": upn,
            "display_name": display_name,
        },
    ).scalar_one()
    return str(row)


def get_by_id(conn: Connection, user_id: str) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, entra_oid, upn, display_name, created_at, last_seen_at "
            "FROM app_user WHERE id = :id"
        ),
        {"id": user_id},
    ).mappings().first()
    return dict(row) if row else None
