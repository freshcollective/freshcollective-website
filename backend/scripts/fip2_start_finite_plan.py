"""Operator script — start a FIP2 finite payment plan in Stripe test mode.

Bypasses the public ``is_member_checkoutable`` flag so we can
integration-test the real Stripe subscription flow while the member
UI remains gated for recurring_installments. The script does NOT
add an HTTP route — it must be run from the backend host by an
operator.

Usage:

    cd /home/lindsey/fc-production/backend
    .venv/bin/python scripts/fip2_start_finite_plan.py \\
        --member-email lindsey.wd@gmail.com \\
        --payment-option-id po_XYZ \\
        --schedule-id sched_XYZ \\
        --success-url https://freshcollective.com.au/checkout/success \\
        --cancel-url  https://freshcollective.com.au/checkout/cancel

The script:

  1. Verifies Stripe is configured in test mode (refuses live keys
     unless ``--i-know-this-is-live`` is passed — you should never
     need that flag).
  2. Verifies the Payment Option Schedule is
     ``schedule_type='recurring_installments'`` and passes
     validation. It does NOT need the schedule's ``status`` to be
     published — this is a test path.
  3. Calls the FIP2 orchestrator directly, which creates the
     ``PurchasePlan`` and opens a Stripe ``mode='setup'`` Session.
  4. Prints the Stripe-hosted Checkout URL. Open it in a browser
     and complete with a Stripe test card (4242 4242 4242 4242 etc).
  5. Prints the ``PurchasePlan.id`` and a summary of what to
     expect: ``checkout.session.completed`` (setup mode) followed
     by ``invoice.payment_succeeded`` for the first instalment.

The public ``/api/checkout`` route continues to gate members via
``is_member_checkoutable`` (still False for recurring in FIP2). This
script exists specifically so we can exercise the real Stripe
subscription flow before FIP3 flips that flag.

Never publish canonical EMBODY schedules for this. Use a dedicated
test Payment Option (create one in test-mode DB via the admin
Creator Studio or seed script).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Backend path bootstrap so ``app.*`` imports resolve.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv(BACKEND_ROOT / ".env")

from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.payment_option import PaymentOption  # noqa: E402
from app.models.payment_option_schedule import PaymentOptionSchedule  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.finite_plan_orchestration import (  # noqa: E402
    ResolvedRecurringOption,
    start_finite_plan_setup,
)
from app.services.checkout_orchestration import (  # noqa: E402
    check_option_fulfillable_or_raise,
    check_same_option_not_active,
)
from app.services.schedule_validation import (  # noqa: E402
    validate_recurring_installments_row,
)
from app.models.platform import Space  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--member-email", required=True)
    ap.add_argument("--payment-option-id", required=True)
    ap.add_argument("--schedule-id", required=True)
    ap.add_argument("--success-url", required=True)
    ap.add_argument("--cancel-url", required=True)
    ap.add_argument(
        "--i-know-this-is-live",
        action="store_true",
        help=(
            "Only pass this if you have deliberately configured live "
            "Stripe keys and want to run the FIP2 flow for real. "
            "Almost always the wrong choice."
        ),
    )
    args = ap.parse_args()

    if not settings.stripe_enabled:
        print("Stripe is not configured on this backend. Aborting.",
              file=sys.stderr)
        return 2

    mode = settings.stripe_mode
    if mode == "live" and not args.i_know_this_is_live:
        print(
            "Refusing to run: STRIPE_SECRET_KEY is a LIVE key. "
            "Use a test-mode key or pass --i-know-this-is-live.",
            file=sys.stderr,
        )
        return 2

    db: Session = SessionLocal()
    try:
        member = (
            db.query(User)
            .filter(User.email == args.member_email.strip().lower())
            .one_or_none()
        )
        if member is None:
            print(f"No user with email {args.member_email!r}",
                  file=sys.stderr)
            return 2

        option = (
            db.query(PaymentOption)
            .filter(PaymentOption.id == args.payment_option_id)
            .one_or_none()
        )
        if option is None:
            print(f"PaymentOption {args.payment_option_id!r} not found",
                  file=sys.stderr)
            return 2

        schedule = (
            db.query(PaymentOptionSchedule)
            .filter(
                PaymentOptionSchedule.id == args.schedule_id,
                PaymentOptionSchedule.payment_option_id == option.id,
            )
            .one_or_none()
        )
        if schedule is None:
            print(f"Schedule {args.schedule_id!r} not on option {option.id}",
                  file=sys.stderr)
            return 2
        if schedule.schedule_type != "recurring_installments":
            print(
                f"Schedule schedule_type={schedule.schedule_type!r} — "
                "this script is only for recurring_installments plans.",
                file=sys.stderr,
            )
            return 2

        validate_recurring_installments_row(schedule)

        space = db.query(Space).filter(Space.id == option.space_id).one_or_none()
        if space is None:
            print(f"Space {option.space_id!r} for option not found",
                  file=sys.stderr)
            return 2

        # Same duplicate + fulfillability guards the route uses.
        check_option_fulfillable_or_raise(option)
        now = datetime.utcnow()
        check_same_option_not_active(
            db, user=member, payment_option=option, now=now,
        )

        currency = (schedule.currency or option.currency or "AUD").upper()
        resolved = ResolvedRecurringOption(
            payment_option=option,
            payment_schedule=schedule,
            space=space,
            currency=currency,
        )

        outcome = start_finite_plan_setup(
            db,
            resolved=resolved,
            payer=member,
            success_url=args.success_url,
            cancel_url=args.cancel_url,
            now=now,
        )

        print()
        print(f"FIP2 test plan started ({mode}-mode)")
        print(f"  PurchasePlan.id     : {outcome.plan.id}")
        print(f"  Stripe Session      : {outcome.session.id}")
        print(f"  Member              : {member.email}")
        print(f"  Payment Option      : {option.name} ({option.id})")
        print(f"  Schedule            : ${schedule.installment_amount_cents/100:.2f} "
              f"× {schedule.installment_count} @ "
              f"{schedule.stripe_interval}×{schedule.stripe_interval_count}")
        print(f"  Currency            : {currency}")
        print()
        print("Open in browser to complete payment method setup:")
        print(f"  {outcome.checkout_url}")
        print()
        print("Expected webhooks (deploy Stripe CLI + `stripe listen` if local):")
        print("  1. checkout.session.completed (mode=setup)")
        print("       → creates SubscriptionSchedule + persists provider ids")
        print("  2. invoice.payment_succeeded (first invoice)")
        print("       → creates PaymentTransaction, applies grants,")
        print("         transitions plan to `active`")
        print()
        print("Later invoices (2..N) are deferred to FIP3 and will")
        print("skip-safe until then.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
