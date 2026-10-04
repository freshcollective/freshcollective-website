"""Audit — and, only when provably safe, remove — disposable test accounts.

Scoped to three named production QA accounts and nothing else. The
scope is a module constant rather than a CLI argument on purpose: a
cleanup that can be pointed at an arbitrary email by whoever runs it is
a different and much worse tool.

Why this is not ``db.delete(user)``
-----------------------------------
``users.id`` is referenced by around a hundred foreign keys, and the
delete rules are not uniform. Roughly forty cascade, six restrict, and
the rest null out. Three of the cascades reach data that does not
belong to the account being deleted:

  * ``peer_threads.participant_a_user_id`` / ``..._b_user_id`` cascade,
    and ``peer_messages.thread_id`` cascades from ``peer_threads``. So
    deleting one participant destroys the whole conversation —
    including every message the *other* person wrote.
  * ``message_threads.creator_id`` / ``member_id`` cascade, and
    ``direct_messages.thread_id`` cascades from the thread. Same shape
    for creator↔member messaging.
  * ``community_posts.author_id`` cascades, and ``post_comments``,
    ``post_reactions`` and ``polls`` all cascade from the post. So
    deleting the author of a Conversation also deletes every real
    member's comment, reaction and vote on it.

None of that is visible in a ``DELETE FROM users`` and none of it is
recoverable. So the audit looks for those specific shapes and refuses,
rather than discovering them afterwards.

The six ``RESTRICT`` columns are the opposite problem: they block the
delete outright with a foreign-key error. Those are
``spaces.creator_id``, ``creator_subscriptions.user_id``,
``member_subscriptions.user_id``, ``purchase_plans.member_user_id``,
``creator_media_assets.uploaded_by_user_id`` and
``creator_payout_batches`` (two columns). The ones that are genuinely
test-only are removed in order ahead of the user; the ones that imply
real money — a member subscription, a purchase plan, a payout batch —
are treated as blockers, because an account with a payment history is
not disposable.

The dependency map is read from ``information_schema`` at run time
rather than hand-listed. A hand-listed map is wrong the moment somebody
adds a table, and being wrong here means silently cascading through
whatever was missed.

Nothing in this module is scheduled, and nothing it does is reversible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

#: The only accounts this may ever touch.
TARGET_EMAILS: tuple[str, ...] = (
    "jenson@hilliard.net.au",
    "hello@freshcollective.au",
    "lindsey.wd@gmail.com",
)

#: Retained production QA account. Named here so the exclusion is part
#: of the code rather than part of whoever is running it remembering:
#: Tom is the controlled example for the finite complimentary Creator
#: lifecycle and the later paid conversion, so his account, his
#: Collective, his grant and his Stripe references all stay.
PROTECTED_EMAILS: tuple[str, ...] = (
    "tom@hilliard.net.au",
)

#: ``RESTRICT`` columns that this cleanup is willing to resolve itself,
#: because the rows are test-only by construction: a Collective the
#: target owns, their own Creator subscription or grant, and media they
#: uploaded. Everything else that restricts is a blocker.
RESOLVABLE_RESTRICTS: frozenset[str] = frozenset({
    "spaces.creator_id",
    "creator_subscriptions.user_id",
    "creator_media_assets.uploaded_by_user_id",
})


@dataclass(frozen=True)
class DependentRows:
    """One foreign-key column, and how many rows it holds for a user."""

    table: str
    column: str
    delete_rule: str
    count: int

    @property
    def ref(self) -> str:
        return f"{self.table}.{self.column}"


@dataclass
class Blocker:
    """A reason this account must not be deleted."""

    kind: str
    detail: str


@dataclass
class SpaceFinding:
    space_id: str
    slug: str
    name: str
    status: str
    owner_email: str | None
    member_emails: list[str]
    outside_member_emails: list[str]
    event_count: int
    pathway_count: int
    post_count: int
    purchase_plan_count: int
    payment_transaction_count: int


@dataclass
class UserFinding:
    email: str
    user_id: str | None = None
    name: str | None = None
    role: str | None = None
    dependents: list[DependentRows] = field(default_factory=list)
    owned_spaces: list[SpaceFinding] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)

    @property
    def present(self) -> bool:
        return self.user_id is not None

    @property
    def safe(self) -> bool:
        return self.present and not self.blockers

    def cascading(self) -> list[DependentRows]:
        return [d for d in self.dependents if d.delete_rule == "CASCADE" and d.count]

    def restricting(self) -> list[DependentRows]:
        return [d for d in self.dependents if d.delete_rule == "RESTRICT" and d.count]

    def nulling(self) -> list[DependentRows]:
        return [d for d in self.dependents if d.delete_rule == "SET NULL" and d.count]


@dataclass
class CleanupPlan:
    findings: list[UserFinding]
    protected_user_ids: dict[str, str]

    @property
    def safe(self) -> bool:
        """Every present target is individually safe, and at least one
        is present. A plan with any blocker is not partially applied —
        see ``apply``."""
        present = [f for f in self.findings if f.present]
        return bool(present) and all(f.safe for f in present)

    @property
    def blocked(self) -> list[UserFinding]:
        return [f for f in self.findings if f.present and f.blockers]


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

_FK_SQL = """
SELECT tc.table_name, kcu.column_name, rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.table_schema = ccu.table_schema
JOIN information_schema.referential_constraints rc
  ON tc.constraint_name = rc.constraint_name
 AND tc.table_schema = rc.constraint_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
  AND ccu.table_name = :ref_table
  AND ccu.column_name = 'id'
