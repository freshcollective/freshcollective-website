"""The one-time Ways to Connect participation reset.

``scripts/ways_to_connect_reset_participation_once.py`` runs once, by
hand, against production. It has no test coverage from being scheduled
and no second chance, so the properties that matter are pinned here:
dry run writes nothing, apply moves only ``true`` rows, deliberate
opt-outs survive, a second apply changes nothing, and no connection or
conversation data is read or written.

The script's ``main()`` builds its own engine from ``settings``, which
is right for a production script and wrong for a test. These tests
exercise the same statement against the test session instead, and a
source-contract test keeps the two from drifting.

Run with::

    cd backend
    .venv/bin/python -m pytest tests/test_ways_to_connect_reset_participation.py
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

import app.models.community_care  # noqa: F401
from app.models.connections import MemberHello
from app.models.peer_messages import PeerMessage, PeerThread, canonical_pair
from app.models.user import User

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "ways_to_connect_reset_participation_once.py"
)


def _code_only(text: str) -> str:
    """Source with comments and docstrings removed — this file asserts
    what the script *does*, and its prose describes what it does not."""
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return re.sub(r"#.*", "", text)


def _reset(db) -> int:
    """The script's one statement, against the test session.

    Kept identical to the script by ``test_the_statement_matches_the_script``
    below rather than by hope.
    """
    result = db.execute(
        User.__table__.update()
        .where(User.ways_to_connect_enabled.is_(True))
        .values(ways_to_connect_enabled=False)
    )
    # A Core UPDATE does not pass through the identity map, so objects
    # already loaded in this session still hold their old value. The
    # script does not care — it exits straight afterwards — but a test
    # that assigns to a stale object would find SQLAlchemy sees no
    # change and emits no UPDATE at all, which looks like the reset
    # having undone something it never touched.
    db.expire_all()
    return result.rowcount


def _count(db, *where) -> int:
    return db.scalar(select(func.count()).select_from(User).where(*where)) or 0


@pytest.fixture
def population(db, make_user):
    """Six accounts: four inherited ``true`` across the three roles, and
    two deliberate ``false`` opt-outs that must survive."""
    return {
        "member_a": make_user(role="user", ways_to_connect_enabled=True),
        "member_b": make_user(role="user", ways_to_connect_enabled=True),
        "creator": make_user(role="creator", ways_to_connect_enabled=True),
        "admin": make_user(role="admin", ways_to_connect_enabled=True),
        "opted_out": make_user(role="user", ways_to_connect_enabled=False),
        "opted_out_creator": make_user(
            role="creator", ways_to_connect_enabled=False,
        ),
    }


class TestTheDryRunWritesNothing:
    def test_the_script_defaults_to_a_dry_run(self):
        """``--apply`` is opt-in. A script that mutated by default could
        do so from a mistyped command or a stray deploy hook."""
        code = _code_only(SCRIPT.read_text())
        assert '"--apply"' in code
        assert "action=\"store_true\"" in code
        # The write is reachable only past an ``args.apply`` guard.
        update_at = code.index(".values(ways_to_connect_enabled=False)")
        guard_at = code.index("if not args.apply:")
        assert guard_at < update_at, "the update is not behind the apply guard"

    def test_the_dry_run_path_rolls_back_rather_than_commits(self):
        code = _code_only(SCRIPT.read_text())
        dry = code[code.index("if not args.apply:"):code.index("result = db.execute")]
        assert "db.rollback()" in dry
        assert "db.commit()" not in dry

    def test_only_one_commit_exists_and_it_is_after_the_checks(self):
        code = _code_only(SCRIPT.read_text())
        assert code.count("db.commit()") == 1
        assert code.index("after_true != 0") < code.index("db.commit()")

    def test_counting_leaves_the_rows_alone(self, db, population):
        """The read half, run for real: counting and listing must not
        change a thing."""
        before = {u.id: u.ways_to_connect_enabled for u in population.values()}

        total = db.scalar(select(func.count()).select_from(User))
        targets = db.scalars(
            select(User).where(User.ways_to_connect_enabled.is_(True))
        ).all()
        assert total >= 6
        assert len(targets) >= 4

        for user in population.values():
            db.refresh(user)
            assert user.ways_to_connect_enabled is before[user.id]


class TestApplyMovesOnlyTheInheritedRows:
    def test_true_becomes_false(self, db, population):
        _reset(db)
        db.flush()
        for key in ("member_a", "member_b", "creator", "admin"):
            db.refresh(population[key])
            assert population[key].ways_to_connect_enabled is False, key

    def test_deliberate_opt_outs_are_left_alone(self, db, population):
        """Already ``false``: excluded by the WHERE clause, not written
        and set back. Nothing distinguishes them afterwards, so the only
        protection is that they were never in the statement's scope."""
        changed = _reset(db)
        db.flush()
        for key in ("opted_out", "opted_out_creator"):
            db.refresh(population[key])
            assert population[key].ways_to_connect_enabled is False, key
        # Four inherited rows, not six.
        assert changed == 4

    def test_every_role_is_included(self, db, population):
        """Admin status is not consent either. The Platform Owner preview
        bypass is about the launch flag, not participation, so owner QA
        access is unaffected by resetting it."""
        _reset(db)
        db.flush()
        db.refresh(population["admin"])
        assert population["admin"].ways_to_connect_enabled is False

    def test_nobody_is_left_opted_in(self, db, population):
        _reset(db)
        db.flush()
        assert _count(db, User.ways_to_connect_enabled.is_(True)) == 0

    def test_the_opt_out_total_adds_up(self, db, population):
        before_false = _count(db, User.ways_to_connect_enabled.is_(False))
        changed = _reset(db)
        db.flush()
        after_false = _count(db, User.ways_to_connect_enabled.is_(False))
        assert after_false == before_false + changed


