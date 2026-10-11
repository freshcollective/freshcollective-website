/**
 * Creator Studio → Commerce → Bank payouts.
 *
 * Everything about getting a creator's money to their bank: readiness,
 * verification, payout schedule and the per-sale earnings behind it.
 * Separated from Billing, which is about the creator's *subscription* to
 * Fresh Collective — money out, not money in. Those were one page, and the
 * payout half had no navigation entry of its own, so a creator who had
 * finished setting up could not find it again.
 *
 * Assembled entirely from existing parts: ``StripeConnectPanel`` (which
 * carries all nine readiness states and renders ``ConnectEarnings`` when
 * routing is live), and the ``getCreatorBilling`` /
 * ``getCreatorStripeConnectStatus`` server fetchers Billing already used.
 * Nothing about the Connect flow is reimplemented here.
 */

import PlanUpgradeNotice from '@/components/creator/PlanUpgradeNotice'
import {
  getCreatorBilling,
  getCreatorStripeConnectStatus,
} from '@/lib/serverApi'
import type {
  CreatorBillingResponse,
  CreatorStripeConnectStatus,
} from '@/types/platform'
import BankPayoutsSections from './BankPayoutsSections'

export const metadata = { title: 'Bank payouts — Creator Studio' }

export default async function BankPayoutsPage() {
  // Plan gate — mirrors the sidebar, which omits this entry on Community.
  // A direct URL is the only way to arrive here on that plan, so explain
  // the plan rather than render a tool every action of which the backend
  // would refuse. Not a security boundary: ``plan_guards.py`` still owns
  // every write, and the Connect endpoints are scoped to the authenticated
  // creator, so no account can see another's figures.
  //
  // ``is_platform_owner`` passes the gate, exactly as on Payments received.
  // The Platform Owner holds a Founding Creator plan and a real connected
  // account, and needs these screens — both to be paid and to test them.
  const gate = await getCreatorBilling().catch(() => null)
  if (!(gate?.is_platform_owner || gate?.current_plan?.paid_offers_enabled)) {
    return (
      <PlanUpgradeNotice
        title="Bank payouts"
        intro="Bank payouts is where you set up how your earnings reach your bank account."
        unlocks="paid offers, so there are earnings to pay out"
      />
    )
  }

  const [billing, connectStatus]: [
    CreatorBillingResponse | null,
    CreatorStripeConnectStatus | null,
  ] = await Promise.all([
    getCreatorBilling(),
    // Cheap: answers from Fresh Collective's own projection with no Stripe
    // call, and returns null rather than throwing, so it cannot take the
    // page down with it.
    getCreatorStripeConnectStatus(),
  ])

  const planFeeBasisPoints =
    billing?.current_plan?.transaction_fee_basis_points ?? null

  return (
    <div className="mx-auto w-full max-w-[920px] px-5 py-8 md:px-8">
      <header className="mb-6">
        <h1 className="font-serif text-[26px] leading-tight text-navy-900">
          Bank payouts
        </h1>
        <p className="mt-2 max-w-[62ch] text-[13px] leading-relaxed text-black">
          How your earnings reach your bank account. Set up your bank details
          once, and your share of each sale is sent on automatically.
        </p>
      </header>

      {/* Shown as context, not as a reason to withhold the panel. A
          platform-owned Collective's sales are processed on Fresh
          Collective's own account, so they need no creator payout account —
          but the same person may also sell through a Collective of their own,
          and previously this condition hid the whole panel from them. */}
      {billing?.is_platform_owner && (
        <p className="mb-6 rounded-xl border border-navy-900/10 bg-navy-900/[0.03] px-4 py-3 text-[12.5px] leading-relaxed text-black">
          Sales from platform-owned Collectives are processed through the Fresh
          Collective Stripe account and do not need a creator payout account.
          Anything you sell through your own Collective is paid out below.
        </p>
      )}

      {/* Readiness, then the bank account and the payouts Stripe has made.
          Rendered together so they share one status: separate copies drifted
          apart, and a refresh updated only one of them. */}
      <BankPayoutsSections
        initialStatus={connectStatus}
        planFeeBasisPoints={planFeeBasisPoints}
      />
    </div>
  )
}
