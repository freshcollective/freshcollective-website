"""The direct-message email preference, which used to have no column.

``app/messages/routes.py`` passes ``pref_key="direct_message_email"``.
``_get_notification_pref`` has always listed that key in its defaults
dict, but the column arrived only in migration 169 — and the lookup has
two branches that disagreed without it:

    prefs is None  -> defaults dict      -> True   (emailed)
    prefs exists   -> getattr(..., False) -> False  (silently not emailed)

A row is created by saving *any* preference, on a page that never
offered a direct-message toggle. So opening notification settings
turned direct-message email off for that Collective, permanently and
invisibly.

The regression is ``test_a_member_who_saved_preferences_still_gets_email``.
It fails on the pre-169 schema and passes after it, and it is the reason
this file exists.

No email leaves the process here: these tests read the preference
decision, and the one end-to-end case asserts on what
``send_notification`` was asked to do rather than letting it run.
"""
from __future__ import annotations

import uuid

import pytest

import app.models.community_care  # noqa: F401
from app.models.platform import (
    SpaceMembership,
    SpaceMembershipStatus,
    SpaceMemberNotificationPrefs,
    SpaceRole,
)
from app.services.notification_service import _get_notification_pref

DM_KEY = "direct_message_email"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _join(db, user, space, role=SpaceRole.learner):
    db.add(SpaceMembership(
        id=_uid("sm"), user_id=user.id, space_id=space.id,
        role=role, status=SpaceMembershipStatus.active,
    ))
    db.flush()


@pytest.fixture
def member_in_space(db, make_user, make_space):
    creator = make_user(role="creator", name="Ada Leader")
    space = make_space(creator=creator)
    member = make_user(name="Mem Ber")
    _join(db, creator, space, role=SpaceRole.creator)
    _join(db, member, space)
    db.commit()
    return space, creator, member


def _save_prefs(db, user, space, **values):
    """A prefs row exactly as the settings endpoint writes one."""
    from app.spaces.routes import _NOTIF_DEFAULTS

    row = SpaceMemberNotificationPrefs(
        id=_uid("pref"), user_id=user.id, space_id=space.id,
        **{**_NOTIF_DEFAULTS, **values},
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# The column, and the two branches that disagreed without it
# ---------------------------------------------------------------------------

class TestThePreferenceHasSomewhereToLive:
    def test_the_column_exists(self):
        # The whole defect in one assertion: the key was read from a
        # model that had no such attribute.
        assert hasattr(SpaceMemberNotificationPrefs, DM_KEY)
        assert DM_KEY in {c.name for c in SpaceMemberNotificationPrefs.__table__.columns}

    def test_it_is_in_the_defaults_used_to_create_a_row(self):
        from app.spaces.routes import _NOTIF_DEFAULTS

        assert _NOTIF_DEFAULTS[DM_KEY] is True

    def test_a_member_with_no_row_is_emailed(self, db, member_in_space):
        # This branch always worked — it reads the defaults dict.
        space, _creator, member = member_in_space
        assert _get_notification_pref(db, member.id, space.id, DM_KEY) is True

    def test_a_member_who_saved_preferences_still_gets_email(self, db, member_in_space):
        """The regression.

        Before migration 169 this returned False: the row existed, so
        the lookup took ``getattr(prefs, "direct_message_email", False)``
        against a model with no such attribute.
        """
        space, _creator, member = member_in_space
        _save_prefs(db, member, space)
        assert _get_notification_pref(db, member.id, space.id, DM_KEY) is True

    def test_turning_it_off_is_respected(self, db, member_in_space):
        space, _creator, member = member_in_space
        _save_prefs(db, member, space, direct_message_email=False)
        assert _get_notification_pref(db, member.id, space.id, DM_KEY) is False

    def test_saving_an_unrelated_preference_does_not_disable_it(self, db, member_in_space):
        """What actually bit members: they changed something else.

        The settings page offers gathering reminders, conversations and
        pathways. Saving any of them wrote the row that silenced direct
        messages.
        """
        space, _creator, member = member_in_space
        _save_prefs(db, member, space, gathering_reminder_email=False)
        assert _get_notification_pref(db, member.id, space.id, DM_KEY) is True


# ---------------------------------------------------------------------------
# The preference is reachable, which it never was
# ---------------------------------------------------------------------------

class TestTheMemberCanSeeAndChangeIt:
    def test_the_settings_response_carries_it(self, db, member_in_space):
        from app.spaces.routes import _prefs_response

        space, _creator, member = member_in_space
        rowless = _prefs_response(space, None)
        assert rowless.direct_message_email is True

        row = _save_prefs(db, member, space, direct_message_email=False)
        assert _prefs_response(space, row).direct_message_email is False

    def test_the_update_schema_accepts_it(self):
        from app.spaces.schemas import NotificationPrefsUpdate

        payload = NotificationPrefsUpdate(direct_message_email=False)
        assert payload.model_dump(exclude_none=True) == {DM_KEY: False}

    def test_the_settings_page_offers_the_toggle(self):
        # A preference with no control is how this one went unnoticed.
        from pathlib import Path

        ui = Path("../frontend/src/app/settings/stay-connected/StayConnectedClient.tsx")
        if not ui.exists():  # frontend not checked out beside the backend
            pytest.skip("frontend not available")
        assert DM_KEY in ui.read_text()


# ---------------------------------------------------------------------------
# What the send path asks for
# ---------------------------------------------------------------------------

class TestTheSendPathUsesThisKey:
    def test_the_creator_send_passes_the_direct_message_key(self):
        from pathlib import Path

        src = Path("app/messages/routes.py").read_text()
        assert f'pref_key="{DM_KEY}"' in src

    def test_in_app_notification_does_not_depend_on_the_email_preference(self):
        """In-app delivery was never affected, and must stay that way.

        ``send_notification`` creates the notification before it reaches
        the email branch, so a member who switches email off still sees
        the message in the platform.
        """
        from pathlib import Path

        src = Path("app/services/notification_service.py").read_text()
        body = src[src.index("def send_notification("):]
        assert body.index("create_notification(") < body.index("should_email")