class TestItIsIdempotent:
    def test_a_second_apply_changes_nothing(self, db, population):
        first = _reset(db)
        db.flush()
        second = _reset(db)
        db.flush()
        assert first == 4
        assert second == 0, "a second run must be a no-op"

    def test_a_third_run_is_still_zero(self, db, population):
        _reset(db)
        db.flush()
        _reset(db)
        db.flush()
        assert _reset(db) == 0

    def test_it_does_not_undo_a_later_opt_in(self, db, population):
        """Somebody who opts in after the reset must stay opted in — the
        script is not a recurring enforcement of ``false``. That it would
        catch them is exactly why it must never be scheduled."""
        _reset(db)
        db.flush()
        population["member_a"].ways_to_connect_enabled = True
        db.flush()

        # The script run again *would* catch them, which is the hazard.
        assert _count(db, User.ways_to_connect_enabled.is_(True)) == 1
        code = _code_only(SCRIPT.read_text())
        assert "schedule" not in code.lower()
        assert "cron" not in code.lower()


class TestNothingElseIsTouched:
    @pytest.fixture
    def connected_pair(self, db, make_user):
        """Two members with a mutual hello, a thread and messages — the
        state a participation change must not disturb."""
        a = make_user(ways_to_connect_enabled=True)
        b = make_user(ways_to_connect_enabled=True)
        for frm, to in ((a, b), (b, a)):
            db.add(MemberHello(
                id=f"h_{uuid.uuid4().hex[:12]}",
                from_user_id=frm.id, to_user_id=to.id,
            ))
        low, high = canonical_pair(a.id, b.id)
        thread = PeerThread(
            id=f"pt_{uuid.uuid4().hex[:12]}",
            participant_a_user_id=low,
            participant_b_user_id=high,
        )
        db.add(thread)
        db.flush()
        for body in ("One", "Two"):
            db.add(PeerMessage(
                id=f"pm_{uuid.uuid4().hex[:12]}",
                thread_id=thread.id, sender_user_id=a.id, body=body,
            ))
        db.flush()
        return a, b, thread

    def test_hellos_messages_and_threads_all_survive(self, db, connected_pair):
        _a, _b, thread = connected_pair
        hellos = db.query(MemberHello).count()
        threads = db.query(PeerThread).count()
        messages = db.query(PeerMessage).count()

        _reset(db)
        db.flush()

        assert db.query(MemberHello).count() == hellos
        assert db.query(PeerThread).count() == threads
        assert db.query(PeerMessage).count() == messages
        assert db.get(PeerThread, thread.id) is not None
        bodies = [
            m.body for m in db.query(PeerMessage)
            .filter(PeerMessage.thread_id == thread.id)
            .order_by(PeerMessage.created_at)
        ]
        assert bodies == ["One", "Two"]

    def test_no_other_account_field_changes(self, db, make_user):
        """Only the one column. A stray ``.values()`` entry would be
        invisible in the counts the script prints."""
        user = make_user(
            role="creator", name="Keep Me", ways_to_connect_enabled=True,
        )
        snapshot = {
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "password_hash": user.password_hash,
            "email_verified_at": user.email_verified_at,
            "created_at": user.created_at,
            "suspended_at": user.suspended_at,
        }

        _reset(db)
        db.flush()
        db.refresh(user)

        for field, value in snapshot.items():
            assert getattr(user, field) == value, field
        assert user.ways_to_connect_enabled is False

    def test_the_script_imports_and_queries_only_the_user_model(self):
        """A source sweep. Checked on model names and imports rather
        than on bare table strings, because the script deliberately
        *names* the untouched tables in ``UNTOUCHED_TABLES`` so its
        output can state the blast radius — the point is that it never
        imports or queries them.
        """
        code = _code_only(SCRIPT.read_text())
        # Strip the documentation constant: it is a list of names the
        # script promises not to touch, which is the opposite of a
        # breach.
        code = re.sub(
            r"UNTOUCHED_TABLES\s*=\s*\([\s\S]*?\)", "", code,
        )
        for name in (
            "MemberHello", "PeerThread", "PeerMessage", "MemberBlock",
            "CreatorProfile", "SpaceMembership", "CommunityPost",
            "member_hellos", "peer_threads", "peer_messages",
            "member_blocks", "community_care", "creator_profiles",
        ):
            assert name not in code, f"the script references {name}"

        imports = re.findall(r"^from app\.models[^\n]*", code, re.M)
        assert imports == ["from app.models.user import User"], imports

    def test_the_script_issues_exactly_one_write(self):
        code = _code_only(SCRIPT.read_text())
        assert code.count(".update()") == 1
        assert ".delete()" not in code
        assert "DELETE" not in code.upper()


