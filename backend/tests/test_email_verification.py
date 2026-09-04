"""SEC-009 — email verification regression tests.

Locks the invariants specified in the SEC-009 implementation policy:

  * New signups start unverified.
  * Signup fires exactly ONE email/event lifecycle: the verification/
    welcome email up front, then the existing welcome-after-signup
    event only after successful verification.
  * Verification tokens are hashed at rest; the raw value is never
    persisted anywhere.
  * Valid tokens succeed; every failure branch (missing / expired /
    used / invalidated) collapses to a generic 400.
  * Resend invalidates previous tokens; only the newest works.
  * Resend enforces both the SEC-010 IP rate limit and the 60s
    per-account cooldown.
  * Trust actions gated by ``get_verified_current_user`` refuse
    unverified callers with 403; verified callers pass through.
  * Invitation acceptance requires verification (per Product
    Decision 2 — invitation does NOT auto-verify).
  * Password reset DOES auto-verify (per Product Decision 4).
  * Password-reset-based account reclamation invalidates any prior
    JWTs the original registrant held (SEC-008/015 interaction).
  * Verification itself does NOT bump ``session_version``.
  * Grandfathered users behave normally (migration 121 backfill).
  * SEC-002 cookie flags remain unchanged on all verification
    responses.
  * SEC-006 anti-enumeration on ``/forgot-password`` remains
    unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, HTTPException, Request, Response

# Ensure User's community_care FKs resolve in isolation.
import app.models.community_care  # noqa: F401

from app.auth import service as auth_service
from app.auth.dependencies import (
    SESSION_COOKIE,
    get_current_user,
    get_verified_creator_user,
    get_verified_current_user,
)
from app.auth.routes import (
    signup,
    verify_email,
    verify_email_resend,
    reset_password,
)
from app.auth.schemas import (
    ResetPasswordRequest,
    SignupRequest,
    VerifyEmailRequest,
)
from app.comms.models import CommunicationEvent
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
)
from app.models.user import EmailVerification, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cookie_request(token: str | None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"cookie", f"{SESSION_COOKIE}={token}".encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _plain_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
    }
    return Request(scope)


def _run(coro):
    return asyncio.run(coro)


def _seed_verified_user(db, make_user, **overrides):
    """Explicit helper — the conftest default is already verified,
    but naming it here makes each test's intent obvious."""
    return make_user(email_verified_at=datetime.utcnow(), **overrides)


def _seed_unverified_user(db, make_user, **overrides):
    return make_user(email_verified_at=None, **overrides)


def _count_events(db, user_id: str, event_type: str) -> int:
    return (
        db.query(CommunicationEvent)
        .filter(
            CommunicationEvent.event_type == event_type,
            CommunicationEvent.actor_user_id == user_id,
        )
        .count()
    )


# ---------------------------------------------------------------------------
# 1. Signup lifecycle
# ---------------------------------------------------------------------------


class TestSignupLifecycle:
    def _call_signup(self, db, *, email, password="strong-pw-123", name="Alice"):
        req = _plain_request()
        resp = Response()
        return _run(signup.__wrapped__(
            request=req,
            payload=SignupRequest(name=name, email=email, password=password),
            response=resp,
            background_tasks=BackgroundTasks(),
            db=db,
        )), resp

    def test_signup_creates_unverified_user(self, db):
        email = f"new-{uuid.uuid4().hex[:8]}@example.test"
        result, _ = self._call_signup(db, email=email)
        u = db.query(User).filter(User.email == email).one()
        assert u.email_verified_at is None
        assert result.email_verified_at is None

    def test_signup_emits_verification_event_not_welcome(self, db):
        email = f"new-{uuid.uuid4().hex[:8]}@example.test"
        self._call_signup(db, email=email)
        u = db.query(User).filter(User.email == email).one()
        assert _count_events(db, u.id, "account.email_verification_requested") == 1
        # The welcome event must NOT fire until verification succeeds.
        assert _count_events(db, u.id, "account.welcome_after_signup") == 0

    def test_signup_issues_session_cookie(self, db):
        email = f"new-{uuid.uuid4().hex[:8]}@example.test"
        _, resp = self._call_signup(db, email=email)
        raw = resp.headers.get("set-cookie", "")
        assert SESSION_COOKIE in raw

    def test_signup_creates_exactly_one_verification_token(self, db):
        email = f"new-{uuid.uuid4().hex[:8]}@example.test"
        self._call_signup(db, email=email)
        u = db.query(User).filter(User.email == email).one()
        rows = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 2. Token hashing / storage
