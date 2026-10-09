"""``app.core.config`` must be importable on its own, cold.

The failure these exist for
---------------------------
A boot validator in ``config`` reached for URL policy that lived in
``app.core.public_url``, and ``public_url`` imported ``settings`` back
from ``config`` at module scope. Importing ``config`` therefore ran::

    config  →  Settings()  →  _check_public_app_url
            →  app.core.public_url
            →  from app.core.config import settings   # still executing
            →  ImportError: cannot import name 'settings' from
               partially initialized module 'app.core.config'

It aborted ``alembic upgrade head`` in pre-deploy, so the deploy failed
and the previous image kept serving.

Why the whole test suite passed anyway
--------------------------------------
The validator only reaches that import when ``app_env == "production"``.
No test process boots cold in production mode — the boot-guard tests
construct ``Settings(app_env="production")`` *after* the test module has
already imported ``app.core.public_url``, so the import came from
``sys.modules`` and succeeded. Every in-process test was blind to it by
construction.

So the tests here are of two kinds, and both are necessary:

  * **cold subprocesses**, because the bug only exists on a first
    import and nothing in-process can see it;
  * **AST checks** on the import graph, because they are fast, run on
    every suite, and state the invariant directly rather than probing
    for its absence.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_core_import_graph.py
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import tempfile
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

PUBLIC = "https://freshcollective.au"
RENDER_HOST = "https://fc-web-q950.onrender.com"

#: The shape of a production process, minus anything inherited. Built
#: from nothing so an ambient ``APP_ENV`` or a stray ``.env`` in the
#: developer's shell cannot make these pass by accident.
PRODUCTION_ENV = {
    "PATH": "/usr/bin:/bin",
    "APP_ENV": "production",
    "PUBLIC_APP_URL": PUBLIC,
    "FRONTEND_ORIGIN": RENDER_HOST,
    "DATABASE_URL": "postgresql://u:p@localhost/db",
    "JWT_SECRET": "x" * 32,
    "FC_SERVICE_ROLE": "job",
    "FC_JOB_REQUIRES_STRIPE": "false",
}


#: An empty directory to run cold subprocesses from.
#:
#: ``Settings.model_config`` sets ``env_file=".env"``, which pydantic
#: resolves against the *working directory*. Running from the backend
#: root therefore read the developer's ``backend/.env`` — so these
#: tests inherited a ``sk_test_…`` Stripe key, and every cold import
#: with ``APP_ENV=production`` died on the Stripe guard instead of
#: reaching the behaviour under test. All seven failed on any machine
#: with a local ``.env``, and passed only where none existed.
#:
#: Running from an empty directory makes the docstring below true
#: rather than aspirational: ``app`` is found through ``PYTHONPATH``,
#: and there is no ``.env`` beside the process to find.
_COLD_CWD = tempfile.mkdtemp(prefix="fc-cold-import-")


def _cold(code: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a snippet in a brand-new interpreter with a minimal env.

    ``app`` resolves through ``PYTHONPATH`` rather than ``cwd``, and the
    working directory is empty, so no ``.env`` is read: ``Settings``
    receives exactly what the test puts in ``env`` and nothing else.
    """
    resolved = {**(env if env is not None else PRODUCTION_ENV)}
    resolved["PYTHONPATH"] = str(BACKEND)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_COLD_CWD,
        env=resolved,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_no_circular_import(result: subprocess.CompletedProcess) -> None:
    combined = result.stdout + result.stderr
    assert "partially initialized module" not in combined, combined
    assert "circular import" not in combined.lower(), combined
    assert result.returncode == 0, combined


# ---------------------------------------------------------------------------
# Cold imports — the production path, exercised the way production does
# ---------------------------------------------------------------------------


