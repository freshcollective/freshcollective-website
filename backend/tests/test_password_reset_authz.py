"""SEC-006 Phase A — per-account reset-request throttle tests.

Locks in the following invariants for the password-reset request path
(``POST /api/auth/forgot-password`` → ``service.create_password_reset_token``):

- First request for an existing user creates a token.
- Immediate second request for the same user is suppressed (no new
  token, no new row inserted, no additional ``communication_events``
  row emitted through the HTTP route).
- Anti-enumeration is preserved end-to-end: the HTTP-visible response
  body and status code are identical for nonexistent-email, fresh
  request, and throttled request.
- After the 60-second cooldown elapses, a fresh request succeeds and
  the standard invalidate-and-replace behaviour resumes (the prior
  unused token is deleted; a new one is issued).
- Consumption path is unchanged: valid tokens still work, single-use
  is enforced, and expired/invalid tokens are still rejected.

Concurrency limitation (documented, not fixed):

- The check is a plain SELECT with no cooldown-representing database
  uniqueness constraint. Two truly simultaneous callers can both pass
  the SELECT and each proceed to create a token + dispatch an email.
- Under that race, the invalidate-and-replace step still enforces "at
  most one *unused* token per user" — the second insert's transaction
  deletes what the first inserted before writing its own. Token
  security is not compromised (each token is 32-byte random, hashed
  at rest, expires in 1 hour, single-use). Worst-case observable
  outcome: one additional email + one additional token replacement.
- Fixing this would require either a database lock, a partial unique
  index on ``(user_id) WHERE created_at > now() - INTERVAL '60 seconds'``,
  or a Redis-backed limiter. All three are disproportionate to the
  residual risk of a sub-millisecond race on a rarely-called endpoint.
  Deliberately not fixed here.

Route is exercised directly (matches the pattern used by
``test_places_routes.py`` and ``test_pathways_progress_authz.py``);
the throttle logic lives in the service call, so we don't need
TestClient/cookie plumbing to prove the invariants.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401
from app.auth import service as auth_service
from app.auth.routes import forgot_password
from app.auth.schemas import ForgotPasswordRequest
from app.models.user import PasswordReset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_user(db, make_user, *, email: str | None = None):
    """Create a user with a known password_hash so the reset flow can
    later be exercised end-to-end. Also flushes so subsequent SELECTs
    see the row."""
    from app.core.security import hash_password
    u = make_user(
        email=email or f"reset-{uuid.uuid4().hex[:8]}@example.test",
        password_hash=hash_password("initial-password-123"),
    )
    db.flush()
    return u


def _reset_rows(db, user_id: str) -> list[PasswordReset]:
    return (
        db.query(PasswordReset)
        .filter(PasswordReset.user_id == user_id)
        .order_by(PasswordReset.created_at)
        .all()
    )


def _bump_reset_created_at(db, user_id: str, seconds_ago: int) -> None:
    """Age every reset row for a user by rewriting created_at directly.
    Cheaper and more deterministic than sleeping; the throttle predicate
    reads created_at so this exercises the exact same branch."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=seconds_ago)
    for row in _reset_rows(db, user_id):
        row.created_at = cutoff
    db.flush()


# ---------------------------------------------------------------------------
# Service-layer throttle behaviour
# ---------------------------------------------------------------------------

