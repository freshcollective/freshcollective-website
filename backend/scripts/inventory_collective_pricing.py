"""Read-only inventory of Collective membership pricing.

Why this exists
---------------
Stage 5A.0. ``Space.pricing_type`` advertises a membership price and
``Space.join_policy`` independently decides whether the free Join button
works — and ``POST /api/spaces/{slug}/join`` reads only the second. So a
Collective can advertise A$29/month and still admit people for nothing.

Before closing that gap, and before retiring the ``coming_soon`` pricing
type, two things have to be known rather than assumed: which Collectives
actually carry a paid or retired pricing type, and how many live members
they already have. A cleanup that locks a real creator out of their own
settings, or a join gate that bars a Collective whose checkout does not
exist yet, is worse than the gap.

Safety
------
SELECT statements only. The transaction is set ``READ ONLY`` before
anything is read, so an accidental write fails at the database rather
than relying on this docstring. No member names or emails are read at
all — memberships are counted, never listed.

Running it
----------
From the Render Shell for fc-api (or locally against a dev database)::

    python scripts/inventory_collective_pricing.py
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal

#: The value behind the creator-facing "Paid — coming soon" option. Named
#: here because the label and the stored value differ, and guessing wrong
#: would make this whole inventory describe nothing.
RETIRED = "coming_soon"
PAID_PREFIX = "paid_"


def heading(title: str) -> None:
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))

        heading("1. Every pricing type in use, by Collective status")
        rows = db.execute(text("""
            SELECT COALESCE(pricing_type, '(null)') AS pricing_type,
                   status::text                      AS status,
                   is_public,
                   count(*)                          AS collectives
            FROM spaces
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        """)).mappings().all()
        print(f"  {'pricing_type':20} {'status':10} {'public':7} {'count':>6}")
        print(f"  {'-'*20} {'-'*10} {'-'*7} {'-'*6}")
        for r in rows:
            print(f"  {r['pricing_type']:20} {r['status']:10} "
                  f"{str(r['is_public']):7} {r['collectives']:>6}")
        total = sum(r["collectives"] for r in rows)
        print(f"\n  total Collectives: {total}")

        heading("2. Paid or retired pricing — the Collectives that matter")
        affected = db.execute(text("""
            SELECT s.slug,
                   s.pricing_type,
                   s.status::text        AS status,
                   s.is_public,
                   s.join_policy,
                   s.pricing_amount_cents,
                   s.pricing_currency,
                   (s.creator_id IS NULL) AS platform_owned,
                   (SELECT count(*) FROM space_memberships m
                     WHERE m.space_id = s.id
                       AND m.status = 'active')   AS active_members,
                   (SELECT count(*) FROM space_memberships m
                     WHERE m.space_id = s.id
                       AND m.status = 'paused')   AS paused_members,
                   (SELECT count(*) FROM space_memberships m
                     WHERE m.space_id = s.id)     AS all_membership_rows
            FROM spaces s
            WHERE s.pricing_type LIKE :paid OR s.pricing_type = :retired
            ORDER BY s.pricing_type, s.slug
        """), {"paid": f"{PAID_PREFIX}%", "retired": RETIRED}).mappings().all()

        if not affected:
            print("  -- none: no Collective carries a paid or retired "
                  "pricing type --")
        for r in affected:
            amount = (
                f"{r['pricing_amount_cents']} {r['pricing_currency']}"
                if r["pricing_amount_cents"] is not None else "(no amount set)"
            )
            print(f"\n  {r['slug']}")
            print(f"     pricing_type     {r['pricing_type']}")
            print(f"     amount           {amount}")
            print(f"     status           {r['status']}"
                  f"   public={r['is_public']}"
                  f"   platform_owned={r['platform_owned']}")
            print(f"     join_policy      {r['join_policy']}")
            print(f"     members          active={r['active_members']} "
                  f"paused={r['paused_members']} "
                  f"rows={r['all_membership_rows']}")

        heading("3. Join policies in use")
        for r in db.execute(text("""
            SELECT COALESCE(join_policy, '(null)') AS join_policy, count(*) AS n
            FROM spaces GROUP BY 1 ORDER BY 2 DESC
        """)).mappings():
            print(f"  {r['join_policy']:22} {r['n']:>4}")

        heading("4. VERDICT")
        retired_rows = [r for r in affected if r["pricing_type"] == RETIRED]
        paid_rows = [r for r in affected
                     if (r["pricing_type"] or "").startswith(PAID_PREFIX)]

        print(f"  Collectives on '{RETIRED}':  {len(retired_rows)}")
        if retired_rows:
            print("    -> retiring the dropdown option must keep these "
                  "renderable and saveable.")
            for r in retired_rows:
                print(f"       {r['slug']}  ({r['active_members']} active members)")
        else:
            print("    -> nothing stored on the retired value; the cleanup "
                  "is a pure dropdown change.")

        print(f"\n  Collectives on a paid type:  {len(paid_rows)}")
        if paid_rows:
            exposed = [r for r in paid_rows if r["join_policy"] == "open"]
            print(f"    of which join_policy='open' (free door on a paid "
                  f"Collective): {len(exposed)}")
            for r in exposed:
                print(f"       {r['slug']}  pricing={r['pricing_type']} "
                      f"active_members={r['active_members']}")
            print("    -> enforcing payment at /join would block NEW joins "
                  "for these until Stage 5A.1 ships checkout.")
            print("       Existing members are unaffected either way.")
        else:
            print("    -> no Collective advertises paid membership, so the "
                  "join gate blocks nobody today.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