ORDER BY tc.table_name, kcu.column_name
"""


def user_fk_columns(db: Session) -> list[tuple[str, str, str]]:
    """Every ``(table, column, delete_rule)`` referencing ``users.id``.

    Read from the live schema so a table added later is audited without
    anybody remembering to add it here.
    """
    return [
        (r[0], r[1], r[2])
        for r in db.execute(text(_FK_SQL), {"ref_table": "users"}).all()
    ]


def _scalar(db: Session, sql: str, **params) -> int:
    return db.scalar(text(sql), params) or 0


def table_exists(db: Session, table: str) -> bool:
    """Whether a table is present in this database.

    Checked rather than assumed. A database behind on migrations is a
    real situation — the local copy of production was missing
    ``peer_threads`` entirely — and a cleanup script that dies on a
    ``relation does not exist`` buried in a stack trace is useless
    exactly when somebody needs to read its output. A table that does
    not exist holds no rows, which is the answer the audit wants
    anyway.
    """
    return bool(db.scalar(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = :t"
    ), {"t": table}))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def _resolve(db: Session, email: str) -> tuple[str, str, str] | None:
    row = db.execute(
        text("SELECT id, name, role FROM users WHERE lower(email) = lower(:e)"),
        {"e": email},
    ).first()
    return (row[0], row[1], row[2]) if row else None


def _space_finding(
    db: Session, space_id: str, target_ids: set[str],
) -> SpaceFinding:
    row = db.execute(text(
        "SELECT s.id, s.slug, s.name, s.status, u.email "
        "FROM spaces s LEFT JOIN users u ON u.id = s.creator_id "
        "WHERE s.id = :sid"
    ), {"sid": space_id}).first()

    members = db.execute(text(
        "SELECT u.id, u.email FROM space_memberships m "
        "JOIN users u ON u.id = m.user_id WHERE m.space_id = :sid"
    ), {"sid": space_id}).all()

    member_emails = [m[1] for m in members]
    # Anybody who is not one of the accounts being removed. A protected
    # account needs no separate clause here: ``PROTECTED_EMAILS`` and
    # ``TARGET_EMAILS`` are disjoint — asserted by test, and backed by
    # the ``protected_account`` blocker if anybody ever lists one in
    # both — so Tom is never in ``target_ids`` and is already an
    # outsider by this test. His membership is his, and this cleanup
    # does not get to cancel it as a side effect of removing somebody
    # else.
    outside = [m[1] for m in members if m[0] not in target_ids]

    def count(sql: str, table: str) -> int:
        if not table_exists(db, table):
            return 0
        return _scalar(db, sql, sid=space_id)

    return SpaceFinding(
        space_id=row[0], slug=row[1], name=row[2], status=row[3],
        owner_email=row[4],
        member_emails=member_emails,
        outside_member_emails=outside,
        event_count=count("SELECT count(*) FROM events WHERE space_id = :sid", "events"),
        pathway_count=count("SELECT count(*) FROM pathways WHERE space_id = :sid", "pathways"),
        post_count=count("SELECT count(*) FROM community_posts WHERE space_id = :sid", "community_posts"),
        purchase_plan_count=count(
            "SELECT count(*) FROM purchase_plans WHERE space_id = :sid", "purchase_plans"
        ),
        payment_transaction_count=count(
            "SELECT count(*) FROM payment_transactions WHERE space_id = :sid", "payment_transactions"
        ),
    )


def _shared_data_blockers(
    db: Session, user_id: str, target_ids: set[str],
) -> list[Blocker]:
    """The cascades that would take somebody else's data with them.

    Each of these is a refusal rather than a warning: the rows are not
    the target's to delete, and the cascade is silent.
    """
    blockers: list[Blocker] = []
    others = tuple(target_ids - {user_id}) or ("",)

    # Peer conversations. Deleting a participant cascades the thread and
    # every message in it, both sides.
    shared_peer = [] if not table_exists(db, "peer_threads") else db.execute(text(
        "SELECT t.id, "
        "  (SELECT count(*) FROM peer_messages m WHERE m.thread_id = t.id) "
        "FROM peer_threads t "
        "WHERE (t.participant_a_user_id = :uid OR t.participant_b_user_id = :uid) "
        "  AND NOT (t.participant_a_user_id = ANY(:others) "
        "           OR t.participant_b_user_id = ANY(:others))"
    ), {"uid": user_id, "others": list(others)}).all()
    # Every row the query returned already has a counterpart outside
    # the cleanup set — a thread between two targets is excluded by the
    # ``others`` predicate, and a thread needs two people.
    if shared_peer:
        total_messages = sum(t[1] for t in shared_peer)
        blockers.append(Blocker(
            kind="shared_peer_thread",
            detail=(
                f"{len(shared_peer)} peer conversation(s) with someone "
                f"outside the cleanup set, holding {total_messages} "
                f"message(s). Deleting this account cascades the thread "
                f"and both sides' messages."
            ),
        ))

    # Creator<->member messaging.
    shared_dm = [] if not table_exists(db, "message_threads") else db.execute(text(
        "SELECT t.id, "
        "  (SELECT count(*) FROM direct_messages d WHERE d.thread_id = t.id) "
        "FROM message_threads t "
        "WHERE (t.member_id = :uid OR t.creator_id = :uid) "
        "  AND NOT (t.member_id = ANY(:others) OR t.creator_id = ANY(:others))"
    ), {"uid": user_id, "others": list(others)}).all()
    if shared_dm:
        blockers.append(Blocker(
            kind="shared_message_thread",
            detail=(
                f"{len(shared_dm)} creator/member thread(s) with someone "
                f"outside the cleanup set, holding "
                f"{sum(t[1] for t in shared_dm)} message(s)."
            ),
        ))

    # Conversations authored by the target that other people engaged
    # with. The post cascades, and the comments and reactions cascade
    # from the post.
    engaged = [] if not table_exists(db, "community_posts") else db.execute(text(
        "SELECT p.id, "
        "  (SELECT count(*) FROM post_comments c "
        "    WHERE c.post_id = p.id AND c.author_id <> :uid "
        "      AND NOT c.author_id = ANY(:others)), "
        "  (SELECT count(*) FROM post_reactions r "
        "    WHERE r.post_id = p.id AND r.user_id <> :uid "
        "      AND NOT r.user_id = ANY(:others)) "
        "FROM community_posts p WHERE p.author_id = :uid"
    ), {"uid": user_id, "others": list(others)}).all()
    foreign_comments = sum(r[1] for r in engaged)
    foreign_reactions = sum(r[2] for r in engaged)
    if foreign_comments or foreign_reactions:
        blockers.append(Blocker(
            kind="engaged_conversation",
            detail=(
                f"Conversations authored by this account carry "
                f"{foreign_comments} comment(s) and {foreign_reactions} "
                f"reaction(s) from other people, which cascade with the "
                f"post."
            ),
        ))

    return blockers


def audit(db: Session) -> CleanupPlan:
    """Read-only. Resolves the targets and everything attached to them."""
    protected: dict[str, str] = {}
    for email in PROTECTED_EMAILS:
        found = _resolve(db, email)
        if found:
            protected[email] = found[0]

    resolved: dict[str, tuple[str, str, str]] = {}
    for email in TARGET_EMAILS:
        found = _resolve(db, email)
        if found:
            resolved[email] = found

    target_ids = {v[0] for v in resolved.values()}
    protected_ids = set(protected.values())
    fk_columns = user_fk_columns(db)

    findings: list[UserFinding] = []
    for email in TARGET_EMAILS:
        finding = UserFinding(email=email)
        found = resolved.get(email)
        if not found:
            findings.append(finding)
            continue

        finding.user_id, finding.name, finding.role = found

        # Hard refusals that do not depend on any row count.
        if finding.user_id in protected_ids or email in PROTECTED_EMAILS:
            finding.blockers.append(Blocker(
                kind="protected_account",
                detail="This email is on the protected list.",
            ))
        if finding.role == "admin":
            finding.blockers.append(Blocker(
                kind="admin_account",
                detail=(
                    f"Role is 'admin'. This cleanup never deletes an "
                    f"administrator, so if {email} is genuinely "
                    f"disposable its role has to be changed first, "
                    f"deliberately."
                ),
            ))

        # Everything referencing this user, by delete rule.
        for table, column, rule in fk_columns:
            count = _scalar(
                db,
                f'SELECT count(*) FROM "{table}" WHERE "{column}" = :uid',
                uid=finding.user_id,
            )
            if count:
                finding.dependents.append(
                    DependentRows(table, column, rule, count)
                )

        # RESTRICT columns this cleanup will not resolve itself.
        for dep in finding.restricting():
            if dep.ref not in RESOLVABLE_RESTRICTS:
                finding.blockers.append(Blocker(
                    kind="unresolvable_restrict",
                    detail=(
                        f"{dep.count} row(s) in {dep.ref} restrict the "
                        f"delete and are not test-only — an account with "
                        f"a subscription, purchase plan or payout history "
                        f"is not disposable."
                    ),
                ))

        # Collectives they own.
        owned = db.execute(text(
            "SELECT id FROM spaces WHERE creator_id = :uid ORDER BY name"
        ), {"uid": finding.user_id}).scalars().all()
        for space_id in owned:
            sf = _space_finding(db, space_id, target_ids)
            finding.owned_spaces.append(sf)
            if sf.outside_member_emails:
                finding.blockers.append(Blocker(
                    kind="collective_has_outside_members",
                    detail=(
                        f"'{sf.name}' ({sf.slug}) has member(s) outside the "
                        f"cleanup set: {', '.join(sorted(sf.outside_member_emails))}. "
                        f"Deleting the Collective cascades their memberships."
                    ),
                ))
            if sf.purchase_plan_count or sf.payment_transaction_count:
                finding.blockers.append(Blocker(
                    kind="collective_has_money",
                    detail=(
                        f"'{sf.name}' has {sf.purchase_plan_count} purchase "
                        f"plan(s) and {sf.payment_transaction_count} payment "
                        f"transaction(s) attached."
                    ),
                ))

        finding.blockers.extend(
            _shared_data_blockers(db, finding.user_id, target_ids)
        )
        findings.append(finding)

    return CleanupPlan(findings=findings, protected_user_ids=protected)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

@dataclass
class ApplyResult:
    users_deleted: list[str] = field(default_factory=list)
    spaces_deleted: list[str] = field(default_factory=list)
    subscriptions_deleted: int = 0
    media_assets_deleted: int = 0
    skipped: list[str] = field(default_factory=list)


def apply_cleanup(db: Session, plan: CleanupPlan) -> ApplyResult:
    """Delete the targets, in dependency order. Caller commits.

    Refuses the whole plan if any present target has a blocker. Not
    partial on purpose: these accounts exist as a set, and removing two
    of three leaves a half-cleaned state that is harder to reason about
    than either end.
    """
    if not plan.safe:
        raise RuntimeError(
            "refusing to apply: "
            + "; ".join(
                f"{f.email}: {b.kind}"
                for f in plan.blocked for b in f.blockers
            )
        )

    result = ApplyResult()

    for finding in plan.findings:
        if not finding.present:
            result.skipped.append(f"{finding.email}: no such account")
            continue

        # Order matters, and it is the RESTRICT columns that set it.
        #
        # 1. Creator subscriptions and grants — RESTRICT on
        #    ``creator_subscriptions.user_id``. ``creator_plan_grants``
        #    nulls its actor, so the audit trail survives the account.
        subs = db.execute(text(
            "DELETE FROM creator_subscriptions WHERE user_id = :uid"
        ), {"uid": finding.user_id})
        result.subscriptions_deleted += subs.rowcount or 0

        # 2. Media they uploaded — RESTRICT on
        #    ``creator_media_assets.uploaded_by_user_id``. The stored
        #    objects are left in R2: this removes rows, not blobs, and
        #    an orphaned blob is cheaper than a wrong deletion.
        assets = db.execute(text(
            "DELETE FROM creator_media_assets WHERE uploaded_by_user_id = :uid"
        ), {"uid": finding.user_id})
        result.media_assets_deleted += assets.rowcount or 0

        # 3. Collectives they own — RESTRICT on ``spaces.creator_id``.
        #    Everything inside cascades from the space.
        for sf in finding.owned_spaces:
            db.execute(
                text("DELETE FROM spaces WHERE id = :sid"), {"sid": sf.space_id},
            )
            result.spaces_deleted.append(f"{sf.name} ({sf.slug})")

        # 4. The account itself. The remaining forty-odd cascades run
        #    here, all of them rows that belong to this account alone —
        #    the audit refused if any of them reached further.
        db.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": finding.user_id},
        )
        result.users_deleted.append(f"{finding.email} ({finding.user_id})")

    return result


#: What is counted for a protected account, before and after.
_PROTECTED_COUNTS: tuple[tuple[str, str, str], ...] = (
    ("collectives_owned", "spaces",
     "SELECT count(*) FROM spaces WHERE creator_id = :uid"),
    ("memberships", "space_memberships",
     "SELECT count(*) FROM space_memberships WHERE user_id = :uid"),
    ("creator_subscriptions", "creator_subscriptions",
     "SELECT count(*) FROM creator_subscriptions WHERE user_id = :uid"),
    ("hellos_sent", "member_hellos",
     "SELECT count(*) FROM member_hellos WHERE from_user_id = :uid"),
    ("hellos_received", "member_hellos",
     "SELECT count(*) FROM member_hellos WHERE to_user_id = :uid"),
    ("peer_messages", "peer_messages",
     "SELECT count(*) FROM peer_messages WHERE sender_user_id = :uid"),
    ("event_bookings", "event_bookings",
     "SELECT count(*) FROM event_bookings WHERE user_id = :uid"),
)


def protected_snapshot(db: Session) -> dict[str, dict[str, int | str]]:
    """What the protected accounts look like right now.

    Taken before an apply and compared after. A snapshot rather than an
    assertion that the counts are non-zero: "Tom has no bookings" is a
    legitimate state, and a tripwire that fires on it would be noise
    that teaches people to ignore it.
    """
    snapshot: dict[str, dict[str, int | str]] = {}
    for email in PROTECTED_EMAILS:
        found = _resolve(db, email)
        if not found:
            snapshot[email] = {"present": 0}
            continue
        user_id = found[0]
        counts: dict[str, int | str] = {"present": 1, "user_id": user_id}
        for label, table, sql in _PROTECTED_COUNTS:
            counts[label] = (
                _scalar(db, sql, uid=user_id) if table_exists(db, table) else 0
            )
        snapshot[email] = counts
    return snapshot


def verify_protected_intact(
    db: Session, before: dict[str, dict[str, int | str]],
) -> list[str]:
    """Differences in the protected accounts since ``before``. Empty is
    good.

    Tom must come out of this byte-for-byte unchanged. Checked by
    re-counting rather than by trusting that nothing in the delete
    order reached him.
    """
    problems: list[str] = []
    after = protected_snapshot(db)
    for email, was in before.items():
        now = after.get(email, {"present": 0})
        if now.get("present") != was.get("present"):
            problems.append(f"{email}: account presence changed")
            continue
        for key, value in was.items():
            if now.get(key) != value:
                problems.append(
                    f"{email}: {key} changed {value} -> {now.get(key)}"
                )
    return problems