class TestTheStatementMatchesTheScript:
    def test_the_predicate_and_the_value_are_the_scripts(self):
        """These tests exercise a copy of the statement, so the copy has
        to be the same statement. Pinned by source rather than trusted.

        Matched as one expression — ``update().where(...).values(...)``
        — not as three strings that each appear somewhere in the file.
        The predicate also appears in the counts and in the target
        SELECT, so an "is it present anywhere" check stayed green when
        the ``where`` was removed from the UPDATE alone: an unscoped
        write over every row, which is the single worst thing this
        script could do.
        """
        code = _code_only(SCRIPT.read_text())
        assert re.search(
            r"User\.__table__\.update\(\)\s*"
            r"\.where\(User\.ways_to_connect_enabled\.is_\(True\)\)\s*"
            r"\.values\(ways_to_connect_enabled=False\)",
            code,
        ), "the UPDATE is not scoped to opted-in rows setting them false"

    def test_no_update_is_left_unscoped(self):
        """Belt and braces for the same hazard, independent of how the
        statement is spelled: every ``update()`` must be followed by a
        ``where``."""
        code = _code_only(SCRIPT.read_text())
        for match in re.finditer(r"\.update\(\)", code):
            tail = code[match.end():match.end() + 120]
            assert ".where(" in tail, (
                f"unscoped update: ...{code[match.start() - 60:match.end() + 60]}"
            )

    def test_the_target_list_uses_the_same_predicate_as_the_update(self):
        """The dry run must list precisely the rows the apply will
        change, or the review it exists for is worthless."""
        code = _code_only(SCRIPT.read_text())
        assert code.count("User.ways_to_connect_enabled.is_(True)") >= 3

    def test_failure_rolls_back_and_exits_non_zero(self):
        code = _code_only(SCRIPT.read_text())
        tail = code[code.index("except Exception:"):]
        assert "db.rollback()" in tail
        assert "return 1" in tail

    def test_it_verifies_before_committing(self):
        """Read-back assertions inside the transaction, so a mismatch
        rolls the whole thing back rather than leaving it half done."""
        code = _code_only(SCRIPT.read_text())
        for check in ("after_true != 0", "changed != len(targets)"):
            assert check in code, check
            assert code.index(check) < code.index("db.commit()")


class TestEmailsAreNotSpilledByDefault:
    def test_addresses_are_masked_unless_asked_for(self):
        from scripts.ways_to_connect_reset_participation_once import mask_email

        assert mask_email("ada@example.com") == "a**@example.com"
        assert mask_email("a@example.com") == "a@example.com"
        assert mask_email(None) == "<none>"
        assert mask_email("not-an-email") == "<none>"

    def test_the_default_output_path_masks(self):
        code = _code_only(SCRIPT.read_text())
        assert "user.email if args.show_emails else mask_email(user.email)" in code
