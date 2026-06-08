import { getCreatorBilling } from '@/lib/serverApi'
import type { CreatorBillingResponse, CreatorPlanOut } from '@/types/platform'
import BillingFeeCalculator from './BillingFeeCalculator'

export const metadata = { title: 'Billing — Creator Studio' }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(cents: number, currency: string): string {
  return `$${(cents / 100).toFixed(0)} ${currency}`
}

function formatFee(basisPoints: number): string {
  return `${(basisPoints / 100).toFixed(0)}%`
}

// ---------------------------------------------------------------------------
// Plan comparison card
// ---------------------------------------------------------------------------

function PlanCard({
  plan,
  isCurrent,
}: {
  plan: CreatorPlanOut
  isCurrent: boolean
}) {
  const isPlus = plan.slug === 'creator-plus'

  return (
    <div
      className="flex flex-col rounded-2xl p-6"
      style={{
        border: isCurrent
          ? '2px solid #38A09E'
          : '1px solid #E2E8F0',
        background: isCurrent ? '#F0FAFA' : '#FFFFFF',
      }}
    >
      {isCurrent && (
        <span
          className="mb-3 inline-block self-start rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide"
          style={{ background: '#38A09E', color: '#FFFFFF' }}
        >
          Current plan
        </span>
      )}
      <p className="font-serif text-[18px] font-semibold text-navy-900">{plan.name}</p>
      <p className="mt-1 text-[28px] font-bold text-navy-900">
        {formatPrice(plan.monthly_price_cents, plan.currency)}
        <span className="text-[14px] font-normal text-slate-500">/month</span>
      </p>
      {plan.description && (
        <p className="mt-2 text-[13px] leading-relaxed text-slate-500">{plan.description}</p>
      )}

      <ul className="mt-5 space-y-2.5">
        <PlanFeature label={`${plan.collective_limit} collective${plan.collective_limit !== 1 ? 's' : ''}`} />
        <PlanFeature label={`${formatFee(plan.transaction_fee_basis_points)} Fresh Collective transaction fee`} />
        {plan.pathway_limit !== null && (
          <PlanFeature label={`Up to ${plan.pathway_limit} pathways`} />
        )}
        {plan.media_storage_limit_mb !== null && (
          <PlanFeature label={`${plan.media_storage_limit_mb} MB media storage`} />
        )}
        {plan.creator_admin_seat_limit !== null && (
          <PlanFeature label={`${plan.creator_admin_seat_limit} admin seat${plan.creator_admin_seat_limit !== 1 ? 's' : ''}`} />
        )}
      </ul>

      <div className="mt-6">
        {isCurrent ? (
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold text-slate-400"
            style={{ background: '#F1F5F9', border: '1px solid #E2E8F0' }}
          >
            Current plan
          </button>
        ) : isPlus ? (
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold"
            style={{ background: '#F0FAFA', color: '#38A09E', border: '1px solid #38A09E', opacity: 0.6 }}
            title="Payments coming soon"
          >
            Upgrade — coming soon
          </button>
        ) : (
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold text-slate-400"
            style={{ background: '#F1F5F9', border: '1px solid #E2E8F0', opacity: 0.6 }}
            title="Payments coming soon"
          >
            Downgrade — coming soon
          </button>
        )}
      </div>
    </div>
  )
}

