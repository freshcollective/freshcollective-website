# Known legacy schema drift

The Alembic chain currently reflects the *active* application model, but
several tables from removed features still exist in production Postgres
because no explicit drop migration was authored at removal time. As a
result, `alembic check` (and `alembic revision --autogenerate`) will
consistently report these tables as "removed" — i.e. present in the DB
but absent from `Base.metadata`.

Until a dedicated cleanup milestone drops them (with the usual review of
each table's residual data), this drift is **accepted**.

## Accepted legacy tables

The following tables persist in the DB but are no longer part of the
active data model:

- `world_guide_documents`
- `world_guide_versions`
- `world_guide_acceptances`
- `direct_messages`
- `message_threads`

## Operational implications

- `alembic check` will exit non-zero with `op.drop_table` entries for
  each of the above. That specific drift is expected. Any *other*
  structural drift is not — investigate before merging.
- If you run `alembic revision --autogenerate`, review the generated
  script and **delete** any `op.drop_table` calls for the tables above
  before applying. Do not let an unrelated migration accidentally drop
  them.
- Representation-only drift (TEXT vs VARCHAR, TIMESTAMP precision, index
  naming conventions) is also expected on this chain and separately
  accepted.

## Historical note

`access_grant_records` was previously on this list. That entry was
resolved during the Alembic-chain repair milestone: it turned out to be
a metadata-import gap (its model module was missing from
`backend/alembic/env.py`), not a dead table. See `AccessGrantRecord`
in `app/models/access_grant_record.py` and the regression test in
`backend/tests/test_alembic_metadata.py`.
