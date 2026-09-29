"""The Connect account state model, tested against recorded Stripe shapes.

The two headline fixtures are not invented. ``V2_BEFORE_ONBOARDING`` and
``V2_AFTER_ONBOARDING`` reproduce the objects Stripe actually returned for
a recipient + express test account either side of Stripe-hosted
onboarding, and ``V1_BEFORE`` / ``V1_AFTER`` the matching v1 accounts. The
narrower cases below vary one field at a time from those shapes to pin the
precedence rules.

The precedence is what this file mostly exists to protect, because two
orderings are easy to get wrong and both are silent when wrong:

* ``transfers_only`` before ``action_required`` — an account with live
  transfers and an outstanding bank account matches both, and only one of
  them says the thing that matters.
* terminal states before everything — an unsupported account must never be
  described as merely needing attention.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.creator_stripe_account import (
    CreatorStripeAccount,
    OnboardingState,
)
from app.services.connect_account_state import (
    derive_onboarding_state,
    project,
)

ACCT = "acct_1UKvYtIZ2nlCECxa"


# ---------------------------------------------------------------------------
# Recorded shapes
# ---------------------------------------------------------------------------


def _entry(description: str, *, awaiting: str = "user", restricts=("payouts", "stripe_transfers")):
    return {
        "awaiting_action_from": awaiting,
        "description": description,
        "errors": [],
        "impact": {
            "restricts_capabilities": [
                {
                    "capability": f"stripe_balance.{c}",
                    "configuration": "recipient",
                    "deadline": {"status": "past_due"},
                }
                for c in restricts
            ]
        },
        "minimum_deadline": {"status": "past_due"},
        "requested_reasons": [{"code": "routine_onboarding"}],
    }


#: The 13 requirements Stripe listed on a fresh AU individual account.
#: ``external_account`` restricts payouts only — that asymmetry is the
#: whole reason ``transfers_only`` exists.
_BEFORE_ENTRIES = [
    _entry("defaults.profile.business_url"),
    _entry("external_account", restricts=("payouts",)),
    _entry("identity.attestations.terms_of_service.account.date"),
    _entry("identity.attestations.terms_of_service.account.ip"),
    _entry("identity.individual.address.city"),
    _entry("identity.individual.address.line1"),
    _entry("identity.individual.address.postal_code"),
    _entry("identity.individual.address.state"),
    _entry("identity.individual.date_of_birth.day"),
    _entry("identity.individual.date_of_birth.month"),
    _entry("identity.individual.date_of_birth.year"),
    _entry("identity.individual.given_name"),
    _entry("identity.individual.surname"),
]

_RESTRICTED_CAP = {
    "status": "restricted",
    "status_details": [{"code": "requirements_past_due", "resolution": "provide_info"}],
}
_ACTIVE_CAP = {"status": "active", "status_details": []}


def _v2(*, transfers, payouts, entries, closed=False, summary="past_due"):
    return {
        "id": ACCT,
        "object": "v2.core.account",
        "applied_configurations": ["recipient"],
        "closed": closed,
        "dashboard": "express",
        "configuration": {
            "customer": None,
            "merchant": None,
            "recipient": {
                "applied": True,
                "capabilities": {
                    "stripe_balance": {"payouts": payouts, "stripe_transfers": transfers}
                },
            },
        },
        "defaults": {
            "currency": "aud",
            "responsibilities": {
                "fees_collector": "application",
                "losses_collector": "application",
                "requirements_collector": "stripe",
            },
        },
        "requirements": (
            {"entries": entries, "summary": {"minimum_deadline": {"status": summary, "time": None}}}
            if entries or summary
            else {"entries": [], "summary": None}
        ),
        "livemode": False,
    }


V2_BEFORE_ONBOARDING = _v2(
    transfers=_RESTRICTED_CAP, payouts=_RESTRICTED_CAP, entries=_BEFORE_ENTRIES,
)
V2_AFTER_ONBOARDING = _v2(
    transfers=_ACTIVE_CAP, payouts=_ACTIVE_CAP, entries=[], summary=None,
)

V1_BEFORE = {
    "id": ACCT,
    "type": "none",
    "charges_enabled": False,
    "payouts_enabled": False,
    "details_submitted": False,
    "capabilities": {"transfers": "inactive"},
    "requirements": {
        "disabled_reason": "requirements.past_due",
        "currently_due": [e["description"] for e in _BEFORE_ENTRIES],
        "pending_verification": [],
    },
    # Observed verbatim: total_count is null while no bank account exists.
    "external_accounts": {"object": "list", "total_count": None, "data": []},
    "settings": {
        "payouts": {
            "debit_negative_balances": True,
            "schedule": {"delay_days": 2, "interval": "daily"},
            "statement_descriptor": None,
        }
    },
}

V1_AFTER = {
    "id": ACCT,
    "type": "none",
    "charges_enabled": False,
    "payouts_enabled": True,
    "details_submitted": True,
    "capabilities": {"transfers": "active"},
    "requirements": {
        "disabled_reason": None,
        "currently_due": [],
        "pending_verification": [],
    },
    "external_accounts": {
        "object": "list",
        "total_count": 1,
        "data": [{
            "object": "bank_account",
            "bank_name": "STRIPE TEST BANK",
            "last4": "3456",
            "currency": "aud",
            "status": "new",
            "default_for_currency": True,
        }],
    },
    "settings": {
        "payouts": {
            "debit_negative_balances": True,
            "schedule": {"delay_days": 2, "interval": "daily"},
        }
    },
}


def _state(**kwargs) -> str:
    kwargs.setdefault("stripe_account_id", ACCT)
    return derive_onboarding_state(**kwargs)


# ---------------------------------------------------------------------------
# 1. No row / no account id
# ---------------------------------------------------------------------------


def test_no_account_id_is_not_started():
    assert derive_onboarding_state(stripe_account_id=None, v2=None, v1=None) == \
        OnboardingState.not_started.value


def test_no_account_id_projects_empty_without_touching_stripe_shapes():
    """A row that exists but has no Stripe account yet still projects
    cleanly — the create call may have failed, and that row must render."""
    p = project(stripe_account_id=None)
    assert p.onboarding_state == OnboardingState.not_started.value
    assert p.transfers_status is None and p.payouts_status is None
    assert p.transfers_enabled is False and p.payouts_enabled is False
    assert p.currently_due_json == []
    assert p.external_account_count == 0


def test_empty_string_account_id_is_treated_as_absent():
    assert _state(stripe_account_id="", v2=V2_AFTER_ONBOARDING, v1=V1_AFTER) == \
        OnboardingState.not_started.value


# ---------------------------------------------------------------------------
# 2. The recorded transition
# ---------------------------------------------------------------------------


def test_recorded_before_onboarding_is_onboarding():
    assert _state(v2=V2_BEFORE_ONBOARDING, v1=V1_BEFORE) == \
        OnboardingState.onboarding.value


def test_recorded_after_onboarding_is_ready():
    assert _state(v2=V2_AFTER_ONBOARDING, v1=V1_AFTER) == OnboardingState.ready.value


def test_projection_of_the_recorded_before_state():
    p = project(stripe_account_id=ACCT, v2=V2_BEFORE_ONBOARDING, v1=V1_BEFORE)

    assert p.onboarding_state == OnboardingState.onboarding.value
    assert p.transfers_status == "restricted"
    assert p.transfers_status_codes == ["requirements_past_due"]
    assert p.payouts_status == "restricted"
    assert p.payouts_status_codes == ["requirements_past_due"]
    assert p.transfers_enabled is False
    assert p.payouts_enabled is False
    assert p.details_submitted is False

    assert len(p.currently_due_json) == 13
    # The entry that makes transfers_only possible.
    external = next(
        e for e in p.currently_due_json if e["description"] == "external_account"
    )
    assert external["restricts_capabilities"] == ["stripe_balance.payouts"]
    assert external["awaiting_action_from"] == "user"

    # total_count was null here; the data length is the reliable reading.
    assert p.external_account_count == 0
    assert p.payout_interval == "daily"
    assert p.payout_delay_days == 2
    assert p.debit_negative_balances is True
    assert p.dashboard == "express"
    assert p.fees_collector == "application"
    assert p.losses_collector == "application"
    # Set by Stripe, not by FC — it follows from dashboard=express.
    assert p.requirements_collector == "stripe"


def test_projection_of_the_recorded_after_state():
    p = project(stripe_account_id=ACCT, v2=V2_AFTER_ONBOARDING, v1=V1_AFTER)

    assert p.onboarding_state == OnboardingState.ready.value
    assert p.transfers_status == "active"
    assert p.payouts_status == "active"
    assert p.transfers_status_codes == []
    assert p.payouts_status_codes == []
    assert p.transfers_enabled is True
    assert p.payouts_enabled is True
    assert p.details_submitted is True
    assert p.currently_due_json == []
    assert p.requirements_deadline is None
    assert p.external_account_count == 1
    # Unchanged by onboarding — the schedule exists from account creation.
    assert p.payout_interval == "daily"
    assert p.payout_delay_days == 2


# ---------------------------------------------------------------------------
# 3. transfers_only — and its precedence over action_required
# ---------------------------------------------------------------------------


def test_transfers_active_without_payouts_is_transfers_only():
    v2 = _v2(
        transfers=_ACTIVE_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[_entry("external_account", restricts=("payouts",))],
    )
    assert _state(v2=v2, v1={**V1_AFTER, "payouts_enabled": False}) == \
        OnboardingState.transfers_only.value


def test_transfers_only_wins_over_action_required():
    """Both rules match here. If ``action_required`` won, FC would tell a
    creator "more information needed" while quietly transferring money into
    a balance that cannot pay out."""
    v2 = _v2(
        transfers=_ACTIVE_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[_entry("external_account", awaiting="user", restricts=("payouts",))],
    )
    v1 = {**V1_AFTER, "details_submitted": True, "payouts_enabled": False}
    assert _state(v2=v2, v1=v1) == OnboardingState.transfers_only.value


def test_transfers_only_is_reflected_in_the_derived_booleans():
    v2 = _v2(transfers=_ACTIVE_CAP, payouts=_RESTRICTED_CAP, entries=[])
    p = project(stripe_account_id=ACCT, v2=v2, v1={**V1_AFTER, "payouts_enabled": False})
    assert p.transfers_enabled is True
    assert p.payouts_enabled is False


# ---------------------------------------------------------------------------
# 4. verifying vs action_required, via awaiting_action_from
# ---------------------------------------------------------------------------


def test_pending_capability_is_verifying():
    pending = {"status": "pending", "status_details": []}
    assert _state(v2=_v2(transfers=pending, payouts=pending, entries=[]), v1=V1_BEFORE) == \
        OnboardingState.verifying.value


def test_pending_verification_code_is_verifying():
    cap = {
        "status": "restricted",
        "status_details": [
            {"code": "requirements_pending_verification", "resolution": "provide_info"}
        ],
    }
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_AFTER) == \
        OnboardingState.verifying.value


def test_determining_status_code_is_verifying():
    cap = {
        "status": "restricted",
        "status_details": [{"code": "determining_status", "resolution": "provide_info"}],
    }
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_AFTER) == \
        OnboardingState.verifying.value


def test_entries_awaiting_stripe_only_is_verifying_not_action_required():
    """The distinction the whole design rests on. Same requirement count,
    same statuses, same ``details_submitted`` — only
    ``awaiting_action_from`` differs, and it flips the answer."""
    v2 = _v2(
        transfers=_RESTRICTED_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[_entry("identity.individual.verification.document", awaiting="stripe")],
    )
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.verifying.value


def test_entries_awaiting_user_after_submission_is_action_required():
    v2 = _v2(
        transfers=_RESTRICTED_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[_entry("identity.individual.verification.document", awaiting="user")],
    )
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.action_required.value


def test_mixed_awaiting_prefers_action_required_over_verifying():
    """If anything is waiting on the creator, say so — a half-true
    "we're checking" leaves them waiting on Stripe forever."""
    v2 = _v2(
        transfers=_RESTRICTED_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[
            _entry("identity.individual.verification.document", awaiting="stripe"),
            _entry("identity.individual.address.line1", awaiting="user"),
        ],
    )
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.action_required.value


def test_same_requirements_before_submission_is_onboarding_not_action_required():
    """``details_submitted`` is the only difference from the test above,
    and it is v1-only — which is why the projection needs both APIs."""
    v2 = _v2(
        transfers=_RESTRICTED_CAP,
        payouts=_RESTRICTED_CAP,
        entries=[_entry("identity.individual.address.line1", awaiting="user")],
    )
    assert _state(v2=v2, v1={**V1_BEFORE, "details_submitted": False}) == \
        OnboardingState.onboarding.value


# ---------------------------------------------------------------------------
# 5. unsupported vs restricted / contact_stripe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", [
    "unsupported_business", "unsupported_country", "unsupported_entity_type",
])
def test_terminal_codes_are_unsupported(code):
    cap = {"status": "restricted", "status_details": [{"code": code, "resolution": "no_resolution"}]}
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_BEFORE) == \
        OnboardingState.unsupported.value


def test_unsupported_status_is_unsupported():
    cap = {"status": "unsupported", "status_details": []}
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_BEFORE) == \
        OnboardingState.unsupported.value


def test_no_resolution_is_unsupported_whatever_the_code():
    cap = {
        "status": "restricted",
        "status_details": [{"code": "restricted_other", "resolution": "no_resolution"}],
    }
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_BEFORE) == \
        OnboardingState.unsupported.value


def test_restricted_other_with_contact_stripe_is_restricted():
    cap = {
        "status": "restricted",
        "status_details": [{"code": "restricted_other", "resolution": "contact_stripe"}],
    }
    assert _state(v2=_v2(transfers=cap, payouts=cap, entries=[]), v1=V1_AFTER) == \
        OnboardingState.restricted.value


def test_unsupported_beats_restricted_when_both_present():
    """Never invite a retry the creator cannot win."""
    v2 = _v2(
        transfers={
            "status": "restricted",
            "status_details": [{"code": "restricted_other", "resolution": "contact_stripe"}],
        },
        payouts={
            "status": "unsupported",
            "status_details": [{"code": "unsupported_country", "resolution": "no_resolution"}],
        },
        entries=[],
    )
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.unsupported.value


def test_payouts_unsupported_blocks_even_when_transfers_are_active():
    """FC must not take money it can never forward."""
    v2 = _v2(
        transfers=_ACTIVE_CAP,
        payouts={"status": "unsupported", "status_details": []},
        entries=[],
    )
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.unsupported.value


# ---------------------------------------------------------------------------
# 6. closed
# ---------------------------------------------------------------------------


def test_closed_account_is_closed_even_when_fully_active():
    v2 = _v2(transfers=_ACTIVE_CAP, payouts=_ACTIVE_CAP, entries=[], closed=True)
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.closed.value


def test_closed_is_checked_before_unsupported():
    cap = {"status": "unsupported", "status_details": []}
    v2 = _v2(transfers=cap, payouts=cap, entries=[], closed=True)
    assert _state(v2=v2, v1=V1_BEFORE) == OnboardingState.closed.value


# ---------------------------------------------------------------------------
# 7. Fallback and tolerance
# ---------------------------------------------------------------------------


def test_unrecognised_combination_falls_back_to_restricted():
    """Withholding routing is the safe default for a shape we don't
    understand; anything reassuring would be a guess."""
    v2 = _v2(transfers=_RESTRICTED_CAP, payouts=_RESTRICTED_CAP, entries=[])
    assert _state(v2=v2, v1=V1_AFTER) == OnboardingState.restricted.value


def test_missing_v2_sub_objects_do_not_raise():
    """Absent sub-objects come back as null from Stripe routinely — an
    account retrieved without ``include`` has no configuration at all.

    The answer is ``onboarding``: with no v1 object there is no evidence of
    submission, and nothing in the v2 object claims a restriction. What
    matters is that it neither raises nor returns anything routable.
    """
    state = _state(v2={"id": ACCT, "configuration": None, "requirements": None}, v1=None)
    assert state == OnboardingState.onboarding.value
    assert state not in {
        OnboardingState.ready.value, OnboardingState.transfers_only.value,
    }


def test_no_v1_object_never_yields_a_routable_state():
    """v1 carries ``details_submitted`` and the external-account count, so a
    projection built from v2 alone must not be able to reach ``ready``."""
    for v2 in (V2_AFTER_ONBOARDING, V2_BEFORE_ONBOARDING):
        p = project(stripe_account_id=ACCT, v2=v2, v1=None)
        assert p.details_submitted is False
        assert p.external_account_count == 0
        assert p.onboarding_state != OnboardingState.action_required.value


def test_requirements_deadline_is_parsed_when_present():
    v2 = _v2(transfers=_RESTRICTED_CAP, payouts=_RESTRICTED_CAP, entries=_BEFORE_ENTRIES)
    v2["requirements"]["summary"] = {
        "minimum_deadline": {"status": "currently_due", "time": "2026-10-15T09:30:00.000Z"}
    }
    p = project(stripe_account_id=ACCT, v2=v2, v1=V1_BEFORE)
    assert p.requirements_deadline == datetime(2026, 10, 15, 9, 30, 0)


def test_external_account_count_prefers_total_count_when_numeric():
    v1 = {**V1_AFTER, "external_accounts": {"total_count": 3, "data": []}}
    assert project(stripe_account_id=ACCT, v2=V2_AFTER_ONBOARDING, v1=v1).external_account_count == 3


# ---------------------------------------------------------------------------
# 8. Writing the projection onto a row
# ---------------------------------------------------------------------------


def _row(creator_id: str, **overrides) -> CreatorStripeAccount:
    values = {
        "id": f"csa_{uuid.uuid4()}",
        "creator_user_id": creator_id,
        "stripe_mode": "test",
    }
    values.update(overrides)
    return CreatorStripeAccount(**values)


class TestPersistence:
    def test_projection_round_trips_through_the_table(self, db, make_user):
        creator = make_user(role="creator")
        row = _row(creator.id, stripe_account_id=ACCT)
        project(
            stripe_account_id=ACCT, v2=V2_AFTER_ONBOARDING, v1=V1_AFTER,
        ).apply_to(row)
        db.add(row)
        db.commit()

        stored = db.query(CreatorStripeAccount).filter_by(id=row.id).one()
        assert stored.onboarding_state == OnboardingState.ready.value
        assert stored.transfers_status == "active"
        assert stored.payouts_status == "active"
        assert stored.transfers_enabled is True
        assert stored.payouts_enabled is True
        assert stored.external_account_count == 1
        assert stored.payout_interval == "daily"
        assert stored.payout_delay_days == 2
        assert stored.debit_negative_balances is True
        assert stored.requirements_collector == "stripe"
        assert stored.currently_due_json == []

    def test_requirement_entries_survive_as_structured_json(self, db, make_user):
        creator = make_user(role="creator")
        row = _row(creator.id, stripe_account_id=ACCT)
        project(
            stripe_account_id=ACCT, v2=V2_BEFORE_ONBOARDING, v1=V1_BEFORE,
        ).apply_to(row)
        db.add(row)
        db.commit()

        stored = db.query(CreatorStripeAccount).filter_by(id=row.id).one()
        assert len(stored.currently_due_json) == 13
        entry = next(
            e for e in stored.currently_due_json if e["description"] == "external_account"
        )
        # Without awaiting_action_from the state machine cannot run, so its
        # survival through JSONB is load-bearing, not incidental.
        assert entry["awaiting_action_from"] == "user"
        assert entry["restricts_capabilities"] == ["stripe_balance.payouts"]

    def test_applying_a_projection_never_touches_the_routing_gate(self, db, make_user):
        """A projection reports what Stripe says. Whether a creator's money
        routes through Connect is a separate, deliberate decision."""
        creator = make_user(role="creator")
        row = _row(creator.id, stripe_account_id=ACCT)
        project(stripe_account_id=ACCT, v2=V2_AFTER_ONBOARDING, v1=V1_AFTER).apply_to(row)
        assert row.connect_payouts_enabled_at is None
        db.add(row)
        db.commit()
        assert db.query(CreatorStripeAccount).filter_by(id=row.id).one() \
            .connect_payouts_enabled_at is None

    def test_one_account_per_creator_per_mode(self, db, make_user):
        creator = make_user(role="creator")
        db.add(_row(creator.id, stripe_mode="test"))
        db.commit()
        # A live-mode row for the same creator is legitimate.
        db.add(_row(creator.id, stripe_mode="live"))
        db.commit()
        # A second test-mode row is not.
        db.add(_row(creator.id, stripe_mode="test"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_a_stripe_account_id_belongs_to_one_row(self, db, make_user):
        a = make_user(role="creator")
        b = make_user(role="creator")
        db.add(_row(a.id, stripe_account_id=ACCT))
        db.commit()
        db.add(_row(b.id, stripe_account_id=ACCT))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_many_rows_may_await_their_account_id(self, db, make_user):
        """The partial index must not make the pre-create state illegal."""
        a = make_user(role="creator")
        b = make_user(role="creator")
        db.add(_row(a.id, stripe_account_id=None))
        db.add(_row(b.id, stripe_account_id=None))
        db.commit()  # no IntegrityError

    def test_transfers_enabled_cannot_contradict_its_status(self, db, make_user):
        creator = make_user(role="creator")
        db.add(_row(
            creator.id, stripe_account_id=ACCT,
            transfers_status="restricted", transfers_enabled=True,
        ))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_payouts_enabled_cannot_contradict_its_status(self, db, make_user):
        creator = make_user(role="creator")
        db.add(_row(
            creator.id, stripe_account_id=ACCT,
            payouts_status="active", payouts_enabled=False,
        ))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_routing_cannot_be_enabled_without_payouts(self, db, make_user):
        """The Phase 2 gate, enforced by the schema. Transfers being live is
        not enough — money would arrive somewhere it cannot leave."""
        creator = make_user(role="creator")
        db.add(_row(
            creator.id, stripe_account_id=ACCT,
            transfers_status="active", transfers_enabled=True,
            payouts_status="restricted", payouts_enabled=False,
            connect_payouts_enabled_at=datetime(2026, 9, 29, 12, 0, 0),
        ))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_routing_is_allowed_once_payouts_are_active(self, db, make_user):
        creator = make_user(role="creator")
        db.add(_row(
            creator.id, stripe_account_id=ACCT,
            onboarding_state=OnboardingState.ready.value,
            transfers_status="active", transfers_enabled=True,
            payouts_status="active", payouts_enabled=True,
            connect_payouts_enabled_at=datetime(2026, 9, 29, 12, 0, 0),
        ))
        db.commit()  # no IntegrityError

    def test_unknown_onboarding_state_is_rejected(self, db, make_user):
        creator = make_user(role="creator")
        db.add(_row(creator.id, onboarding_state="rejected"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_every_derived_state_is_storable(self, db, make_user):
        """Guards the enum against the CHECK constraint drifting from it."""
        for state in OnboardingState:
            creator = make_user(role="creator")
            db.add(_row(creator.id, onboarding_state=state.value))
            db.commit()

    def test_defaults_are_the_pre_connect_state(self, db, make_user):
        creator = make_user(role="creator")
        row = _row(creator.id)
        db.add(row)
        db.commit()
        stored = db.query(CreatorStripeAccount).filter_by(id=row.id).one()
        assert stored.onboarding_state == OnboardingState.not_started.value
        assert stored.transfers_enabled is False
        assert stored.payouts_enabled is False
        assert stored.details_submitted is False
        assert stored.external_account_count == 0
        assert stored.account_link_count == 0
        assert stored.connect_payouts_enabled_at is None
