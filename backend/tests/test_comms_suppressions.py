"""Tests for the M5a suppression module."""

from __future__ import annotations

import pytest

from app.comms.suppressions import (
    UnknownAddressTypeError,
    UnknownReasonError,
    hash_address,
    is_address_suppressed,
    record_suppression,
    remove_suppression,
)


class TestNormalisationAndHashing:
    def test_lowercase_and_strip(self):
        a = hash_address("email", "  Alice@Example.TEST ")
        b = hash_address("email", "alice@example.test")
        assert a == b

    def test_distinct_addresses_hash_distinctly(self):
        a = hash_address("email", "alice@example.test")
        b = hash_address("email", "bob@example.test")
        assert a != b

    def test_dot_stripping_not_applied(self):
        """Precision over recall — Gmail's dot-canonicalisation is
        deliberately NOT applied so suppression of one address never
        suppresses a similar-looking one.
        """
        a = hash_address("email", "a.b@gmail.com")
        b = hash_address("email", "ab@gmail.com")
        assert a != b

    def test_unknown_address_type_rejected(self):
        with pytest.raises(UnknownAddressTypeError):
            hash_address("carrier_pigeon", "someone@example.test")


class TestSuppressionRoundTrip:
    def test_lookup_returns_none_when_absent(self, db):
        assert is_address_suppressed(
            db, address_type="email", address="nobody@example.test",
        ) is None

    def test_record_then_lookup(self, db):
        record_suppression(
            db,
            address_type="email",
            address="alice@example.test",
            reason="bounced",
            source_provider="resend",
        )
        row = is_address_suppressed(
            db, address_type="email", address="alice@example.test",
        )
        assert row is not None
        assert row.reason == "bounced"
        assert row.source_provider == "resend"

    def test_lookup_case_insensitive(self, db):
        record_suppression(
            db, address_type="email", address="alice@example.test",
            reason="manual",
        )
        row = is_address_suppressed(
            db, address_type="email", address="ALICE@example.test",
        )
        assert row is not None

    def test_repeat_record_is_idempotent(self, db):
        first = record_suppression(
            db, address_type="email", address="alice@example.test",
            reason="bounced",
        )
        second = record_suppression(
            db, address_type="email", address="alice@example.test",
            reason="complained",
        )
        assert first.id == second.id  # same row, updated in place
        assert second.reason == "complained"  # latest wins
        assert second.first_seen_at == first.first_seen_at
        # last_seen_at should have been touched — best-effort check
        # (could tie on the same tick in fast tests, so >=).
        assert second.last_seen_at >= first.last_seen_at

    def test_remove_returns_true_when_present(self, db):
        record_suppression(
            db, address_type="email", address="alice@example.test",
            reason="manual",
        )
        assert remove_suppression(
            db, address_type="email", address="alice@example.test",
        ) is True
        assert is_address_suppressed(
            db, address_type="email", address="alice@example.test",
        ) is None

    def test_remove_returns_false_when_absent(self, db):
        assert remove_suppression(
            db, address_type="email", address="ghost@example.test",
        ) is False

    def test_unknown_reason_rejected(self, db):
        with pytest.raises(UnknownReasonError):
            record_suppression(
                db, address_type="email", address="alice@example.test",
                reason="rude",  # type: ignore[arg-type]
            )

    def test_distinct_address_types_are_separate(self, db):
        # Same value string on two different address types — must not collide.
        record_suppression(
            db, address_type="email", address="1234567890",
            reason="manual",
        )
        record_suppression(
            db, address_type="phone", address="1234567890",
            reason="unsubscribed",
        )
        email_row = is_address_suppressed(
            db, address_type="email", address="1234567890",
        )
        phone_row = is_address_suppressed(
            db, address_type="phone", address="1234567890",
        )
        assert email_row is not None and phone_row is not None
        assert email_row.id != phone_row.id
