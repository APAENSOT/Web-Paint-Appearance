# `backend/tests/sql/`

## `99_verify_demo_baseline.sql`

A byte-identical copy of
`Paint Appearance/Component/Database/sql/99_verify.sql`, taken at T01
(copied under the T01 task's exception; the vault itself stays read-only).

It is kept **unmodified, as a baseline for diffing**, not as the suite CI
runs. The live suite is `backend/tests/test_schema_constraints.py`, which
ports tests 1-13 to pytest, and `backend/tests/test_t01_security.py`,
which adds the three T01 cases (DELETE `wavescan` refused, DELETE
`load_batch` refused, INSERT `audit_event` accepted).

Three things differ deliberately in the port, and a reviewer diffing the
two files should expect them:

1. **Principal.** The original runs as `postgres`. The port runs as the
   *application* role, because "what can the application do" is the
   question T01 answers.
2. **Cleanup.** The original's tests 10 and 11 end with
   `DELETE FROM wavescan WHERE ...`. After T01 the application role has
   no `DELETE`, so the port relies on the `app_conn` fixture rolling its
   transaction back instead.
3. **Test 11** (NULL `serial_no` accepted at DB level) is not ported.
   It documents a Phase-1 relaxation of the demo schema, and
   `01-DATA-MODEL.md` section 5 keeps `serial_no ... NOT NULL`; T02 owns
   that column's final shape, so asserting either way here would pin a
   decision T01 does not own.

`purge_stg_raw()` is still present in the schema but `EXECUTE` on it has
been revoked from `PUBLIC` (migration 0001), so no application role can
call it.
