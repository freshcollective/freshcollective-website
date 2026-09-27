"""Which PostgreSQL driver our URL shape selects.

A production pre-deploy died on ``ModuleNotFoundError: No module named
'psycopg'`` while the running image, built nine days earlier from the
same source, kept serving. Nothing in this repository had changed — not
the URL, not the Python version, not a line of application code.

SQLAlchemy 2.1.0 changed the default DBAPI for a plain ``postgresql://``
URL from psycopg2 to psycopg (v3). ``requirements.txt`` asked for
``sqlalchemy>=2.0.0`` with no ceiling, so the first fresh build after
2.1.0 was published resolved 2.1.1 and asked for a driver this project
has never declared. Render's fc-db hands us exactly that URL shape.

These tests are deliberately independent of ``DATABASE_URL``: they assert
on a representative literal URL, so they hold in CI, on a laptop, and in
a container regardless of what environment happens to be present. What
they pin is the *decision* — given our declared dependency set, a plain
PostgreSQL URL must resolve to psycopg2, and that driver must actually be
importable.

If SQLAlchemy is deliberately moved to 2.1+ and psycopg3 adopted, these
are the tests to change, and changing them should be a conscious act
rather than a surprise at a production pre-deploy.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine.url import make_url

#: Exactly the shape Render's ``fc-db.connectionString`` produces — no
#: ``+driver`` qualifier, which is what makes the default consequential.
PLAIN_PG_URL = "postgresql://fc_user:secret@dpg-example.singapore-postgres.render.com:5432/fc_db"

EXPECTED_DRIVER = "psycopg2"


class TestThePlainUrlResolvesToPsycopg2:
    def test_the_driver_name_is_psycopg2(self):
        """The regression, in one assertion. On SQLAlchemy 2.1 this
        returns 'psycopg' and the pre-deploy dies."""
        assert make_url(PLAIN_PG_URL).get_driver_name() == EXPECTED_DRIVER

    def test_the_dialect_module_is_the_psycopg2_one(self):
        dialect = make_url(PLAIN_PG_URL).get_dialect()
        assert dialect.__module__ == "sqlalchemy.dialects.postgresql.psycopg2"

    def test_the_selected_driver_is_actually_importable(self):
        """A driver the URL selects but nobody installed is the failure
        this whole file exists for. Asserting the name alone would have
        passed in the broken build."""
        dialect = make_url(PLAIN_PG_URL).get_dialect()
        dbapi = dialect.import_dbapi()  # raises ModuleNotFoundError if absent
        assert dbapi is not None

    @pytest.mark.parametrize("url", [
        "postgresql://u:p@h/db",
        "postgresql://u:p@h:5432/db",
        "postgresql://u@h/db",
        "postgresql://u:p@h/db?sslmode=require",
    ])
    def test_every_plain_variant_resolves_the_same_way(self, url):
        """Render's connection string has carried a port and an sslmode at
        different times; the driver must not depend on which."""
        assert make_url(url).get_driver_name() == EXPECTED_DRIVER


class TestTheDependencyCeilingIsPresent:
    def test_sqlalchemy_is_on_the_2_0_line(self):
        """The pin is what makes the tests above true. Without it a fresh
        install resolves 2.1.x and the driver silently changes."""
        import sqlalchemy

        major, minor = (int(p) for p in sqlalchemy.__version__.split(".")[:2])
        assert (major, minor) == (2, 0), (
            f"SQLAlchemy {sqlalchemy.__version__} — the plain-URL default "
            "driver changed in 2.1; see requirements.txt"
        )

    def test_requirements_declares_the_ceiling(self):
        """Pinned in the file, not merely true of whatever is installed —
        the production failure was a *fresh install* resolving differently
        from the running image."""
        from pathlib import Path

        requirements = (
            Path(__file__).resolve().parent.parent / "requirements.txt"
        ).read_text()
        line = next(
            ln for ln in requirements.splitlines()
            if ln.strip().lower().startswith("sqlalchemy")
        )
        assert "<2.1" in line, f"no upper bound on SQLAlchemy: {line!r}"


class TestAnExplicitDriverStillWins:
    def test_an_explicit_psycopg2_url_is_unaffected(self):
        assert make_url("postgresql+psycopg2://u:p@h/db").get_driver_name() == "psycopg2"

    def test_asking_for_psycopg3_explicitly_still_means_psycopg3(self):
        """The cap constrains the *default*, not the ability to choose. A
        future migration sets ``+psycopg`` and declares the dependency."""
        assert make_url("postgresql+psycopg://u:p@h/db").get_driver_name() == "psycopg"
