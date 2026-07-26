import { getActiveCreatorSpace, getCreatorBilling, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorBillingResponse, CreatorPlanOut, CreatorSpaceDetail, SpaceSummary } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import BillingFeeCalculator from './BillingFeeCalculator'

export const metadata = { title: 'Billing — Creator Studio' }

/**
 * Creator Studio → Billing.
 *
 * Two account types render two entirely different pages:
 *
 *   Platform Owner   → the account is NOT on any creator subscription plan.
 *                      No plan card, no fee calculator, no upgrade prompts,
 *                      no "N of M collectives used" text, no references to
 *                      Creator Free / Plus / Pro. Usage panel shows
 *                      "Unlimited" for every dimension and a 0% transaction
 *                      fee. Creator Billing panel reads "Not applicable".
 *
 *   Creator          → the standard plan/subscription/upgrade UI.
 *
 * The Platform Owner UI is not built by hiding text on the Creator UI —
 * it renders a distinct panel set that mirrors the underlying architecture
 * (Platform Owner is a separate account type; see `/api/creator/billing`).
 */

// ---------------------------------------------------------------------------
// Formatting helpers (creator branch only)
// ---------------------------------------------------------------------------

function formatPrice(cents: number | null, currency: string): string {
  if (cents === null) return 'Talk to us'
  if (cents === 0) return 'Free'
  return `$${(cents / 100).toFixed(0)} ${currency}`
}

function formatFee(basisPoints: number | null): string {
  if (basisPoints === null) return 'To be defined'
  return `${(basisPoints / 100).toFixed(0)}%`
}

// ---------------------------------------------------------------------------
// Shared: status pill
// ---------------------------------------------------------------------------

function StatusBadge({
  state,
}: {
  state: 'connected' | 'not_connected' | 'not_applicable'
}) {
  const style =
    state === 'connected'
      ? { background: '#DCFCE7', color: '#166534' }
      : state === 'not_connected'
      ? { background: '#FEF9C3', color: '#854D0E' }
      : { background: '#F1F5F9', color: '#475569' }
  const label =
    state === 'connected' ? 'Connected'
    : state === 'not_connected' ? 'Not connected'
    : 'Not applicable'
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={style}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function BillingPage() {
  const [billing, activeSpace]: [CreatorBillingResponse | null, SpaceSummary | null] = await Promise.all([
    getCreatorBilling(),
    getActiveCreatorSpace(),
  ])
  const spaceDetail: CreatorSpaceDetail | null = activeSpace
    ? ((await getCreatorSpace(activeSpace.slug)) as CreatorSpaceDetail | null)
    : null

  const headerProps = activeSpace
    ? {
        collectiveName: activeSpace.name,
        location: spaceDetail?.location ?? null,
        coverImageUrl: spaceDetail?.cover_image_url ?? null,
      }
    : null

  if (!billing) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <p className="text-black">Unable to load billing information. Please try again.</p>
      </div>
    )
  }

  if (billing.is_platform_owner) {
    return <PlatformOwnerBilling billing={billing} header={headerProps} />
  }

  return <CreatorBilling billing={billing} header={headerProps} />
}

type HeaderProps = {
  collectiveName: string
  location: { name?: string; hero_artwork_url?: string | null; thumbnail_artwork_url?: string | null } | null
  coverImageUrl: string | null
} | null

// ---------------------------------------------------------------------------
// Platform Owner branch
// ---------------------------------------------------------------------------