class TestColdImports:
    def test_importing_config_succeeds(self):
        """(1) The exact statement that failed in pre-deploy."""
        result = _cold("import app.core.config; print('ok')")
        _assert_no_circular_import(result)
        assert "ok" in result.stdout

    def test_importing_settings_from_config_succeeds(self):
        """(2) The form every caller actually uses."""
        result = _cold(
            "from app.core.config import settings\n"
            "print(settings.resolved_public_app_url)"
        )
        _assert_no_circular_import(result)
        assert PUBLIC in result.stdout

    def test_importing_public_url_first_succeeds(self):
        """(3) The other direction, with nothing loaded before it.

        ``public_url`` reading ``config`` is fine — that edge was never
        the problem. The cycle only existed because ``config`` reached
        back the other way.
        """
        result = _cold(
            "import app.core.public_url as p\n"
            "print(p.public_app_url('/reset-password?token=X'))"
        )
        _assert_no_circular_import(result)
        assert f"{PUBLIC}/reset-password?token=X" in result.stdout

    def test_the_policy_module_imports_with_no_configuration_at_all(self):
        """The leaf, proved to be a leaf.

        No ``DATABASE_URL``, no ``JWT_SECRET``, no environment to speak
        of — it must still import, because ``config`` depends on it
        while being constructed.
        """
        result = _cold(
            "import app.core.url_policy as u\n"
            "print(u.join_public_url('https://freshcollective.au/', "
            "'/reset-password?token=X'))",
            env={"PATH": "/usr/bin:/bin"},
        )
        _assert_no_circular_import(result)
        assert f"{PUBLIC}/reset-password?token=X" in result.stdout

    def test_importing_the_app_succeeds(self):
        """The start command's first act, cold, in production mode."""
        result = _cold(
            "from app.main import app\nprint('routes', len(app.routes))"
        )
        _assert_no_circular_import(result)
        assert "routes" in result.stdout

    def test_the_production_guard_still_fires_on_a_cold_import(self):
        """(5) The behaviour must survive the restructuring.

        Checked cold rather than in-process, because the in-process
        version of this test is exactly the one that was satisfied by
        ``sys.modules`` while production failed.
        """
        env = {k: v for k, v in PRODUCTION_ENV.items() if k != "PUBLIC_APP_URL"}
        result = _cold("import app.core.config", env=env)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        # The *intended* refusal, not an import error.
        assert "PUBLIC_APP_URL" in combined, combined
        assert "onrender.com" in combined, combined
        assert "partially initialized module" not in combined, combined
        assert "ImportError" not in combined, combined

    def test_a_platform_host_in_public_app_url_itself_is_refused_cold(self):
        env = {**PRODUCTION_ENV, "PUBLIC_APP_URL": RENDER_HOST}
        result = _cold("import app.core.config", env=env)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "PUBLIC_APP_URL" in combined, combined

    def test_localhost_is_refused_cold(self):
        env = {
            **PRODUCTION_ENV,
            "PUBLIC_APP_URL": "http://localhost:3000",
        }
        result = _cold("import app.core.config", env=env)
        assert result.returncode != 0
        assert "PUBLIC_APP_URL" in result.stdout + result.stderr

    def test_development_still_imports_with_nothing_configured(self):
        """The fallback that keeps local work and this suite viable."""
        result = _cold(
            "from app.core.config import settings\n"
            "print(settings.resolved_public_app_url)",
            env={
                "PATH": "/usr/bin:/bin",
                "DATABASE_URL": "postgresql://u:p@localhost/db",
                "JWT_SECRET": "x" * 32,
            },
        )
        _assert_no_circular_import(result)
        assert "localhost:3000" in result.stdout


# ---------------------------------------------------------------------------
# The pre-deploy command itself
# ---------------------------------------------------------------------------


