"""Tests for the M2 preference / consent / member-settings layer.

Covers:
  * Effective preference resolution (default vs override).
  * Locked-channel refusal.
  * Preference upsert semantics + clear.
  * Consent grant/revoke append semantics.
  * Member settings upsert with partial updates.
  * The /api/comms/preferences/me matrix + PATCH behaviour.
  * Backfill logic — direct unit test against seeded old prefs.
"""

from __future__ import annotations

from datetime import time

import pytest
from fastapi import HTTPException

from app.comms.categories import (
    CATEGORY_ACCOUNT,
    CATEGORY_COMMUNITY,
    CATEGORY_PATHWAYS,
    Channel,
    Priority,
)
from app.comms.models import CommunicationConsent, CommunicationPreference
from app.comms.preferences import (
    LockedPreferenceError,
    UnsupportedChannelError,
    clear_preference,
    get_consent_state,
    get_effective_preference,
    get_member_settings,
    get_preference_matrix,
    grant_consent,
    revoke_consent,
    set_preference,
    update_member_settings,
)
from app.comms.routes import (
    get_my_consents,
    get_my_preferences,
    patch_my_preferences,
)
from app.comms.schemas import (
    ConsentUpdate,
    MemberSettingsPatch,
    MyPreferencesPatch,
    PreferenceUpdate,
)


