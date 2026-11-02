#!/usr/bin/env python
"""Who would be refused if the Creator Plan guard were switched on.

Read-only. Writes nothing, changes nothing, and is safe to run
against production.

Why a script rather than an answer
----------------------------------
The guard's effect depends entirely on live data — which creators
hold an active or trialing subscription right now — and a local
database lags production by many migrations, so reading one to
answer a question about the other would be worse than not answering.
This asks production directly.

What it reports
---------------
1. **The configured fee for every plan**, read from the
   ``creator_plans`` rows, which is what checkout actually charges.
   The constants in ``app/creator/plan_config.py`` are the seed and
   the capability record, not the runtime source, so the two can
   disagree and only this one matters.
2. **Every creator who owns a Collective**, their subscription if
   any, and what the guard would do to them. A creator with no
   active, trialing or past-due subscription is currently selling at
   **0% platform fee** and would start receiving HTTP 409 at
   checkout the moment the guard is enabled.
3. **Whether any affected Collective has taken money**, so the
   difference between "a dormant Collective would break" and
   "a trading Collective would stop selling" is visible rather than
   inferred.

``past_due`` counts as covered on purpose: it is Fresh Collective's
seven-day grace window, during which checkout keeps succeeding at the
creator's snapshotted fee.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")

import app.main  # noqa: E402,F401 — loads the full model graph

from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models.creator_billing import (  # noqa: E402
    CreatorPlan,
    CreatorSubscription,
    CreatorSubscriptionStatus,
)
from app.models.payment import PaymentTransaction  # noqa: E402
from app.models.platform import Space  # noqa: E402
from app.models.user import User  # noqa: E402

#: The statuses ``_resolve_fee_bps_for_creator`` accepts. Kept in step
#: with that function deliberately — if it changes, this report is
#: wrong in the direction that matters.
COVERED = (
    CreatorSubscriptionStatus.active,
    CreatorSubscriptionStatus.trialing,
    CreatorSubscriptionStatus.past_due,
)


def main() -> None:
    db = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]))()

    print("\nPLANS — the rates checkout actually uses")
    print(f"  {'slug':20} {'monthly':>10} {'fee':>7}  active")
    for p in db.query(CreatorPlan).order_by(CreatorPlan.slug).all():
        monthly = (
            "n/a" if p.monthly_price_cents is None
            else f"${p.monthly_price_cents / 100:,.0f}"
        )
        bps = p.transaction_fee_basis_points
        fee = "n/a" if bps is None else f"{bps / 100:g}%"
        print(f"  {p.slug:20} {monthly:>10} {fee:>7}  {p.is_active}")

    # The capability constants and the database can disagree, and only
    # the database is charged. Where a slug has no row at all the
    # catalogue shows a "synthetic" entry built from the constant —
    # and no subscription can be created against it, because
    # ``creator_subscriptions.creator_plan_id`` is a foreign key.
    from app.creator.plan_config import ALL_PLANS

    rows = {p.slug: p for p in db.query(CreatorPlan).all()}
    mismatches, missing = [], []
    for cap in ALL_PLANS:
        row = rows.get(cap.slug)
        if row is None:
            missing.append(cap.slug)
        elif (
            cap.transaction_fee_basis_points is not None
            and row.transaction_fee_basis_points
            != cap.transaction_fee_basis_points
        ):
            mismatches.append(
                (cap.slug, row.transaction_fee_basis_points,
                 cap.transaction_fee_basis_points)
            )

    if mismatches:
        print("\n  RATE DISAGREEMENTS — charged vs displayed")
        for slug, charged, shown in mismatches:
            print(f"    {slug:20} charges {charged / 100:g}%, "
                  f"the capability constant says {shown / 100:g}%")
    if missing:
        print("\n  PLANS WITH NO DATABASE ROW")
        print(f"    {', '.join(missing)}")
        print("    These appear in the catalogue as synthetic entries, but")
        print("    no creator can be subscribed to one: the subscription's")
        print("    creator_plan_id is a foreign key to creator_plans.")

    print("\nCREATORS WHO OWN A COLLECTIVE")
    owners = (
        db.query(User)
        .filter(User.id.in_(
            db.query(Space.creator_id).filter(Space.creator_id.isnot(None))
        ))
        .order_by(User.email)
        .all()
    )
    if not owners:
        print("  (none)")

    at_risk: list[tuple[User, int, int]] = []
    for u in owners:
        sub = (
            db.query(CreatorSubscription)
            .filter(
                CreatorSubscription.user_id == u.id,
                CreatorSubscription.status.in_(COVERED),
            )
            .order_by(CreatorSubscription.created_at.desc())
            .first()
        )
        spaces = (
            db.query(Space).filter(Space.creator_id == u.id).all()
        )
        space_ids = [s.id for s in spaces]
        taken = (
            db.query(func.count(PaymentTransaction.id))
            .filter(
                PaymentTransaction.space_id.in_(space_ids),
                PaymentTransaction.status == "succeeded",
            )
            .scalar() or 0
        ) if space_ids else 0

        if sub is None:
            verdict = "WOULD BE REFUSED — selling at 0% today"
            at_risk.append((u, len(spaces), taken))
        else:
            plan = db.get(CreatorPlan, sub.creator_plan_id)
            bps = plan.transaction_fee_basis_points if plan else None
            rate = "n/a" if bps is None else f"{bps / 100:g}%"
            verdict = f"covered — {plan.slug if plan else '?'} at {rate}"

        print(f"\n  {u.email}  ({u.role})")
        print(f"     Collectives      : {len(spaces)} — "
              f"{', '.join(s.slug for s in spaces) or '(none)'}")
        print(f"     succeeded sales  : {taken}")
        print(f"     subscription     : "
              f"{sub.status.value if sub else 'NONE'}")
        print(f"     if guard enabled : {verdict}")

    print("\nSUMMARY")
    if not at_risk:
        print("  Every Collective owner holds a covered subscription.")
        print("  Enabling CREATOR_PLAN_GUARD_ENABLED would refuse nobody.")
    else:
        print(f"  {len(at_risk)} owner(s) would be refused at checkout:")
        for u, n_spaces, taken in at_risk:
            trading = "HAS TAKEN MONEY" if taken else "no sales yet"
            print(f"     {u.email} — {n_spaces} Collective(s), {trading}")
        print("\n  Give each an explicit CreatorSubscription before")
        print("  enabling the guard. Founding Creator is $0/month and 0%,")
        print("  so assigning it changes nobody's economics — it only")
        print("  makes the existing arrangement explicit.")
    print()


if __name__ == "__main__":
    main()