class TestRenderPreDeployCommand:
    """(4) ``alembic upgrade head`` — the literal ``preDeployCommand``.

    This is where the failure surfaced, and the import chain it pulls
    (``env.py`` → ``app.main`` → every model → ``config``) is wider
    than any single module import. Idempotent against a database
    already at head, which conftest guarantees.
    """

    def _db_url(self) -> str:
        url = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
            "DATABASE_URL"
        )
        if not url:
            pytest.skip("no test database configured")
        return url

    def test_alembic_upgrade_head_succeeds_under_production_config(self):
        url = self._db_url()
        alembic = pathlib.Path(sys.executable).parent / "alembic"
        if not alembic.exists():
            pytest.skip("alembic not on this interpreter's path")

        result = subprocess.run(
            [str(alembic), "upgrade", "head"],
            cwd=BACKEND,
            env={
                **PRODUCTION_ENV,
                "PATH": f"{alembic.parent}:/usr/bin:/bin",
                "HOME": os.environ.get("HOME", "/tmp"),
                "DATABASE_URL": url,
                "STRIPE_SECRET_KEY": "sk_live_stub",
                "STRIPE_WEBHOOK_SECRET": "whsec_stub",
                "R2_ACCOUNT_ID": "a" * 32,
                "R2_ACCESS_KEY_ID": "k",
                "R2_SECRET_ACCESS_KEY": "s",
                "R2_BUCKET_PRIVATE": "priv",
                "R2_BUCKET_PUBLIC": "pub",
                "R2_PUBLIC_BASE_URL": "https://cdn.test",
            },
            capture_output=True, text=True, timeout=600,
        )
        _assert_no_circular_import(result)

    def test_the_blueprint_still_declares_that_command(self):
        """If the pre-deploy command changes, the test above is
        measuring something that no longer runs."""
        import yaml

        data = yaml.safe_load((BACKEND.parent / "render.yaml").read_text())
        api = next(s for s in data["services"] if s["name"] == "fc-api")
        assert api["preDeployCommand"] == "alembic upgrade head"


# ---------------------------------------------------------------------------
# The invariant, stated directly
# ---------------------------------------------------------------------------


def _imports_of(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every ``app.*`` module this file imports, at any scope.

    Function-scoped imports count. A deferred import still forms an
    edge — the broken validator's import was function-scoped, and that
    is exactly why it was invisible until production ran it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("app"):
                found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app"):
                    found.append((node.lineno, alias.name))
    return found


class TestTheDependencyDirectionIsOneWay:
    def test_url_policy_imports_nothing_from_the_application(self):
        """The property that makes it usable from inside ``Settings()``.

        If it ever grows an ``app`` import, the cycle can come back
        through the back door, and only a cold production boot would
        notice.
        """
        imports = _imports_of(BACKEND / "app/core/url_policy.py")
        assert imports == [], (
            "app/core/url_policy.py must stay dependency-free: "
            f"{imports}"
        )

    def test_config_never_imports_public_url_at_any_scope(self):
        """The precise edge that broke the deploy.

        Deliberately checks function scope too. The import that failed
        was inside a validator, so a module-level-only check would have
        passed on the broken commit.
        """
        offenders = [
            f"line {line}: {module}"
            for line, module in _imports_of(BACKEND / "app/core/config.py")
            if module.startswith("app.core.public_url")
        ]
        assert offenders == [], (
            "config.py must not import app.core.public_url — that module "
            "reads ``settings``, which does not exist until config finishes "
            "executing. Put shared rules in app/core/url_policy.py "
            f"instead. Found: {offenders}"
        )

    def test_config_depends_only_on_the_policy_leaf(self):
        """Nothing else from ``app`` either. ``config`` is imported by
        almost everything, so every edge out of it is a potential
        cycle."""
        modules = {module for _line, module in _imports_of(
            BACKEND / "app/core/config.py"
        )}
        assert modules <= {"app.core.url_policy"}, modules

    def test_public_url_is_allowed_to_depend_on_config(self):
        """Documenting the direction that is fine, so nobody 'fixes' it.

        ``public_url`` → ``config`` → ``url_policy`` is a chain, not a
        cycle. The read is deferred to call time as belt and braces.
        """
        imports = _imports_of(BACKEND / "app/core/public_url.py")
        modules = {module for _line, module in imports}
        assert "app.core.config" in modules, imports
        assert "app.core.url_policy" in modules, imports

    def test_the_policy_module_has_no_module_level_side_effects(self):
        """Only definitions and constants. Something imported during
        ``Settings()`` construction must not run anything."""
        tree = ast.parse(
            (BACKEND / "app/core/url_policy.py").read_text(encoding="utf-8")
        )
        for node in tree.body:
            assert isinstance(node, (
                ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef,
                ast.Assign, ast.AnnAssign, ast.Expr,
            )), ast.dump(node)
            if isinstance(node, ast.Expr):
                # Only the module docstring.
                assert isinstance(node.value, ast.Constant), ast.dump(node)
