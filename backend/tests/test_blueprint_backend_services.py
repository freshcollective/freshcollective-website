"""Every backend service in the blueprint can actually construct Settings.

The failure these exist for
---------------------------
``PUBLIC_APP_URL`` became a production invariant on the shared
``Settings`` object. It was declared on the five services that had
``APP_ENV=production`` in ``render.yaml`` — and two production crons,
``fc-connect-transfer-sweeper`` and ``fc-connect-recovery-sweeper``,
were not in ``render.yaml`` at all. They had been specified in
``docs/connect-go-live.md`` §2.1/§2.2 and then created in the Dashboard
instead, so a blueprint sync could not reach them and no check that
reads this file could see them. Both failed to boot.

Neither sweeper sends email, which is the point. They import model
modules, those import ``app.core.config``, and that constructs
``Settings()`` at module scope — so a *global* production invariant on
that object applies to every process that imports it, regardless of
what the process does. A job's env has to satisfy the whole object, not
the part of it the job uses.

What is checked
---------------
Enumerating services and asserting a variable is present would only
have caught this particular variable. So the central test instead
**builds each python service's environment from the blueprint and
constructs ``Settings`` from it** — the same thing the service does on
boot. Any future production invariant is covered without anyone
remembering to extend a list, and a newly declared service that is
missing anything fails here rather than on Render.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_blueprint_backend_services.py
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from app.core.config import Settings

BACKEND = pathlib.Path(__file__).resolve().parent.parent
BLUEPRINT = BACKEND.parent / "render.yaml"

PUBLIC_APP_URL = "https://freshcollective.au"

#: The crons that were created in the Dashboard instead of here. Named
#: explicitly so that reverting them to Dashboard-only fails loudly
#: rather than quietly reopening the gap.
ADOPTED_FROM_THE_DASHBOARD = (
    "fc-connect-transfer-sweeper",
    "fc-connect-recovery-sweeper",
)

#: Operational scripts that are run by hand, once. A blueprint entry for
#: any of these would schedule a one-time mutation, which is the one
#: thing they must never be.
ONE_TIME_SCRIPTS = (
    "migrate_legacy_community_media_keys",
    "delete_legacy_community_media_object",
    "cleanup_orphaned_uploaded_media",
    "cleanup_production_test_accounts",
    "ways_to_connect_reset_participation_once",
    "delete_natural_leader_hub_from_prod",
)


def _blueprint() -> dict:
    return yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))


def _services() -> list[dict]:
    return _blueprint()["services"]


def _python_services() -> list[dict]:
    """Services that run backend Python, and therefore import Settings.

    ``fc-web`` is Node and lives in ``frontend/``; it cannot import
    ``app.core.config`` and is correctly outside all of this.
    """
    return [s for s in _services() if s.get("runtime") == "python"]


def _stub_value(key: str) -> str:
    """A plausible value for a var the blueprint does not carry.

    ``sync: false`` means operator-supplied and ``fromDatabase`` /
    ``fromService`` are resolved by Render, so a boot simulation has to
    supply something. The shapes matter: production refuses an
    ``sk_test_`` key, and the R2 account id must be 32 hex characters.
    """
    if key == "DATABASE_URL":
        return "postgresql://u:p@localhost/db"
    if key == "STRIPE_SECRET_KEY":
        return "sk_live_stub"
    if key.endswith("WEBHOOK_SECRET"):
        return "whsec_stub"
    if key == "R2_ACCOUNT_ID":
        return "a" * 32
    if key.endswith("_BASE_URL") or key == "FRONTEND_ORIGIN":
        # What FRONTEND_ORIGIN genuinely is in production: fc-web's
        # Render host. The simulation should not quietly hand it the
        # public domain and hide the very conflation this guards.
        return "https://fc-web-q950.onrender.com"
    if key == "JWT_SECRET":
        return "x" * 32
    if key == "EMAIL_FROM":
        return "hello@freshcollective.au"

    # Typed fields need a parseable stub. Several ``sync: false`` vars
    # are feature-flag booleans, and "stub" is not a boolean — read the
    # annotation off Settings rather than guessing from the name.
    field = Settings.model_fields.get(key.lower())
    if field is not None:
        annotation = str(field.annotation)
        if "bool" in annotation:
            return "false"
        if "int" in annotation:
            return "0"
    return "stub"


def _env_for(service: dict) -> dict[str, str]:
    """The environment this service boots with, as the blueprint
    describes it."""
    env: dict[str, str] = {}
    for entry in service.get("envVars", []):
        key = entry["key"]
        if "value" in entry:
            env[key] = str(entry["value"])
        else:
            env[key] = _stub_value(key)
    return env


def _ids(services: list[dict]) -> list[str]:
    return [s["name"] for s in services]


# ---------------------------------------------------------------------------
# The central check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "service", _python_services(), ids=_ids(_python_services()),
)
def test_every_python_service_can_construct_settings(service, monkeypatch):
    """Boot each declared backend service from its own declared env.

    This is the check that generalises. Asserting "PUBLIC_APP_URL is
    present" would only ever catch PUBLIC_APP_URL; constructing the real
    object catches whatever the next production invariant turns out to
    be, on whatever service is declared next.
    """
    for key in list(_env_for(service)) + [
        "APP_ENV", "FC_SERVICE_ROLE", "PUBLIC_APP_URL", "FRONTEND_ORIGIN",
        "DATABASE_URL", "JWT_SECRET", "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY", "R2_BUCKET_PRIVATE", "R2_BUCKET_PUBLIC",
        "R2_PUBLIC_BASE_URL", "FC_JOB_REQUIRES_STRIPE",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in _env_for(service).items():
        monkeypatch.setenv(key, value)

    try:
        settings = Settings(_env_file=None)
    except Exception as exc:  # noqa: BLE001 — the message is the point
        pytest.fail(
            f"{service['name']} cannot construct Settings from the env "
            f"render.yaml declares for it:\n\n{exc}\n\n"
            f"Declared keys: {sorted(_env_for(service))}"
        )

    assert settings.resolved_public_app_url == PUBLIC_APP_URL, (
        f"{service['name']} would build member-facing links from "
        f"{settings.resolved_public_app_url!r}"
    )


# ---------------------------------------------------------------------------
# Coverage of the blueprint itself
# ---------------------------------------------------------------------------


class TestPublicAppUrlCoverage:
    def test_every_python_service_declares_it(self):
        """Not only the ones with APP_ENV=production.

        A service without ``APP_ENV=production`` does not trip the guard
        today, which makes it a trap: the day somebody sets that
        variable — the correct thing to do for a job that uses the live
        Stripe key — the job stops booting. Declaring it everywhere
        costs nothing and removes the trap.
        """
        missing = []
        for service in _python_services():
            env = {e["key"]: e.get("value") for e in service.get("envVars", [])}
            if env.get("PUBLIC_APP_URL") != PUBLIC_APP_URL:
                missing.append(f"{service['name']}: {env.get('PUBLIC_APP_URL')!r}")
        assert missing == [], (
            "every runtime: python service must declare "
            f"PUBLIC_APP_URL={PUBLIC_APP_URL}:\n" + "\n".join(missing)
        )

    def test_it_is_pinned_and_not_operator_supplied(self):
        """``sync: false`` would let a sync leave it unset on a fresh
        service, which is how this gap opens. A pinned ``value:`` is
        reasserted on every sync — the behaviour we want for a stable
        fact about the product."""
        for service in _python_services():
            for entry in service.get("envVars", []):
                if entry["key"] != "PUBLIC_APP_URL":
                    continue
                assert entry.get("value") == PUBLIC_APP_URL, service["name"]
                assert "sync" not in entry, (
                    f"{service['name']}: PUBLIC_APP_URL must be pinned, "
                    f"not operator-supplied"
                )
                assert "fromService" not in entry, service["name"]
                assert "fromDatabase" not in entry, service["name"]

    def test_the_node_frontend_is_correctly_excluded(self):
        """fc-web runs Node from ``frontend/``. It cannot import
        ``app.core.config``, so this invariant does not apply to it —
        stated so the exclusion is deliberate rather than an oversight."""
        web = next(s for s in _services() if s["name"] == "fc-web")
        assert web["runtime"] == "node"
        assert web["rootDir"] == "frontend"
        env = {e["key"] for e in web.get("envVars", [])}
        assert "PUBLIC_APP_URL" not in env


class TestTheDashboardOnlyCronsAreDeclaredHere:
    @pytest.mark.parametrize("name", ADOPTED_FROM_THE_DASHBOARD)
    def test_the_sweeper_is_in_the_blueprint(self, name):
        """A Dashboard-only service is outside every guarantee this file
        provides: no sync can give it a new variable, and no check that
        reads this file can see it. Both of these drifted twice before
        being adopted."""
        assert name in _ids(_services()), (
            f"{name} is not declared in render.yaml. A Dashboard-created "
            f"service cannot receive env vars from a blueprint sync."
        )

    @pytest.mark.parametrize("name", ADOPTED_FROM_THE_DASHBOARD)
    def test_the_sweeper_matches_the_go_live_design(self, name):
        """Adoption must not silently change what the job does.

        The schedule, command and least-privilege env come from
        ``docs/connect-go-live.md`` §2.1/§2.2, which specified these
        jobs before they were built.
        """
        service = next(s for s in _services() if s["name"] == name)
        assert service["type"] == "cron"
        assert service["runtime"] == "python"
        assert service["rootDir"] == "backend"
        assert service["schedule"] == "*/15 * * * *"
        assert service["startCommand"].startswith("python scripts/")

        env = {e["key"]: e.get("value") for e in service["envVars"]}
        assert env["FC_SERVICE_ROLE"] == "job"
        assert env["APP_ENV"] == "production"
        # The API key and only the API key — a cron consumes no webhooks.
        assert "STRIPE_SECRET_KEY" in env
        assert "STRIPE_WEBHOOK_SECRET" not in env
        # And nothing it has no use for.
        assert not [k for k in env if k.startswith("R2_")], env
        assert "RESEND_API_KEY" not in env


class TestEveryCronRunsSomethingThatExists:
    @pytest.mark.parametrize(
        "service",
        [s for s in _python_services() if s.get("type") == "cron"],
        ids=_ids([s for s in _python_services() if s.get("type") == "cron"]),
    )
    def test_the_start_command_script_is_present(self, service):
        command = service["startCommand"]
        assert command.startswith("python scripts/"), command
        script = command.split()[1]
        assert (BACKEND / script).is_file(), (
            f"{service['name']} runs {script}, which does not exist"
        )

    @pytest.mark.parametrize(
        "service",
        _python_services(), ids=_ids(_python_services()),
    )
    def test_it_has_a_database(self, service):
        env = {e["key"] for e in service.get("envVars", [])}
        assert "DATABASE_URL" in env, service["name"]


class TestOneTimeScriptsAreNotScheduled:
    """The counterpart invariant.

    These exist to be run once, by a person, after reading their output.
    A blueprint entry would make a one-time mutation recurring — and
    because a pinned ``value:`` is reasserted on every sync, removing it
    from the Dashboard would not be enough to stop it.
    """

    def test_none_of_them_appear_in_the_blueprint(self):
        text = BLUEPRINT.read_text(encoding="utf-8")
        scheduled = [name for name in ONE_TIME_SCRIPTS if name in text]
        assert scheduled == [], scheduled

    def test_the_list_refers_to_real_scripts(self):
        """Otherwise the test above passes by naming nothing."""
        for name in ONE_TIME_SCRIPTS:
            assert (BACKEND / f"scripts/{name}.py").is_file(), name


class TestFrontendOriginIsUnchanged:
    """Explicitly out of scope for the coverage fix, and pinned so it
    stays that way.

    ``FRONTEND_ORIGIN`` is the CORS origin and is wired to fc-web's
    Render host by design. Nothing about extending ``PUBLIC_APP_URL``
    coverage should touch it.
    """

    def test_only_the_two_services_that_had_it_still_have_it(self):
        declaring = sorted(
            s["name"] for s in _services()
            if any(e["key"] == "FRONTEND_ORIGIN" for e in s.get("envVars", []))
        )
        assert declaring == ["fc-api", "fc-gathering-reminders"], declaring

    def test_fc_api_still_wires_it_to_the_platform_host(self):
        api = next(s for s in _services() if s["name"] == "fc-api")
        entry = next(
            e for e in api["envVars"] if e["key"] == "FRONTEND_ORIGIN"
        )
        assert entry["fromService"]["name"] == "fc-web"
        assert entry["fromService"]["envVarKey"] == "RENDER_EXTERNAL_URL"

    def test_no_service_sets_frontend_origin_to_the_public_domain(self):
        """If the two were ever collapsed back together, the separation
        this whole line of work established would be gone."""
        for service in _services():
            for entry in service.get("envVars", []):
                if entry["key"] == "FRONTEND_ORIGIN":
                    assert entry.get("value") != PUBLIC_APP_URL, service["name"]
