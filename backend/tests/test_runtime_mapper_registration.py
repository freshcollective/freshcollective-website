"""Regression guard: SQLAlchemy mapper registration must not
depend on test-suite import side effects.

Backstory
---------
B1 added ``PaymentOption.grants = relationship("PaymentOptionGrant", ...)``.
SQLAlchemy resolves that string at first mapper-configuration time,
i.e. the first query against *any* mapped class in the registry.

The test suite's conftest happens to import ``PaymentOptionGrant``
early (through several routes), so every test session had the
class registered by the time queries ran — the whole suite passed.
But in production, the first ``db.query(User)`` at login triggered
the whole-registry configure, which needed ``PaymentOptionGrant``
resolvable and failed with:

    InvalidRequestError: When initializing mapper Mapper[PaymentOption],
    expression 'PaymentOptionGrant.position,PaymentOptionGrant.created_at'
    failed to locate a name ("name 'PaymentOptionGrant' is not defined").

Login returned 500; the browser rendered "Unable to connect to the
server." The bug was latent from B1 and only surfaced in a fresh
Python process that mirrored uvicorn's import chain.

What this test does
-------------------
Spawns a fresh Python interpreter that imports only the normal
FastAPI runtime entry point (``app.main``) plus what a route
naturally touches (``PaymentOption`` and ``User``), then performs
the equivalent of a login-time query. If any relationship target
is missing from the runtime import chain, the subprocess exits
non-zero and this test surfaces the captured stderr.

The subprocess deliberately does NOT import
``app.models.payment_option_grant`` explicitly. Doing so would
recreate the exact conftest-side-effect condition that hid the
original bug.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_fresh_runtime_can_configure_mappers_via_first_query():
    """Fresh Python process → import FastAPI app → open a session →
    query a mapped model. This is the same code path uvicorn walks
    when a login request lands.

    A missing runtime relationship-target registration would fail
    inside SQLAlchemy's ``_configure_registries`` on the first
    query. We assert the subprocess exits 0 and prints ``OK``.
    """
    code = textwrap.dedent(
        """
        # Mimic uvicorn's ``app.main:app`` import; this pulls in every
        # router and every model any router touches. If a route
        # imports PaymentOption but not PaymentOptionGrant, and no
        # other module registers PaymentOptionGrant either, the
        # mapper string-reference will not resolve on first query.
        from app.main import app  # noqa: F401

        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.payment_option import PaymentOption

        with SessionLocal() as db:
            # First mapped-model query triggers a registry-wide
            # mapper configuration. This is what login hits.
            db.query(User).first()

            # Then explicitly resolve the specific relationship the
            # regression involved. Touching ``.grants`` exercises
            # the loader (selectin), which also needs the target
            # class registered.
            first_option = db.query(PaymentOption).first()
            if first_option is not None:
                _ = list(first_option.grants)

        print("OK")
        """
    ).strip()

    # Pass the parent test process's environment through so the
    # subprocess sees the test DATABASE_URL that conftest configured.
    # ``PYTHONDONTWRITEBYTECODE`` keeps the test tree tidy.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise AssertionError(
            "Fresh-runtime mapper configuration failed.\n"
            "This normally means a SQLAlchemy string-referenced "
            "relationship target is not being imported through the "
            "normal FastAPI runtime path.\n\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    assert "OK" in result.stdout, (
        f"Subprocess ran clean but did not print OK.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