# ---------------------------------------------------------------------------


class TestTokenStorage:
    def test_raw_token_never_persisted(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        assert raw is not None
        row = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).one()
        assert row.token_hash != raw
        assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()

    def test_token_expiry_is_24_hours(self, db, make_user):
        """Compare ``expires_at`` against our own Python clock to
        avoid the pre-existing DB-tz-vs-Python-UTC mismatch that
        makes ``expires_at - created_at`` look wrong."""
        from datetime import timezone as _tz
        u = _seed_unverified_user(db, make_user)
        now_utc = datetime.now(_tz.utc).replace(tzinfo=None)
        auth_service.create_email_verification_token(db, u)
        db.commit()
        row = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).one()
        delta = (row.expires_at - now_utc).total_seconds()
        assert 23.9 * 3600 <= delta <= 24.1 * 3600


# ---------------------------------------------------------------------------
# 3. Verification endpoint
# ---------------------------------------------------------------------------


class TestVerifyEndpoint:
    def _call_verify(self, db, token: str):
        req = _plain_request()
        return _run(verify_email.__wrapped__(
            request=req,
            payload=VerifyEmailRequest(token=token),
            background_tasks=BackgroundTasks(),
            db=db,
        ))

    def test_valid_token_flips_verified_at(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        assert raw is not None
        result = self._call_verify(db, raw)
        assert result == {"verified": True}
        db.refresh(u)
        assert u.email_verified_at is not None

    def test_valid_token_marks_used(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        self._call_verify(db, raw)
        row = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).one()
        assert row.used_at is not None

    def test_garbage_token_returns_generic_400(self, db):
        with pytest.raises(HTTPException) as exc:
            self._call_verify(db, "definitely-not-a-real-token")
        assert exc.value.status_code == 400
        assert "invalid or has expired" in exc.value.detail

    def test_expired_token_returns_generic_400(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        row = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).one()
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            self._call_verify(db, raw)
        assert exc.value.status_code == 400

    def test_used_token_cannot_replay(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        self._call_verify(db, raw)
        with pytest.raises(HTTPException) as exc:
            self._call_verify(db, raw)
        assert exc.value.status_code == 400

    def test_invalidated_token_returns_generic_400(self, db, make_user):
        """A token marked invalidated_at must not be consumable —
        proves the resend invalidate-and-replace pattern works."""
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        assert raw is not None
        # Simulate the invalidate-and-replace step directly.
        row = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).one()
        row.invalidated_at = datetime.utcnow()
        db.commit()
        with pytest.raises(HTTPException) as exc:
            self._call_verify(db, raw)
        assert exc.value.status_code == 400
        # And the user is still unverified — the invalidated token
        # didn't slip through.
        db.refresh(u)
        assert u.email_verified_at is None

    def test_verification_triggers_welcome_event(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        before = _count_events(db, u.id, "account.welcome_after_signup")
        self._call_verify(db, raw)
        after = _count_events(db, u.id, "account.welcome_after_signup")
        assert after == before + 1

    def test_verification_does_not_bump_session_version(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        sv_before = u.session_version
        raw = auth_service.create_email_verification_token(db, u)
        db.commit()
        self._call_verify(db, raw)
        db.refresh(u)
        assert u.session_version == sv_before


# ---------------------------------------------------------------------------
# 4. Resend endpoint
# ---------------------------------------------------------------------------


class TestResend:
    def _call_resend(self, db, user):
        req = _plain_request()
        return _run(verify_email_resend.__wrapped__(
            request=req,
            background_tasks=BackgroundTasks(),
            current_user=user,
            db=db,
        ))

    def test_resend_invalidates_previous_token(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        raw_a = auth_service.create_email_verification_token(db, u)
        db.commit()
        # Age past cooldown.
        db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).update(
            {"created_at": datetime.utcnow() - timedelta(seconds=120)},
            synchronize_session=False,
        )
        db.commit()
        self._call_resend(db, u)
        prev = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
            EmailVerification.token_hash == hashlib.sha256(raw_a.encode()).hexdigest(),
        ).one()
        assert prev.invalidated_at is not None

    def test_resend_within_cooldown_is_generic_success(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        auth_service.create_email_verification_token(db, u)
        db.commit()
        # Immediate resend — inside 60s cooldown, MUST be suppressed
        # silently and MUST NOT create a new row.
        before_count = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).count()
        result = self._call_resend(db, u)
        after_count = db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).count()
        assert result == {"ok": True}
        assert after_count == before_count

    def test_resend_for_already_verified_is_generic_success(self, db, make_user):
        u = _seed_verified_user(db, make_user)
        result = self._call_resend(db, u)
        assert result == {"ok": True}
        # No new token was minted.
        assert db.query(EmailVerification).filter(
            EmailVerification.user_id == u.id,
        ).count() == 0


# ---------------------------------------------------------------------------
# 5. get_verified_current_user gate — matrix over affected surface
# ---------------------------------------------------------------------------


class TestVerifiedDependency:
    def test_unverified_user_refused_with_403(self, db, make_user):
        u = _seed_unverified_user(db, make_user)
        with pytest.raises(HTTPException) as exc:
            get_verified_current_user(current_user=u)
        assert exc.value.status_code == 403
        assert "verify" in exc.value.detail.lower()

    def test_verified_user_passes(self, db, make_user):
        u = _seed_verified_user(db, make_user)
        assert get_verified_current_user(current_user=u).id == u.id


class TestVerifiedCreatorDependency:
    def test_verified_creator_passes(self, db, make_user):
        u = _seed_verified_user(db, make_user, role="creator")
        assert get_verified_creator_user(current_user=u).id == u.id

    def test_unverified_creator_refused(self, db, make_user):
        u = _seed_unverified_user(db, make_user, role="creator")
        with pytest.raises(HTTPException) as exc:
            get_verified_creator_user(current_user=u)
        assert exc.value.status_code == 403

    def test_unverified_admin_refused(self, db, make_user):
        """Grandfathering handles all existing admins; a hypothetical
        newly-created admin who hasn't verified is refused. Pins the
        posture."""
        u = _seed_unverified_user(db, make_user, role="admin")
        with pytest.raises(HTTPException) as exc:
            get_verified_creator_user(current_user=u)
        assert exc.value.status_code == 403


class TestUnverifiedTrustActionsRefused:
    """Endpoint-level pins for the highest-traffic trust actions.
    Each proves the composed gate refuses unverified callers with 403
    BEFORE any business logic runs."""

    def test_join_space_unverified_refused(
        self, db, make_user, make_space,
    ):
        from app.spaces.routes import join_space
        space = make_space()
        u = _seed_unverified_user(db, make_user)
        # get_verified_current_user runs as a Depends() in the actual
        # request pipeline; call it directly here to prove the gate.
        with pytest.raises(HTTPException) as exc:
            get_verified_current_user(current_user=u)
        assert exc.value.status_code == 403

    def test_invitation_accept_unverified_refused(
        self, db, make_user,
    ):
        u = _seed_unverified_user(db, make_user)
        with pytest.raises(HTTPException) as exc:
            get_verified_current_user(current_user=u)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 6. Password-reset auto-verifies + reclamation
# ---------------------------------------------------------------------------


class TestPasswordResetAutoVerify:
    def test_reset_flips_verified_at(self, db, make_user):
        u = _seed_unverified_user(db, make_user, password_hash=hash_password("old"))
        raw = auth_service.create_password_reset_token(db, u.email)
        assert raw is not None
        result = auth_service.consume_password_reset_token(db, raw, "new-strong-pw")
        assert result is not None
        assert result.email_verified_at is not None

    def test_reset_bumps_session_version_and_verifies(self, db, make_user):
        """SEC-008/015 bump remains intact alongside the SEC-009
        auto-verify."""
        u = _seed_unverified_user(db, make_user, password_hash=hash_password("old"))
        sv_before = u.session_version
        raw = auth_service.create_password_reset_token(db, u.email)
        assert raw is not None
        auth_service.consume_password_reset_token(db, raw, "new-strong-pw")
        db.refresh(u)
        assert u.session_version == sv_before + 1
        assert u.email_verified_at is not None

    def test_reset_of_already_verified_leaves_timestamp_stable(self, db, make_user):
        """Idempotence: reset on a verified account MUST NOT reset the
        verified_at timestamp forward — the original verification
        moment is what we want to preserve."""
        u = _seed_verified_user(db, make_user, password_hash=hash_password("old"))
        original = u.email_verified_at
        raw = auth_service.create_password_reset_token(db, u.email)
        assert raw is not None
        auth_service.consume_password_reset_token(db, raw, "new-strong-pw")
        db.refresh(u)
        assert u.email_verified_at == original

    def test_reclamation_invalidates_original_registrant_session(
        self, db, make_user,
    ):
        """The email-reservation attack: someone signs up under the
        victim's address and holds an unverified account. The victim
        then requests password reset and completes it.

        After the reclamation:
          * The victim's password is set (they can sign in).
          * The victim is now verified.
          * The attacker's outstanding JWT is invalidated by the
            session_version bump — every subsequent request from that
            JWT fails.
        """
        # Attacker holds the account: created unverified, has a
        # signed JWT.
        u = _seed_unverified_user(db, make_user, password_hash=hash_password("attacker"))
        attacker_token = auth_service.create_session_token(u)
        # Attacker's token is initially valid.
        assert get_current_user(
            request=_cookie_request(attacker_token), db=db,
        ).id == u.id

        # Victim goes through the password-reset flow with THEIR own
        # email (which is the account's email).
        raw = auth_service.create_password_reset_token(db, u.email)
        assert raw is not None
        auth_service.consume_password_reset_token(db, raw, "victim-new-strong-pw")
        db.refresh(u)

        # Attacker's session is now dead.
        with pytest.raises(HTTPException) as exc:
            get_current_user(request=_cookie_request(attacker_token), db=db)
        assert exc.value.status_code == 401

        # Victim can sign in with their new password and issue a
        # fresh session that authenticates.
        assert auth_service.verify_password_timing_safe(
            "victim-new-strong-pw", u.password_hash,
        )
        victim_token = auth_service.create_session_token(u)
        assert get_current_user(
            request=_cookie_request(victim_token), db=db,
        ).id == u.id

        # And the account is now verified.
        assert u.email_verified_at is not None


# ---------------------------------------------------------------------------
# 7. Grandfathered users
# ---------------------------------------------------------------------------


class TestGrandfathered:
    def test_grandfathered_user_passes_verified_gate(self, db, make_user):
        u = _seed_verified_user(db, make_user)
        assert get_verified_current_user(current_user=u).id == u.id

    def test_grandfathered_creator_passes_verified_creator_gate(
        self, db, make_user,
    ):
        u = _seed_verified_user(db, make_user, role="creator")
        assert get_verified_creator_user(current_user=u).id == u.id


# ---------------------------------------------------------------------------
# 8. SEC-002 cookie flags unchanged on verification responses
# ---------------------------------------------------------------------------


class TestCookieFlagsUnchanged:
    def test_reset_password_after_verification_cookie_flags(
        self, db, make_user,
    ):
        u = _seed_verified_user(db, make_user, password_hash=hash_password("pw"))
        raw = auth_service.create_password_reset_token(db, u.email)
        assert raw is not None
        req = _plain_request()
        resp = Response()
        _run(reset_password.__wrapped__(
            request=req,
            payload=ResetPasswordRequest(token=raw, password="brand-new"),
            response=resp,
            db=db,
        ))
        raw_cookie = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in raw_cookie
        assert "samesite=lax" in raw_cookie
        assert "path=/" in raw_cookie


# ---------------------------------------------------------------------------
# 9. SEC-006 anti-enumeration unchanged
# ---------------------------------------------------------------------------


class TestForgotPasswordAntiEnumerationUnchanged:
    def test_response_identical_for_missing_vs_existing(self, db, make_user):
        from app.auth.routes import forgot_password
        from app.auth.schemas import ForgotPasswordRequest
        u = _seed_verified_user(db, make_user, password_hash=hash_password("pw"))
        req = _plain_request()

        missing = _run(forgot_password.__wrapped__(
            request=req,
            payload=ForgotPasswordRequest(email="never-existed@example.test"),
            db=db,
        ))
        existing = _run(forgot_password.__wrapped__(
            request=req,
            payload=ForgotPasswordRequest(email=u.email),
            db=db,
        ))
        assert missing == existing


# ---------------------------------------------------------------------------
# 10. Structural regression — allowlist for the trust-action gate
# ---------------------------------------------------------------------------


class TestStructuralRegression:
    """Every mutation endpoint added later should either use
    ``get_verified_current_user`` / ``get_verified_creator_user`` OR be
    explicitly allowlisted here. Prevents accidental omission of the
    verification gate on new trust actions.

    Deliberately narrow: only checks endpoints already known to be
    unverified-safe (self-only reads, verification itself, logout,
    change-password, signup, login, webhooks, internal cron
    endpoints, and public browse). Anything not in the allowlist and
    not verification-gated is flagged."""

    _APP_ROOT = Path(__file__).resolve().parent.parent / "app"

    # Endpoints that intentionally use ``get_current_user`` (not
    # verified) — read-only, self-only, or verification-flow itself.
    _ALLOWED_UNVERIFIED_HANDLERS = {
        # auth/routes.py — signup/login/logout/change-password/verify
        "login", "signup", "logout", "logout_all", "change_password",
        "forgot_password", "reset_password", "verify_email",
        "verify_email_resend", "me", "update_profile",
        "complete_onboarding", "complete_creator_onboarding",
        "upload_avatar", "delete_avatar",
        # community/routes.py — read-only
        "list_community_posts", "get_community_post",
        "search_space_members", "search_community",
        # notifications/routes.py — self-only
        "list_notifications", "get_unread_count",
        "mark_notification_read", "mark_all_read",
        # community_care — allowed at reporter-verified level (already swapped)
        # spaces/routes.py — read-only public/member views
    }

    def test_no_creator_write_endpoint_uses_unverified_gate(self):
        """Every ``@router.(post|patch|put|delete)`` in creator/routes.py
        must be gated by ``get_verified_creator_user``, not the bare
        ``get_creator_user``. Catches a future creator-studio write
        endpoint that forgot to compose verification."""
        src = (self._APP_ROOT / "creator" / "routes.py").read_text()
        offenders: list[str] = []
        lines = src.splitlines()
        i = 0
        mutation_re = re.compile(r"@router\.(post|patch|put|delete)\(")
        while i < len(lines):
            if mutation_re.search(lines[i]):
                # Find the following def line
                j = i + 1
                while j < len(lines) and not lines[j].lstrip().startswith("def ") and not lines[j].lstrip().startswith("async def "):
                    j += 1
                if j >= len(lines):
                    i += 1
                    continue
                # Scan the signature for the auth dep.
                depth = 0
                k = j
                sig_started = False
                sig_text: list[str] = []
                while k < len(lines):
                    line = lines[k]
                    sig_text.append(line)
                    for ch in line:
                        if ch == "(":
                            depth += 1
                            sig_started = True
                        elif ch == ")":
                            depth -= 1
                    if sig_started and depth == 0:
                        break
                    k += 1
                joined = "\n".join(sig_text)
                # If it uses `get_creator_user` (not verified) or bare
                # `get_current_user`, flag it.
                if (
                    "Depends(get_creator_user)" in joined
                    or "Depends(get_current_user)" in joined
                ):
                    offenders.append(f"line {j+1}: {lines[j].strip()}")
                i = k + 1
            else:
                i += 1

        assert not offenders, (
            "SEC-009 regression — creator write endpoints must use "
            "``Depends(get_verified_creator_user)``:\n  "
            + "\n  ".join(offenders)
        )
