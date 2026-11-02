#!/usr/bin/env python
"""Who would be refused if the Creator Plan guard were switched on.

Read-only. Writes nothing, changes nothing, and is safe to run
against production.

Where to run it
---------------
From the **fc-api Render Shell**, where ``DATABASE_URL`` already
points at production::

    python scripts/audit_creator_plans.py

The working directory there is ``backend`` — ``rootDir: backend`` in
render.yaml — which is also why this file lives in ``backend/scripts``
rather than at the repository root. The root is not part of that
service's deployed tree, so a script placed there is simply absent on
the instance; every cron in render.yaml addresses its script the same
way, as ``scripts/<name>.py`` relative to this directory.

Locally, pass ``DATABASE_URL`` explicitly.

Not to be confused with ``audit_creator_plans_prod.py`` beside it,
which is run *from a developer machine* with ``PROD_DATABASE_URL``
and answers a narrower pair of questions: which plan rows exist, and
whether any creator holds two active subscriptions. This one is about
eligibility, waivers and fee integrity.

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

# ``backend/`` — this file's grandparent. The fc-api service builds
# with ``rootDir: backend``, so the repository root is not part of its
# deployed tree and a script living there is simply absent on the
# instance. Every operational script lives here for that reason, and
# every cron in render.yaml addresses them as ``scripts/<name>.py``
# relative to this directory.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

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
    not_commercial: list[tuple[User, str, int]] = []
    expiring: list = []
    caps = {c.slug: c for c in ALL_PLANS}
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

        cap = caps.get(
            db.get(CreatorPlan, sub.creator_plan_id).slug
            if sub and db.get(CreatorPlan, sub.creator_plan_id) else None
        )
        if sub is None:
            verdict = "WOULD BE REFUSED — selling at 0% today"
            at_risk.append((u, len(spaces), taken))
        else:
            plan = db.get(CreatorPlan, sub.creator_plan_id)
            bps = plan.transaction_fee_basis_points if plan else None
            rate = "n/a" if bps is None else f"{bps / 100:g}%"
            if cap is not None and not cap.paid_offers_enabled:
                verdict = (
                    f"REFUSED — {plan.slug} does not permit paid offers"
                )
                not_commercial.append((u, plan.slug, taken))
            else:
                verdict = f"covered — {plan.slug if plan else '?'} at {rate}"

        print(f"\n  {u.email}  ({u.role})")
        print(f"     Collectives      : {len(spaces)} — "
              f"{', '.join(s.slug for s in spaces) or '(none)'}")
        print(f"     succeeded sales  : {taken}")
        if sub is None:
            print("     subscription     : NONE")
        else:
            # A waiver is a manual grant on the creator's real plan: the
            # monthly charge is forgiven, the plan and its transaction
            # fee are not. Printing source and dates together is what
            # makes that visible rather than inferred.
            print(f"     subscription     : {sub.status.value} "
                  f"({sub.source}"
                  f"{', ' + sub.grant_reason if sub.grant_reason else ''})")
            if sub.ends_at:
                print(f"     grant/waiver ends: {sub.ends_at:%Y-%m-%d}")
                # A comp grant with an end date falls back seven days
                # after it unless a paid row is already waiting. That
                # is the difference between "billing resumes" and
                # "selling stops".
                elected = (
                    db.query(CreatorSubscription)
                    .filter(
                        CreatorSubscription.user_id == u.id,
                        CreatorSubscription.source == "stripe_paid",
                        CreatorSubscription.status.in_(COVERED),
                    )
                    .first()
                )
                print(f"     paid row waiting : "
                      f"{'yes — billing resumes' if elected else 'NO — selling stops at expiry'}")
                if not elected:
                    expiring.append((u, sub.ends_at))
        print(f"     if guard enabled : {verdict}")

    # ---- Founding Creator exclusivity --------------------------------
    print("\nFOUNDING CREATOR — must be exactly one holder")
    fc_row = rows.get("founding-creator")
    if fc_row is None:
        print("    no founding-creator plan row — see above")
    else:
        holders = (
            db.query(CreatorSubscription, User)
            .join(User, User.id == CreatorSubscription.user_id)
            .filter(CreatorSubscription.creator_plan_id == fc_row.id)
            .all()
        )
        live = [(sub, u) for sub, u in holders if sub.status in COVERED]
        for sub, u in holders:
            state = "LIVE" if sub.status in COVERED else sub.status.value
            print(f"    {u.email:42} {state:10} {sub.source}")
        if len(live) > 1:
            print("    DISCREPANCY: more than one live holder. This plan is")
            print("    the founder's exclusive arrangement.")
        elif not live:
            print("    DISCREPANCY: nobody currently holds it.")
        cap = caps.get("founding-creator")
        if cap is not None:
            ok = not cap.is_purchasable and not cap.is_self_service
            print(f"    not purchasable / not self-service: {ok}")

    # ---- Historical fee integrity ------------------------------------
    #
    # Every transaction snapshots the rate it was charged at. A row
    # whose rate does not match any configured plan rate was charged
    # under a fallback or an older configuration — reported, never
    # adjusted: a historical transaction is a record of what happened.
    print("\nHISTORICAL TRANSACTIONS BY FEE RATE")
    known = {
        r.transaction_fee_basis_points for r in rows.values()
        if r.transaction_fee_basis_points is not None
    }
    seen = (
        db.query(
            PaymentTransaction.platform_fee_basis_points,
            func.count(PaymentTransaction.id),
        )
        .filter(PaymentTransaction.status == "succeeded")
        .group_by(PaymentTransaction.platform_fee_basis_points)
        .order_by(PaymentTransaction.platform_fee_basis_points)
        .all()
    )
    if not seen:
        print("    (no succeeded transactions)")
    for bps, n in seen:
        if bps is None:
            note = "no rate recorded"
        elif bps == 0:
            note = ("0% — expected only for the founder or a "
                    "platform-owned Collective")
        elif bps in known:
            note = "matches a configured plan"
        else:
            note = "DOES NOT MATCH ANY CONFIGURED PLAN"
        rate = "n/a" if bps is None else f"{bps / 100:g}%"
        print(f"    {rate:>6}  {n:5} transaction(s)  — {note}")

    print("\nSUMMARY")
    refused = len(at_risk) + len(not_commercial)
    if refused == 0:
        print("  Every Collective owner holds an eligible commercial plan.")
        print("  Enabling CREATOR_PLAN_GUARD_ENABLED would refuse nobody.")
    else:
        print(f"  {refused} owner(s) would be refused at paid checkout.")
    if at_risk:
        print(f"\n  {len(at_risk)} with no subscription at all "
              "(selling at 0% today):")
        for u, n_spaces, taken in at_risk:
            trading = "HAS TAKEN MONEY" if taken else "no sales yet"
            print(f"     {u.email} — {n_spaces} Collective(s), {trading}")
    if not_commercial:
        print(f"  {len(not_commercial)} owner(s) are on a non-commercial plan:")
        for u, slug, taken in not_commercial:
            print(f"     {u.email} — {slug}, "
                  f"{'HAS TAKEN MONEY' if taken else 'no sales'}")
    if expiring:
        print(f"  {len(expiring)} grant(s) end with no paid row waiting:")
        for u, ends in expiring:
            print(f"     {u.email} — ends {ends:%Y-%m-%d}, selling stops 7 days later")
    if at_risk:
        print("\n  Give each an explicit CreatorSubscription before")
        print("  enabling the guard. Founding Creator is $0/month and 0%,")
        print("  so assigning it changes nobody's economics — it only")
        print("  makes the existing arrangement explicit.")
    print()


if __name__ == "__main__":
    main()