function PlatformOwnerBilling({ billing, header }: { billing: CreatorBillingResponse; header: HeaderProps }) {
  const memberPaymentsConnected = billing.payment_setup.member_payments_connected
  const stripeTestMode = billing.payment_setup.stripe_test_mode

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {header ? (
        <CollectiveArtworkHeader
          collectiveName={header.collectiveName}
          sectionTitle="Billing"
          meta="Your account, usage and payment processing."
          location={header.location}
          coverImageUrl={header.coverImageUrl}
        />
      ) : (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Billing</h1>
        </div>
      )}

      {/* Identity panel */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#F0FDFB', border: '1px solid #99E6E4' }}
      >
        <p
          className="text-[11px] font-semibold uppercase tracking-wide"
          style={{ color: '#38A09E' }}
        >
          Account type
        </p>
        <p className="mt-1 font-serif text-[22px] font-semibold text-navy-900">
          Platform Owner
        </p>
        <p className="mt-2 text-[14px] leading-relaxed text-black">
          You are signed in as the owner of the Fresh Collective platform.
        </p>
        <p className="mt-1 text-[14px] leading-relaxed text-black">
          Your account is not governed by creator subscription plans.
        </p>
        <p className="mt-1 text-[14px] leading-relaxed text-black">
          Official Fresh Collective collectives are managed directly through your platform account.
        </p>
      </div>

      {/* Usage — all Unlimited */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-4 text-[15px] font-semibold text-navy-900">Usage</h2>
        <dl className="divide-y divide-slate-100">
          <UsageRow label="Collectives" value="Unlimited" />
          <UsageRow label="Pathways" value="Unlimited" />
          <UsageRow label="Storage" value="Unlimited" />
          <UsageRow label="Transaction fee" value="0%" />
        </dl>
      </div>

      {/* Creator Billing — not applicable */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-1 text-[15px] font-semibold text-navy-900">Creator Billing</h2>
        <p className="text-[13px] font-semibold" style={{ color: '#475569' }}>
          Not applicable
        </p>
        <p className="mt-2 text-[13px] leading-relaxed text-black">
          Platform owners do not subscribe to creator plans.
        </p>
      </div>

      {/* Payment Processing */}
      <div
        className="rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-4 text-[15px] font-semibold text-navy-900">Payment Processing</h2>
        <div className="space-y-3">

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Member payments</p>
              <p className="text-[12px] text-black">
                Processed through the Fresh Collective platform Stripe account.
                {memberPaymentsConnected && stripeTestMode && (
                  <span className="ml-2 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
                    Test mode
                  </span>
                )}
              </p>
            </div>
            <StatusBadge state={memberPaymentsConnected ? 'connected' : 'not_connected'} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Creator payouts</p>
              <p className="text-[12px] text-black">
                Platform-owned collectives do not require payout tracking.
              </p>
            </div>
            <StatusBadge state="not_applicable" />
          </div>

        </div>
      </div>

    </div>
  )
}

function UsageRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
      <dt className="text-[13px] text-black">{label}</dt>
      <dd className="text-[13px] font-semibold text-navy-900">{value}</dd>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Creator branch (unchanged behaviour — plan card, fee calc, upgrade UI)
// ---------------------------------------------------------------------------

function CreatorBilling({ billing, header }: { billing: CreatorBillingResponse; header: HeaderProps }) {
  // Non-platform-owner rows always have a current plan; the backend enforces
  // that. The null-guard here is just to keep TypeScript happy after we
  // widened the type to `CreatorPlanOut | null`.
  const current_plan = billing.current_plan
  if (!current_plan) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <p className="text-black">Unable to load your creator plan. Please try again.</p>
      </div>
    )
  }

  const { usage, available_plans, payment_setup } = billing

  // Guard against a null limit (e.g. legacy plan row without an active
  // capability record). Show progress only when a numeric limit exists.
  const collectiveLimit = current_plan.active_collective_limit ?? current_plan.collective_limit
  const collectivesUsedPct = collectiveLimit
    ? Math.min(Math.round((usage.collectives_used / collectiveLimit) * 100), 100)
    : 0

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {header ? (
        <CollectiveArtworkHeader
          collectiveName={header.collectiveName}
          sectionTitle="Billing"
          meta="Your current plan, usage and payment setup."
          location={header.location}
          coverImageUrl={header.coverImageUrl}
        />
      ) : (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Billing</h1>
        </div>
      )}

      {/* Plan + subscription status */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-wide text-black">
              Current plan
            </p>
            <p className="mt-1 font-serif text-[22px] font-semibold text-navy-900">
              {current_plan.name}
            </p>
            <p className="mt-0.5 text-[15px] text-black">
              {current_plan.monthly_price_cents === 0
                ? 'Free'
                : formatPrice(current_plan.monthly_price_cents, current_plan.currency)
              }
              {current_plan.monthly_price_cents !== null && current_plan.monthly_price_cents > 0 && '/month'}
              &nbsp;·&nbsp;
              {formatFee(current_plan.transaction_fee_basis_points)} transaction fee
            </p>
          </div>
          <div className="text-right">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-black">
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
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[13px] text-black">Collectives</span>
              <span className="text-[13px] font-semibold text-navy-900">
                {usage.collectives_used}
                {collectiveLimit !== null ? ` of ${collectiveLimit}` : ''}
              </span>
            </div>
            {collectiveLimit !== null && (
              <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${collectivesUsedPct}%`,
                    background: collectivesUsedPct >= 100 ? '#F59E0B' : '#38A09E',
                  }}
                />
              </div>
            )}
            {collectiveLimit !== null && collectivesUsedPct >= 100 && (
              <p className="mt-1.5 text-[12px] text-amber-600">
                You have reached your collective limit.
              </p>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 pt-3">
            <span className="text-[13px] text-black">Pathways (across all collectives)</span>
            <span className="text-[13px] font-semibold text-navy-900">
              {usage.pathways_used}
              {current_plan.pathway_limit !== null
                ? ` of ${current_plan.pathway_limit}`
                : ' (unlimited)'}
            </span>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 pt-3">
            <span className="text-[13px] text-black">Media storage</span>
            <span className="text-[13px] text-black">
              {current_plan.media_storage_limit_mb !== null
                ? `— of ${current_plan.media_storage_limit_mb} MB`
                : 'Unlimited'}
            </span>
          </div>
        </div>
      </div>

      {/* Fee calculator — only for plans with a defined commercial fee. */}
      {current_plan.paid_offers_enabled && current_plan.transaction_fee_basis_points !== null && (
        <div
          className="mb-6 rounded-2xl p-6"
          style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
        >
          <h2 className="mb-1.5 text-[15px] font-semibold text-navy-900">Earnings estimate</h2>
          <p className="mb-5 text-[13px] text-black">
            See how your plan&apos;s transaction fee affects a member sale. This is an estimate only — does not include Stripe processing fees, GST/tax, refunds, disputes, or payout costs.
          </p>
          <BillingFeeCalculator
            feeBasisPoints={current_plan.transaction_fee_basis_points}
            currency={current_plan.currency}
          />
        </div>
      )}

      {/* Plan comparison — Community · Creator · Pro · Organisation */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-1 text-[15px] font-semibold text-navy-900">Plan comparison</h2>
        <p className="mb-5 text-[13px] text-black">
          Plan changes are managed by Fresh Collective. Automatic plan upgrades will be available in a future update.
        </p>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {available_plans.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              isCurrent={plan.slug === current_plan.slug}
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
              <p className="text-[12px] text-black">
                Your monthly subscription payment to Fresh Collective
              </p>
            </div>
            <StatusBadge state={payment_setup.creator_billing_connected ? 'connected' : 'not_connected'} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Member payments</p>
              <p className="text-[12px] text-black">
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
            <StatusBadge state={payment_setup.member_payments_connected ? 'connected' : 'not_connected'} />
          </div>

          <div className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
            <div>
              <p className="text-[13px] font-medium text-navy-900">Automatic creator payouts</p>
              <p className="text-[12px] text-black">
                Direct payouts via Stripe Connect — coming later
              </p>
            </div>
            <StatusBadge state={payment_setup.stripe_connect_connected ? 'connected' : 'not_connected'} />
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-[13px] text-black">
          <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-black">Phase 1 — current</p>
          <p>Payments are processed through the Fresh Collective Stripe account. Your earnings are tracked as pending payout and disbursed manually.</p>
        </div>

        <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4">
          <p className="text-[12px] font-semibold uppercase tracking-wide text-black">Coming later</p>
          <ul className="mt-2 space-y-1 text-[13px] text-black">
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

// ---------------------------------------------------------------------------
// Plan comparison card (creator branch only)
// ---------------------------------------------------------------------------

function PlanCard({
  plan,
  isCurrent,
}: {
  plan: CreatorPlanOut
  isCurrent: boolean
}) {
  const isOrganisation = !plan.is_purchasable
  const priceLabel = isOrganisation
    ? 'Talk to us'
    : plan.monthly_price_cents === 0
      ? 'Free'
      : formatPrice(plan.monthly_price_cents, plan.currency)
  const showMonthly = !isOrganisation && (plan.monthly_price_cents ?? 0) > 0

  const features = plan.card_features.length > 0
    ? plan.card_features
    : legacyFeaturesFallback(plan)

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
        {priceLabel}
        {showMonthly && <span className="text-[14px] font-normal text-black">/month</span>}
      </p>
      {plan.card_headline && (
        <p className="mt-2 text-[13px] leading-relaxed text-black">{plan.card_headline}</p>
      )}

      <ul className="mt-5 space-y-2.5">
        {features.map((f) => (
          <PlanFeature key={f} label={f} />
        ))}
      </ul>

      <div className="mt-6">
        {isCurrent ? (
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold text-black"
            style={{ background: '#F1F5F9', border: '1px solid #E2E8F0' }}
          >
            Current plan
          </button>
        ) : isOrganisation ? (
          // No self-service checkout for Organisation. Link to the
          // existing /for-creators marketing page as the interim lead
          // pathway — TODO: replace with a dedicated contact form once
          // that flow is built.
          <a
            href="/for-creators"
            className="block w-full rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Talk to us
          </a>
        ) : (
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold text-black"
            style={{ background: '#F1F5F9', border: '1px solid #E2E8F0', opacity: 0.6 }}
            title="Automatic plan changes coming soon"
          >
            Change plan — coming soon
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Fallback feature list for plans whose backend response predates the
 * capability record (should not happen at runtime once the config is
 * populated, but keeps the card renderable during rollout).
 */
function legacyFeaturesFallback(plan: CreatorPlanOut): string[] {
  const out: string[] = []
  if (plan.collective_limit !== null) {
    out.push(`${plan.collective_limit} collective${plan.collective_limit !== 1 ? 's' : ''}`)
  }
  if (plan.transaction_fee_basis_points !== null) {
    out.push(`${formatFee(plan.transaction_fee_basis_points)} Fresh Collective transaction fee`)
  }
  return out
}

function PlanFeature({ label }: { label: string }) {
  return (
    <li className="flex items-start gap-2 text-[13px] text-black">
      <span className="mt-0.5 shrink-0 text-[#38A09E]">✓</span>
      {label}
    </li>
  )
}