function PlanFeature({ label }: { label: string }) {
  return (
    <li className="flex items-start gap-2 text-[13px] text-slate-600">
      <span className="mt-0.5 shrink-0 text-[#38A09E]">✓</span>
      {label}
    </li>
  )
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ connected }: { connected: boolean }) {
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={
        connected
          ? { background: '#DCFCE7', color: '#166534' }
          : { background: '#FEF9C3', color: '#854D0E' }
      }
    >
      {connected ? 'Connected' : 'Not connected'}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function BillingPage() {
  const billing: CreatorBillingResponse | null = await getCreatorBilling()

  if (!billing) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <p className="text-slate-500">Unable to load billing information. Please try again.</p>
      </div>
    )
  }

  const { current_plan, subscription, usage, available_plans, payment_setup } = billing

  const collectivesUsedPct = Math.min(
    Math.round((usage.collectives_used / current_plan.collective_limit) * 100),
    100,
  )

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Header */}
      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Billing</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Your current plan, usage, and payment setup.
        </p>
      </div>

      {/* Plan + subscription status */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-wide text-slate-400">
              Current plan
            </p>
            <p className="mt-1 font-serif text-[22px] font-semibold text-navy-900">
              {current_plan.name}
            </p>
            <p className="mt-0.5 text-[15px] text-slate-600">
              {formatPrice(current_plan.monthly_price_cents, current_plan.currency)}/month
              &nbsp;·&nbsp;
              {formatFee(current_plan.transaction_fee_basis_points)} transaction fee
            </p>
          </div>
          <div className="text-right">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-slate-400">
              Billing status
            </p>
            <p
              className="mt-1.5 rounded-full px-3 py-1 text-[13px] font-semibold"
              style={{ background: '#FEF9C3', color: '#854D0E', display: 'inline-block' }}
            >
              Billing not connected yet
            </p>
          </div>
        </div>
      </div>

      {/* Usage */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-4 text-[15px] font-semibold text-navy-900">Usage</h2>
        <div className="space-y-4">

          {/* Collectives */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[13px] text-slate-600">Collectives</span>
              <span className="text-[13px] font-semibold text-navy-900">
                {usage.collectives_used} of {current_plan.collective_limit}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${collectivesUsedPct}%`,
                  background: collectivesUsedPct >= 100 ? '#F59E0B' : '#38A09E',
                }}
              />
            </div>
            {collectivesUsedPct >= 100 && (
              <p className="mt-1.5 text-[12px] text-amber-600">
                You have reached your collective limit. Upgrade to Creator Plus for more.
              </p>
            )}
          </div>

          {/* Pathways */}
          <div className="flex items-center justify-between border-t border-slate-100 pt-3">
            <span className="text-[13px] text-slate-600">Pathways (across all collectives)</span>
            <span className="text-[13px] font-semibold text-navy-900">
              {usage.pathways_used}
              {current_plan.pathway_limit !== null
                ? ` of ${current_plan.pathway_limit}`
                : ' (unlimited)'}
            </span>
          </div>

          {/* Storage */}
          <div className="flex items-center justify-between border-t border-slate-100 pt-3">
            <span className="text-[13px] text-slate-600">Media storage</span>
            <span className="text-[13px] text-slate-400">
              {current_plan.media_storage_limit_mb !== null
                ? `— of ${current_plan.media_storage_limit_mb} MB`
                : 'Unlimited'}
            </span>
          </div>

        </div>
      </div>

      {/* Fee calculator */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-1.5 text-[15px] font-semibold text-navy-900">Earnings estimate</h2>
        <p className="mb-5 text-[13px] text-slate-500">
          See how your plan&apos;s transaction fee affects a member sale. This is an estimate only — does not include Stripe processing fees, GST/tax, refunds, disputes, or payout costs.
        </p>
        <BillingFeeCalculator feeBasisPoints={current_plan.transaction_fee_basis_points} currency={current_plan.currency} />
      </div>

      {/* Plan comparison */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-1 text-[15px] font-semibold text-navy-900">Plan comparison</h2>
        <p className="mb-5 text-[13px] text-slate-500">
          Plan changes are managed by Fresh Collective. Automatic plan upgrades will be available in a future update.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {available_plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              isCurrent={plan.id === current_plan.id}
            />
          ))}
        </div>
      </div>

      {/* Payment setup status */}
      <div
        className="rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-4 text-[15px] font-semibold text-navy-900">Payment setup</h2>
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Creator billing</p>
              <p className="text-[12px] text-slate-500">Your monthly subscription payment to Fresh Collective</p>
            </div>
            <StatusBadge connected={payment_setup.creator_billing_connected} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Member payments</p>
              <p className="text-[12px] text-slate-500">
                {payment_setup.member_payments_connected
                  ? 'Processed through Fresh Collective · Paid pathway checkout is live'
                  : 'Platform Stripe not yet configured · Contact Fresh Collective'}
                {payment_setup.member_payments_connected && payment_setup.stripe_test_mode && (
                  <span className="ml-2 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                    Test mode
                  </span>
                )}
              </p>
            </div>
            <StatusBadge connected={payment_setup.member_payments_connected} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Automatic creator payouts</p>
              <p className="text-[12px] text-slate-500">
                Direct payouts via Stripe Connect — coming later
              </p>
            </div>
            <StatusBadge connected={payment_setup.stripe_connect_connected} />
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-[13px] text-slate-500">
          <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-slate-400">Phase 1 — current</p>
          <p>Payments are processed through the Fresh Collective Stripe account. Your earnings are tracked as pending payout and disbursed manually.</p>
        </div>

        <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4">
          <p className="text-[12px] font-semibold uppercase tracking-wide text-slate-400">Coming later</p>
          <ul className="mt-2 space-y-1 text-[13px] text-slate-500">
            <li>· Stripe Connect onboarding for automatic creator payouts</li>
            <li>· Refunds, disputes, and payout reporting</li>
            <li>· Creator subscription billing via Stripe</li>
            <li>· GST/tax reporting and invoicing</li>
          </ul>
        </div>
      </div>

    </div>
  )
}
