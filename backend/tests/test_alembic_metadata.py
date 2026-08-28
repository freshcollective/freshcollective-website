"""Regression tests for Alembic ``target_metadata`` completeness.

``backend/alembic/env.py`` explicitly imports each model module so that
its tables are registered on ``Base.metadata`` and Alembic can compare
the live schema against the declared metadata during
``alembic check`` / ``alembic revision --autogenerate``.

When a model module is *not* imported, Alembic sees the DB table as
"removed" and suggests dropping it. Historically this happened to
``AccessGrantRecord`` (FIP3 grant log, created by migration 119): the
runtime worked because service code imported the model directly, but
Alembic's env-time scan missed it and flagged
``access_grant_records`` as drift.

This test guards against a recurrence by executing the exact model
imports listed in ``env.py`` and asserting a representative set of
actively-used tables ends up in ``Base.metadata``. If it fails, the
likely fix is a missing ``import app.models.<module>`` line in
``backend/alembic/env.py``.

See ``backend/docs/db/known-legacy-schema-drift.md`` for context on
the (separate) legacy tables that remain in the DB without a matching
model.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parent.parent / "alembic" / "env.py"


def _model_modules_imported_by_env() -> list[str]:
    """Return the ``app.*`` module paths ``env.py`` imports for metadata."""
    text = ENV_PATH.read_text()
    # Match lines like `import app.models.access_grant_record  # noqa: F401 …`
    # and `import app.comms.models  # noqa: F401 …`.
    pattern = re.compile(r"^\s*import\s+(app\.[\w\.]+)", re.MULTILINE)
    return pattern.findall(text)


def test_alembic_target_metadata_includes_active_tables() -> None:
    """Actively-used tables must be present in ``Base.metadata``.

    ``AccessGrantRecord`` was previously omitted from ``env.py``'s
    import chain, causing ``alembic check`` to suggest dropping
    ``access_grant_records``.
    """
    # Execute the same import side effects Alembic does at env-load
    # time. If a module is missing from env.py, the corresponding
    # table will not appear in ``Base.metadata`` and this test fails.
    for module_name in _model_modules_imported_by_env():
        importlib.import_module(module_name)

    from app.db.base import Base

    tables = set(Base.metadata.tables.keys())
    required = {
        "users",
        "payment_transactions",
        "pathway_entitlements",
        "access_grant_records",
    }
    missing = required - tables
    assert not missing, (
        f"Alembic target metadata missing tables: {missing}. "
        "A model module is probably not imported in backend/alembic/env.py."
    )
