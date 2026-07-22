# Fresh Collective — backend test scaffold

Scope: **standalone paid Gathering ticket flow only** (Stage 2 rollout).
Not a general-purpose test suite for the whole app.

## Prerequisites

- Local PostgreSQL, same server that hosts `fc_prod`.
- A `fc_test` database owned by the same role that runs the app locally
  (`lindsey`). One-time setup:
  ```
  sudo -u postgres psql -c "ALTER USER lindsey CREATEDB;"
  createdb -U lindsey fc_test        # peer-auth over unix socket
  ```
- `pytest` installed into `backend/.venv`:
  ```
  .venv/bin/pip install pytest
  ```

## Environment variables

- `TEST_DATABASE_URL` — full postgres URL for the test DB. Optional;
  if unset, `conftest.py` derives it from `DATABASE_URL` by swapping
  the database name to `fc_test`.

## Running

From `backend/`:

```
.venv/bin/pytest                      # everything
.venv/bin/pytest tests/test_holds.py  # a single file
.venv/bin/pytest -m concurrency       # only concurrent-transaction tests
.venv/bin/pytest -v                   # verbose
```

## What this scaffold does not do

- Does not touch `fc_prod`.
- Does not use SQLite for anything that involves row locking, CHECK
  constraints, PostgreSQL enums, `NOW()` intervals or serialisable
  transactions — those are load-bearing for the feature.
- Does not mock Stripe with a full-fidelity harness. Stripe is
  minimally stubbed via `unittest.mock` so we can drive fulfilment
  without hitting Stripe's servers.

## Test file map

- `conftest.py` — shared fixtures: engine, transactional session, factories
- `test_migration_080.py` — schema-level assertions (columns, enum values,
  CHECK constraint)
- `test_ticket_price_validation.py` — Pydantic + service-layer validation
- `test_hold_model.py` — hold lifecycle: create, expire, confirm, cancel
- `test_capacity_with_holds.py` — capacity math respects active holds and
  ignores expired ones
- `test_hold_uniqueness.py` — one hold per user per event
- `test_concurrent_last_seat.py` (`@pytest.mark.concurrency`) — two
  workers race for the final place; only one hold survives
- `test_webhook_fulfilment.py` — (Stage 2B) idempotent conversion + AccessPass
- `test_access_scope.py` — (Stage 2B) paid ticket unlocks only the purchased
  event, not other Collective content