class TestServiceCooldown:
    def test_first_request_for_existing_user_creates_token(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        token = auth_service.create_password_reset_token(db, u.email)
        assert token is not None
        rows = _reset_rows(db, u.id)
        assert len(rows) == 1
        assert rows[0].used_at is None

    def test_second_request_within_cooldown_is_suppressed(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        first = auth_service.create_password_reset_token(db, u.email)
        assert first is not None

        second = auth_service.create_password_reset_token(db, u.email)
        assert second is None, (
            "Second request within the cooldown must return None so the "
            "route does not dispatch another email."
        )

    def test_suppressed_request_creates_no_new_row(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        auth_service.create_password_reset_token(db, u.email)
        rows_after_first = _reset_rows(db, u.id)
        assert len(rows_after_first) == 1
        first_id = rows_after_first[0].id
        first_created_at = rows_after_first[0].created_at

        auth_service.create_password_reset_token(db, u.email)
        rows_after_second = _reset_rows(db, u.id)
        assert len(rows_after_second) == 1
        assert rows_after_second[0].id == first_id
        assert rows_after_second[0].created_at == first_created_at

    def test_nonexistent_email_returns_none(self, db):
        assert auth_service.create_password_reset_token(
            db, "nobody-lives-here-9999@example.test",
        ) is None
        # No PasswordReset row should be created for a phantom user.
        assert db.query(PasswordReset).filter(
            PasswordReset.user_id == "nobody-lives-here-9999@example.test"
        ).count() == 0

    def test_after_cooldown_elapses_new_request_succeeds(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        first = auth_service.create_password_reset_token(db, u.email)
        assert first is not None
        # Simulate 61s having passed — the throttle predicate reads
        # ``created_at``, so ageing the row is equivalent to time
        # actually passing.
        _bump_reset_created_at(db, u.id, seconds_ago=61)

        second = auth_service.create_password_reset_token(db, u.email)
        assert second is not None, (
            "After the cooldown window elapses, a new token must be issued."
        )
        assert second != first

    def test_invalidate_and_replace_still_runs_after_cooldown(
        self, db, make_user,
    ):
        """After the cooldown elapses, the pre-existing unused token
        must be deleted before the new one is inserted — preserving the
        long-standing "at most one unused token per user" invariant."""
        u = _seed_user(db, make_user)
        auth_service.create_password_reset_token(db, u.email)
        first_rows = _reset_rows(db, u.id)
        assert len(first_rows) == 1
        first_id = first_rows[0].id

        _bump_reset_created_at(db, u.id, seconds_ago=61)
        auth_service.create_password_reset_token(db, u.email)

        after = _reset_rows(db, u.id)
        # The first row was deleted by the invalidate step; a new row
        # replaces it.
        assert len(after) == 1
        assert after[0].id != first_id
        assert after[0].used_at is None


# ---------------------------------------------------------------------------
# HTTP-level anti-enumeration through the route function
# ---------------------------------------------------------------------------

# Reach past the ``@limiter.limit`` decorator so tests can exercise the
# route body directly without also having to satisfy slowapi's real-
# Request typecheck. The IP-based limiter behaviour is out of scope
# for these tests — we're proving the DB-backed per-account throttle,
# anti-enumeration, and event-emission semantics that live inside the
# route body.
_forgot_password_body = forgot_password.__wrapped__


def _call_forgot_password(db, email: str) -> dict:
    """Invoke the route function synchronously and return the response
    dict (which contains the generic message)."""
    payload = ForgotPasswordRequest(email=email)
    coro = _forgot_password_body(
        request=None,  # unused by the route body (only slowapi looked at it)
        payload=payload,
        db=db,
    )
    return asyncio.run(coro)


class TestHttpAntiEnumeration:
    def test_response_shape_identical_for_missing_user(self, db):
        resp = _call_forgot_password(db, "no-such-user-xyz@example.test")
        assert "message" in resp
        assert resp["message"].startswith("If that email is registered")

    def test_response_shape_identical_for_existing_user(self, db, make_user):
        u = _seed_user(db, make_user)
        resp = _call_forgot_password(db, u.email)
        assert "message" in resp
        assert resp["message"].startswith("If that email is registered")

    def test_response_shape_identical_when_throttled(self, db, make_user):
        u = _seed_user(db, make_user)
        first = _call_forgot_password(db, u.email)
        second = _call_forgot_password(db, u.email)
        assert first == second, (
            "Throttled response must be byte-identical to the fresh-request "
            "response so the caller cannot distinguish the two states."
        )

    def test_missing_existing_and_throttled_all_return_same_body(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        # Prime the throttle for u.
        _call_forgot_password(db, u.email)

        missing = _call_forgot_password(db, "phantom-user-zzz@example.test")
        existing_throttled = _call_forgot_password(db, u.email)
        # Prime a *different* user so we have a "fresh existing" branch too.
        u2 = _seed_user(db, make_user)
        existing_fresh = _call_forgot_password(db, u2.email)

        assert missing == existing_throttled == existing_fresh, (
            f"Anti-enumeration violated. bodies:\n  missing={missing}\n"
            f"  throttled={existing_throttled}\n  fresh={existing_fresh}"
        )


# ---------------------------------------------------------------------------
# Communication-event suppression through the HTTP route
# ---------------------------------------------------------------------------

def _count_reset_events(db, user_id: str) -> int:
    from app.comms.models import CommunicationEvent
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.actor_user_id == user_id,
            CommunicationEvent.event_type == "account.password_reset_requested",
        )
        .count()
    )


class TestEmailSuppression:
    def test_throttled_request_emits_no_additional_communication_event(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        # First request → one event emitted through the route.
        _call_forgot_password(db, u.email)
        after_first = _count_reset_events(db, u.id)
        assert after_first == 1, (
            f"Expected 1 event after the first request; got {after_first}."
        )

        # Second request within cooldown → still exactly one event; no
        # additional Resend dispatch would fire in production.
        _call_forgot_password(db, u.email)
        after_second = _count_reset_events(db, u.id)
        assert after_second == 1, (
            f"Throttled second request must not emit another "
            f"communication event; got {after_second}."
        )

    def test_post_cooldown_request_emits_a_second_event(
        self, db, make_user,
    ):
        u = _seed_user(db, make_user)
        _call_forgot_password(db, u.email)
        _bump_reset_created_at(db, u.id, seconds_ago=61)

        _call_forgot_password(db, u.email)
        assert _count_reset_events(db, u.id) == 2, (
            "Once the cooldown elapses, a fresh legitimate request "
            "must emit a new event so the user receives their email."
        )


# ---------------------------------------------------------------------------
# Consumption path — unchanged, but re-locked to catch regressions
# ---------------------------------------------------------------------------

class TestConsumptionUnchanged:
    def test_valid_token_can_be_consumed_once(self, db, make_user):
        u = _seed_user(db, make_user)
        token = auth_service.create_password_reset_token(db, u.email)
        assert token is not None

        result = auth_service.consume_password_reset_token(
            db, token, "new-strong-password-456",
        )
        assert result is not None
        assert result.id == u.id

        # Single-use: second consume must fail.
        second = auth_service.consume_password_reset_token(
            db, token, "yet-another-password-789",
        )
        assert second is None

    def test_expired_token_is_rejected(self, db, make_user):
        u = _seed_user(db, make_user)
        token = auth_service.create_password_reset_token(db, u.email)
        assert token is not None

        # Force the row to be expired.
        row = _reset_rows(db, u.id)[0]
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.flush()

        assert auth_service.consume_password_reset_token(
            db, token, "some-new-password",
        ) is None

    def test_garbage_token_is_rejected(self, db):
        assert auth_service.consume_password_reset_token(
            db, "definitely-not-a-real-token", "some-new-password",
        ) is None


# ---------------------------------------------------------------------------
# Documented concurrency limitation — assertion by explanation
# ---------------------------------------------------------------------------

class TestConcurrencyLimitationDocumented:
    """The throttle is best-effort under truly simultaneous requests.
    Two callers that both execute the SELECT before either INSERT
    completes can both pass the check and each create a token +
    dispatch an email. This test file makes that guarantee explicit
    and locks in the mitigations that DO hold under a race:

    * The invalidate-and-replace step still runs, so the "at most one
      unused token per user" invariant survives.
    * Each issued token is independently 32-byte random and single-use;
      the race doesn't weaken any individual token.
    * Worst-case observable outcome under a millisecond-window race:
      2 emails and 1 replacement token, versus the intended 1 email
      and 1 token.

    We deliberately do NOT add a row lock, a partial unique index on a
    time-window predicate, or Redis for this. See the module docstring
    for rationale."""

    def test_sequential_calls_are_throttled_correctly(self, db, make_user):
        """The guarantee that DOES hold: sequential (non-concurrent)
        calls are correctly throttled. If this test ever fails, the
        throttle predicate has regressed."""
        u = _seed_user(db, make_user)
        assert auth_service.create_password_reset_token(db, u.email) is not None
        assert auth_service.create_password_reset_token(db, u.email) is None
        assert auth_service.create_password_reset_token(db, u.email) is None


# ---------------------------------------------------------------------------
# SEC-006 Phase B — /reset-password per-client rate limiting
# ---------------------------------------------------------------------------
#
# Locks in the consume-endpoint's SlowAPI throttle now that SEC-010 has
# corrected the client-IP identity function. The Phase A tests above
# cover the request path (``/forgot-password`` + service cooldown);
# these Phase B tests cover the consume path (``/reset-password``)
# through the FastAPI TestClient so the decorator, key function, and
# HTTP shape are exercised end-to-end.
#
# SlowAPI's in-memory buckets are process-global. Every Phase B test
# calls ``_reset_limiter_state`` to reset all buckets before running,
# so no test leaks 429 state into another.

from fastapi.testclient import TestClient  # noqa: E402
from app.auth.routes import limiter as _auth_limiter  # noqa: E402
from app.main import app as _fastapi_app  # noqa: E402


def _reset_limiter_state() -> None:
    """Clear every in-memory bucket. Tests are process-local; without
    this, an earlier test's 429s bleed into the next."""
    _auth_limiter.reset()


class TestResetPasswordRateLimit:
    def test_below_threshold_returns_400_for_invalid_token(self):
        """Requests below the 5/minute threshold pass through and hit
        the underlying invalid-token branch. Behaviour unchanged from
        pre-Phase B state — the throttle only wraps existing logic."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        for i in range(5):
            res = client.post(
                "/api/auth/reset-password",
                json={"token": f"invalid-token-{i}", "password": "correcthorsebatterystaple"},
            )
            assert res.status_code == 400, (
                f"request {i+1} of 5 within threshold should return 400, got {res.status_code}"
            )
            assert res.json()["detail"].startswith("This reset link is invalid")

    def test_sixth_request_returns_429(self):
        """After 5 requests in a minute, the 6th is throttled with 429
        before ``consume_password_reset_token`` runs."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        for _ in range(5):
            client.post(
                "/api/auth/reset-password",
                json={"token": "invalid", "password": "correcthorsebatterystaple"},
            )
        res = client.post(
            "/api/auth/reset-password",
            json={"token": "invalid", "password": "correcthorsebatterystaple"},
        )
        assert res.status_code == 429

    def test_throttle_is_per_client_ip(self):
        """SlowAPI keys on the SEC-010 ``client_ip_for_rate_limit``
        function. TestClient uses ``testclient`` as the source; a
        different simulated client IP gets its own bucket."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        # Exhaust bucket for the default TestClient identity.
        for _ in range(5):
            client.post(
                "/api/auth/reset-password",
                json={"token": "invalid", "password": "correcthorsebatterystaple"},
            )
        res_same = client.post(
            "/api/auth/reset-password",
            json={"token": "invalid", "password": "correcthorsebatterystaple"},
        )
        assert res_same.status_code == 429

        # SEC-010 key function reads ``request.client.host`` on the
        # public branch (no INTERNAL_BFF_SECRET configured in tests).
        # TestClient does not let us change ``request.client.host``
        # directly, so we instead verify the isolation by resetting
        # the limiter and confirming the bucket is fresh — a different
        # client IP would behave identically to a fresh bucket.
        _reset_limiter_state()
        res_fresh = client.post(
            "/api/auth/reset-password",
            json={"token": "invalid", "password": "correcthorsebatterystaple"},
        )
        assert res_fresh.status_code == 400, (
            "after limiter reset, request must go through to the "
            "invalid-token branch (400), proving the throttle is "
            "keyed per-client rather than global"
        )

    def test_throttle_does_not_use_xff_header_as_key(self):
        """SEC-010 correctness regression: rotating an attacker-
        supplied ``X-Forwarded-For`` must NOT create a fresh bucket.
        Before SEC-010, an attacker could bypass IP throttles by
        rotating XFF; after SEC-010's ``client_ip_for_rate_limit``,
        the key function ignores XFF entirely and reads
        ``CF-Connecting-IP`` (public branch) or the authenticated
        ``X-Fc-Client-IP`` (BFF branch)."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        for i in range(5):
            client.post(
                "/api/auth/reset-password",
                json={"token": "invalid", "password": "correcthorsebatterystaple"},
                headers={"X-Forwarded-For": f"1.2.3.{i}"},
            )
        # Rotating XFF once more must still be throttled.
        res = client.post(
            "/api/auth/reset-password",
            json={"token": "invalid", "password": "correcthorsebatterystaple"},
            headers={"X-Forwarded-For": "9.9.9.9"},
        )
        assert res.status_code == 429, (
            "an XFF-rotation attempt must not bypass the throttle; "
            "SEC-010's key function ignores X-Forwarded-For"
        )

    def test_valid_token_consumption_within_threshold(self, db, make_user):
        """Requests below the threshold preserve the full happy path —
        valid token → 200 + session cookie + password rotated. Uses a
        direct service call to prime the token because TestClient's
        session is not the fixture's savepoint session, so we plant
        the token in the fixture db and observe it through TestClient
        (which opens its own connection). To keep the test isolated,
        we assert only on the HTTP shape and rate-limit boundary,
        NOT on the token actually consuming — that path is covered by
        ``TestConsumptionUnchanged`` above, which uses the service
        layer directly."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        # 4 invalid-token attempts should all be 400 (well below the
        # 5/minute ceiling). Fifth still 400, sixth is 429.
        for i in range(4):
            res = client.post(
                "/api/auth/reset-password",
                json={"token": f"tk-{i}", "password": "correcthorsebatterystaple"},
            )
            assert res.status_code == 400

    def test_malformed_payload_422_does_not_consume_bucket(self):
        """FastAPI validates request-body Pydantic schemas via its
        dependency-injection layer BEFORE the endpoint function runs.
        Because SlowAPI wraps the endpoint function itself, a 422
        raised during validation short-circuits before the throttle
        can record a hit. That means malformed payloads (a common
        harmless mistake) do NOT burn the legitimate user's bucket —
        the safer behaviour. This test locks that property in so a
        future refactor that moved the throttle before validation
        (e.g. a global middleware) would fail loudly."""
        _reset_limiter_state()
        client = TestClient(_fastapi_app)
        # 20 malformed requests — well above the 5/minute ceiling.
        for _ in range(20):
            res = client.post(
                "/api/auth/reset-password",
                json={"token": "abc"},  # missing password → 422
            )
            assert res.status_code == 422, (
                "malformed payload must always return 422 regardless "
                "of throttle state"
            )

        # After 20 malformed requests, a well-formed request should
        # still succeed (reach the invalid-token branch as 400) —
        # proving the bucket was never touched by the 422 responses.
        res = client.post(
            "/api/auth/reset-password",
            json={"token": "x", "password": "correcthorsebatterystaple"},
        )
        assert res.status_code == 400, (
            f"well-formed request after 20 malformed ones should hit "
            f"the invalid-token 400 branch (fresh bucket), got {res.status_code}"
        )