def _load_migration_098():
    """Load the 098 migration module by file path — Alembic version
    files aren't a real Python package so plain ``import`` doesn't
    resolve. Cached inside importlib so repeated calls are cheap.
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "alembic" / "versions"
        / "098_communications_preferences_and_consents.py"
    )
    spec = importlib.util.spec_from_file_location("m098_backfill", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Effective preference resolution
# ---------------------------------------------------------------------------


class TestEffectivePreference:
    def test_defaults_apply_when_no_override(self, db, make_user):
        u = make_user()
        # Community × in-app defaults to enabled (immediate).
        priority, is_locked, origin = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.IN_APP,
        )
        assert priority == Priority.IMMEDIATE
        assert is_locked is False
        assert origin == "default"

    def test_community_email_default_is_silent(self, db, make_user):
        # From migration 097: community × email_transactional is
        # default_enabled=False → silent.
        u = make_user()
        priority, _, _ = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert priority == Priority.SILENT

    def test_override_wins_over_default(self, db, make_user):
        u = make_user()
        set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        priority, _, origin = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert priority == Priority.DAILY_DIGEST
        assert origin == "override"

    def test_locked_flag_exposed(self, db, make_user):
        u = make_user()
        # Account × in-app is locked in the seed.
        _, is_locked, _ = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_ACCOUNT,
            channel=Channel.IN_APP,
        )
        assert is_locked is True

    def test_unsupported_channel_raises(self, db, make_user):
        u = make_user()
        # Push is not offered for Account in the seed defaults? Actually
        # it IS in the seed but with default_enabled=False, so it's
        # supported. Use email_marketing on Account which is NOT seeded.
        with pytest.raises(UnsupportedChannelError):
            get_effective_preference(
                db,
                user_id=u.id,
                category_key=CATEGORY_ACCOUNT,
                channel=Channel.EMAIL_MARKETING,
            )


class TestSetPreference:
    def test_upsert_creates_and_updates(self, db, make_user):
        u = make_user()
        first = set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_PATHWAYS,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.WEEKLY_DIGEST,
        )
        second = set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_PATHWAYS,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        # Same row, updated in place.
        assert first.id == second.id
        assert second.priority == Priority.DAILY_DIGEST

    def test_locked_channel_refuses(self, db, make_user):
        u = make_user()
        with pytest.raises(LockedPreferenceError):
            set_preference(
                db,
                user_id=u.id,
                category_key=CATEGORY_ACCOUNT,
                channel=Channel.IN_APP,
                priority=Priority.SILENT,
            )

    def test_clear_removes_override(self, db, make_user):
        u = make_user()
        set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        removed = clear_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert removed is True
        # Back to default now.
        priority, _, origin = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert priority == Priority.SILENT
        assert origin == "default"

    def test_clear_returns_false_when_no_override(self, db, make_user):
        u = make_user()
        removed = clear_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert removed is False


# ---------------------------------------------------------------------------
# Matrix response
# ---------------------------------------------------------------------------


class TestPreferenceMatrix:
    def test_matrix_returns_all_nine_categories(self, db, make_user):
        u = make_user()
        matrix = get_preference_matrix(db, user_id=u.id)
        keys = [row["category_key"] for row in matrix]
        # Should include every category from the seed.
        for expected in [
            "account", "safety", "purchases", "messages", "gatherings",
            "pathways", "community", "creator_updates", "platform_updates",
        ]:
            assert expected in keys

    def test_matrix_sorted_by_sort_order(self, db, make_user):
        u = make_user()
        matrix = get_preference_matrix(db, user_id=u.id)
        sort_orders = [row["sort_order"] for row in matrix]
        assert sort_orders == sorted(sort_orders)

    def test_matrix_reflects_override(self, db, make_user):
        u = make_user()
        set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        matrix = get_preference_matrix(db, user_id=u.id)
        community = next(r for r in matrix if r["category_key"] == "community")
        email_cell = next(
            c for c in community["cells"]
            if c["channel"] == "email_transactional"
        )
        assert email_cell["priority"] == "daily_digest"
        assert email_cell["origin"] == "override"


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------


class TestConsent:
    def test_no_state_when_never_granted(self, db, make_user):
        u = make_user()
        state = get_consent_state(
            db, user_id=u.id, consent_kind="marketing",
        )
        assert state is None

    def test_grant_appends_row(self, db, make_user):
        u = make_user()
        row = grant_consent(
            db,
            user_id=u.id,
            consent_kind="marketing",
            source="test.settings.grant",
            policy_version="mkt.v1",
        )
        assert row.state == "granted"
        latest = get_consent_state(
            db, user_id=u.id, consent_kind="marketing",
        )
        assert latest is not None
        assert latest.state == "granted"

    def test_revoke_appends_and_supersedes(self, db, make_user):
        u = make_user()
        grant_consent(
            db,
            user_id=u.id,
            consent_kind="marketing",
            source="test.settings.grant",
        )
        revoke_consent(
            db,
            user_id=u.id,
            consent_kind="marketing",
            source="test.settings.revoke",
        )
        latest = get_consent_state(
            db, user_id=u.id, consent_kind="marketing",
        )
        assert latest is not None
        assert latest.state == "revoked"

    def test_history_preserved(self, db, make_user):
        from sqlalchemy import select
        u = make_user()
        grant_consent(
            db, user_id=u.id, consent_kind="marketing", source="grant-1",
        )
        revoke_consent(
            db, user_id=u.id, consent_kind="marketing", source="revoke-1",
        )
        grant_consent(
            db, user_id=u.id, consent_kind="marketing", source="grant-2",
        )
        rows = db.execute(
            select(CommunicationConsent).where(
                CommunicationConsent.user_id == u.id,
                CommunicationConsent.consent_kind == "marketing",
            )
        ).scalars().all()
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# Member settings
# ---------------------------------------------------------------------------


class TestMemberSettings:
    def test_no_row_returns_none(self, db, make_user):
        u = make_user()
        assert get_member_settings(db, user_id=u.id) is None

    def test_upsert_partial(self, db, make_user):
        u = make_user()
        row1 = update_member_settings(
            db, user_id=u.id, timezone="Australia/Sydney",
        )
        assert row1.timezone == "Australia/Sydney"
        assert row1.quiet_hours_start_local is None

        row2 = update_member_settings(
            db,
            user_id=u.id,
            quiet_hours_start_local=time(22, 0),
            quiet_hours_end_local=time(7, 0),
        )
        # Same row; timezone preserved.
        assert row2.timezone == "Australia/Sydney"
        assert row2.quiet_hours_start_local == time(22, 0)
        assert row2.quiet_hours_end_local == time(7, 0)

    def test_can_reset_field_to_none(self, db, make_user):
        u = make_user()
        update_member_settings(
            db, user_id=u.id, timezone="Australia/Sydney",
        )
        update_member_settings(db, user_id=u.id, timezone=None)
        row = get_member_settings(db, user_id=u.id)
        assert row is not None
        assert row.timezone is None

    def test_weekday_range_validation(self, db, make_user):
        u = make_user()
        with pytest.raises(ValueError):
            update_member_settings(
                db, user_id=u.id, weekly_digest_send_local_weekday=7,
            )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestPreferencesEndpoint:
    def test_get_returns_matrix_and_defaults(self, db, make_user):
        u = make_user()
        resp = get_my_preferences(db=db, current_user=u)  # type: ignore[arg-type]
        assert len(resp.categories) == 9
        assert resp.member_settings.timezone is None
        assert len(resp.consents) == 5
        # All consents start unset.
        assert all(c.state is None for c in resp.consents)

    def test_patch_preference(self, db, make_user):
        u = make_user()
        patch_my_preferences(
            body=MyPreferencesPatch(
                preferences=[
                    PreferenceUpdate(
                        category_key=CATEGORY_COMMUNITY,
                        channel=Channel.EMAIL_TRANSACTIONAL,
                        priority=Priority.DAILY_DIGEST,
                    ),
                ]
            ),
            db=db,
            current_user=u,  # type: ignore[arg-type]
        )
        priority, _, origin = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert priority == Priority.DAILY_DIGEST
        assert origin == "override"

    def test_patch_clear_preference(self, db, make_user):
        u = make_user()
        set_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
            priority=Priority.DAILY_DIGEST,
        )
        patch_my_preferences(
            body=MyPreferencesPatch(
                preferences=[
                    PreferenceUpdate(
                        category_key=CATEGORY_COMMUNITY,
                        channel=Channel.EMAIL_TRANSACTIONAL,
                        priority=None,
                    ),
                ]
            ),
            db=db,
            current_user=u,  # type: ignore[arg-type]
        )
        _, _, origin = get_effective_preference(
            db,
            user_id=u.id,
            category_key=CATEGORY_COMMUNITY,
            channel=Channel.EMAIL_TRANSACTIONAL,
        )
        assert origin == "default"

    def test_patch_locked_channel_rejected(self, db, make_user):
        u = make_user()
        with pytest.raises(HTTPException) as exc:
            patch_my_preferences(
                body=MyPreferencesPatch(
                    preferences=[
                        PreferenceUpdate(
                            category_key=CATEGORY_ACCOUNT,
                            channel=Channel.IN_APP,
                            priority=Priority.SILENT,
                        ),
                    ]
                ),
                db=db,
                current_user=u,  # type: ignore[arg-type]
            )
        assert exc.value.status_code == 400

    def test_patch_member_settings(self, db, make_user):
        u = make_user()
        patch_my_preferences(
            body=MyPreferencesPatch(
                member_settings=MemberSettingsPatch(
                    timezone="Australia/Sydney",
                    quiet_hours_start_local=time(22, 0),
                    quiet_hours_end_local=time(7, 0),
                ),
            ),
            db=db,
            current_user=u,  # type: ignore[arg-type]
        )
        settings = get_member_settings(db, user_id=u.id)
        assert settings is not None
        assert settings.timezone == "Australia/Sydney"
        assert settings.quiet_hours_start_local == time(22, 0)

    def test_patch_grants_consent(self, db, make_user):
        u = make_user()
        patch_my_preferences(
            body=MyPreferencesPatch(
                consents=[
                    ConsentUpdate(consent_kind="marketing", state="granted"),
                ]
            ),
            db=db,
            current_user=u,  # type: ignore[arg-type]
        )
        state = get_consent_state(
            db, user_id=u.id, consent_kind="marketing",
        )
        assert state is not None
        assert state.state == "granted"

    def test_get_consents_endpoint(self, db, make_user):
        u = make_user()
        grant_consent(
            db, user_id=u.id, consent_kind="marketing", source="test",
        )
        db.flush()
        rows = get_my_consents(db=db, current_user=u)  # type: ignore[arg-type]
        by_kind = {r.consent_kind: r for r in rows}
        assert by_kind["marketing"].state == "granted"
        assert by_kind["terms_of_service"].state is None


# ---------------------------------------------------------------------------
# Backfill — unit test the resolution logic directly
# ---------------------------------------------------------------------------


class TestBackfillLogic:
    """Exercise the migration's ``_resolve_priority`` on synthetic
    per-space rows. The DB side of the migration is exercised by the
    ``alembic upgrade`` at test-schema-bootstrap time.
    """

    def test_new_post_email_true_wins_immediate(self):
        m098 = _load_migration_098()
        rules = m098.BACKFILL_RULES[("community", "email_transactional")]
        rows = [
            {"new_post_email": True, "weekly_digest_email": True},
        ]
        assert m098._resolve_priority(rows, rules) == "immediate"

    def test_only_daily_digest_true_yields_daily(self):
        m098 = _load_migration_098()
        rules = m098.BACKFILL_RULES[("community", "email_transactional")]
        rows = [
            {"daily_digest_email": True},
        ]
        assert m098._resolve_priority(rows, rules) == "daily_digest"

    def test_only_weekly_digest_true_yields_weekly(self):
        m098 = _load_migration_098()
        rules = m098.BACKFILL_RULES[("community", "email_transactional")]
        rows = [
            {"weekly_digest_email": True},
        ]
        assert m098._resolve_priority(rows, rules) == "weekly_digest"

    def test_no_matching_rows_returns_none(self):
        m098 = _load_migration_098()
        rules = m098.BACKFILL_RULES[("community", "email_transactional")]
        rows = [
            {"new_post_email": False, "weekly_digest_email": False},
        ]
        assert m098._resolve_priority(rows, rules) is None

    def test_push_requires_master_and_topic_switch(self):
        m098 = _load_migration_098()
        rules = m098.BACKFILL_RULES[("gatherings", "push")]
        # Only master enabled — not enough.
        assert m098._resolve_priority(
            [{"push_enabled": True, "push_gathering_reminders": False}],
            rules,
        ) is None
        # Only topic switch — not enough.
        assert m098._resolve_priority(
            [{"push_enabled": False, "push_gathering_reminders": True}],
            rules,
        ) is None
        # Both — immediate.
        assert m098._resolve_priority(
            [{"push_enabled": True, "push_gathering_reminders": True}],
            rules,
        ) == "immediate"

    def test_immediate_wins_across_multiple_rows(self):
        m098 = _load_migration_098()
        # Two different spaces: one has immediate on, one has only weekly.
        # Result: immediate wins (aggregated across the user's spaces).
        rules = m098.BACKFILL_RULES[("community", "email_transactional")]
        rows = [
            {"weekly_digest_email": True},
            {"new_post_email": True},
        ]
        assert m098._resolve_priority(rows, rules) == "immediate"
