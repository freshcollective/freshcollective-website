import { getActiveCreatorSpace, getCreatorBilling, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorBillingResponse, CreatorPlanOut, CreatorSpaceDetail, SpaceSummary } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import { creatorFacingPlanName } from '@/lib/creatorPlanDisplay'
import BillingFeeCalculator from './BillingFeeCalculator'
import {
  CancelSubscriptionButton,
  ManageBillingButton,
  ReactivateSubscriptionButton,
  StartSubscriptionButton,
  UpgradeSubscriptionButton,
} from './BillingActions'

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

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

/**
 * Contextual billing-status pill. Reads the truest available state
 * from ``billing.subscription`` and falls back to the "not required
 * / not connected" categorisation used for manual-grant + priced-but-
 * not-yet-billed plans.
 */
function BillingStatusPill({ billing, plan }: {
  billing: CreatorBillingResponse
  plan: CreatorPlanOut
}) {
  const sub = billing.subscription
  const stripePaid = sub?.source === 'stripe_paid'
  let label = 'Billing not connected yet'
  let style: React.CSSProperties = { background: '#FEF9C3', color: '#854D0E' }
  if (plan.monthly_price_cents === 0 && plan.is_purchasable === false) {
    label = 'No billing required'
    style = { background: '#F1F5F9', color: '#475569' }
  } else if (stripePaid && sub?.status === 'active') {
    label = 'Active'
    style = { background: '#ECFDF5', color: '#065F46' }
  } else if (stripePaid && sub?.status === 'past_due') {
    label = 'Past due (grace)'
    style = { background: '#FFF7ED', color: '#7C2D12' }
  } else if (stripePaid && sub?.status === 'unpaid') {
    label = 'Lapsed'
    style = { background: '#FEF2F2', color: '#7F1D1D' }
  } else if (stripePaid && sub?.status === 'cancelled') {
    label = 'Cancelled'
    style = { background: '#F1F5F9', color: '#475569' }
  }
  return (
    <p
      className="mt-1.5 rounded-full px-3 py-1 text-[13px] font-semibold"
      style={{ ...style, display: 'inline-block' }}
    >
      {label}
    </p>
  )
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
    : 'Not required'
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

  // Route on whether the caller has an actual plan attached.
  // Historical behaviour routed admins to PlatformOwnerBilling
  // regardless of subscription state — which meant an admin who
  // had been granted a Creator Plan (Fresh Collective's founder on
  // Founding Creator) saw "no creator subscription plan attached"
  // instead of their real plan. Now: admins without a plan still
  // route to PlatformOwnerBilling; admins WITH a plan see the same
  // truthful plan card any other creator sees. The backend
  // response still carries ``is_platform_owner`` so the plan card
  // can annotate it if we want.
  if (billing.is_platform_owner && billing.current_plan === null) {
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
  const current_plan = billing.current_plan
  // "Not configured" state: creator has no active/trialing
  // CreatorSubscription. Renders a truthful warning card and hides
  // the fee-display / upgrade UI. Paid checkout is blocked (see the
  // guard in ``services/checkout_orchestration.py``); nothing here
  // needs to enforce that — but everything shown must line up with
  // the reality that no commercial terms are in effect yet.
  if (!current_plan || !billing.has_active_plan) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        {header ? (
          <CollectiveArtworkHeader
            collectiveName={header.collectiveName}
            sectionTitle="Billing"
            meta="Your Fresh Collective plan and usage."
            location={header.location}
            coverImageUrl={header.coverImageUrl}
          />
        ) : (
          <div className="mb-8">
            <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Billing</h1>
          </div>
        )}
        <div
          className="rounded-2xl p-6"
          style={{ background: '#FFF7ED', border: '1px solid #FBD38D' }}
        >
          <p className="font-serif text-[20px] text-[#7C2D12]">
            Your Fresh Collective creator plan has not been configured yet.
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-[#7C2D12]">
            Paid checkout is unavailable on your Collectives until your
            commercial terms are set. Contact Fresh Collective to
            activate your plan. Free offers continue to work while your
            plan is being configured.
          </p>
        </div>
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
              {creatorFacingPlanName(current_plan.slug, current_plan.name)}
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
            {billing.subscription?.source === 'stripe_paid'
              && billing.subscription.current_period_end && (
              <p className="mt-1 text-[12px] text-black">
                Renews {formatDate(billing.subscription.current_period_end)}
              </p>
            )}
            {billing.subscription?.source === 'manual_grant'
              && current_plan.monthly_price_cents !== null
              && current_plan.monthly_price_cents > 0 && (
              <p className="mt-1 text-[12px] italic text-black">
                Billed manually by Fresh Collective.
              </p>
            )}
            {billing.is_platform_owner && (
              <p className="mt-1 text-[12px] italic text-black">
                Platform Owner privileges also apply to this account.
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="text-[12px] font-semibold uppercase tracking-wide text-black">
              Billing status
            </p>
            <BillingStatusPill billing={billing} plan={current_plan} />
          </div>
        </div>

        {/* Contextual banners — past_due grace, cancel_at_period_end,
            unpaid/lapsed. Every banner reads truthful state directly
            from ``billing.subscription`` fields the backend populates
            from webhook data. */}
        {billing.subscription?.status === 'past_due' && billing.subscription.grace_expires_at && (
          <div
            className="mt-4 rounded-xl px-4 py-3 text-[13px]"
            style={{ background: '#FFF7ED', border: '1px solid #FBD38D', color: '#7C2D12' }}
          >
            <p className="font-semibold">Payment failed — please update your card.</p>
            <p className="mt-1">
              Your subscription will lapse on{' '}
              {formatDate(billing.subscription.grace_expires_at)} if payment is
              not recovered. Existing member purchases and access continue
              regardless.
            </p>
          </div>
        )}
        {billing.subscription?.status === 'unpaid' && (
          <div
            className="mt-4 rounded-xl px-4 py-3 text-[13px]"
            style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', color: '#7F1D1D' }}
          >
            <p className="font-semibold">Subscription lapsed.</p>
            <p className="mt-1">
              New paid sales are blocked. Existing member purchases and
              access continue. Update your billing to reactivate.
            </p>
          </div>
        )}
        {billing.subscription?.cancel_at_period_end
          && billing.subscription.current_period_end && (
          <div
            className="mt-4 rounded-xl px-4 py-3 text-[13px]"
            style={{ background: '#F1F5F9', border: '1px solid #CBD5E1', color: '#334155' }}
          >
            <p className="font-semibold">
              Cancellation scheduled for{' '}
              {formatDate(billing.subscription.current_period_end)}.
            </p>
            <p className="mt-1">
              You retain commercial capability until then. Existing member
              purchases and payment plans continue after cancellation.
            </p>
          </div>
        )}
        {billing.subscription?.pending_downgrade_plan_slug
          && billing.subscription.pending_downgrade_effective_at && (
          <div
            className="mt-4 rounded-xl px-4 py-3 text-[13px]"
            style={{ background: '#F1F5F9', border: '1px solid #CBD5E1', color: '#334155' }}
          >
            <p className="font-semibold">
              Downgrade to {billing.subscription.pending_downgrade_plan_slug} scheduled for{' '}
              {formatDate(billing.subscription.pending_downgrade_effective_at)}.
            </p>
          </div>
        )}

        {/* Primary CTAs — Manage billing for Stripe-paid subs;
            Cancel / Reactivate as the sub state warrants. Manual-grant
            plans (Founding Creator / admin-comped Community) don't
            expose these — there's nothing to manage. */}
        {billing.subscription?.source === 'stripe_paid' && (
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <ManageBillingButton />
            {billing.subscription.cancel_at_period_end
              ? <ReactivateSubscriptionButton />
              : billing.subscription.status !== 'cancelled'
                && <CancelSubscriptionButton />}
          </div>
        )}
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

      {/* Plan comparison — Community · Creator · Creator Portfolio · Organisation */}
      <div
        className="mb-6 rounded-2xl p-6"
        style={{ background: '#FFFFFF', border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-1 text-[15px] font-semibold text-navy-900">Plan comparison</h2>
        <p className="mb-5 text-[13px] text-black">
          Upgrades take effect immediately and are billed with a prorated
          adjustment. Downgrades take effect at the end of the current
          billing period.
        </p>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {available_plans
            // Hide non-purchasable plans (Founding Creator,
            // Organisation) from the picker — they're only assignable
            // manually by Fresh Collective. Keep the current plan
            // visible even if is_purchasable=false so Lindsey sees
            // her Founding Creator card while on it.
            .filter((plan) => plan.is_purchasable || plan.slug === current_plan.slug)
            .map((plan) => (
              <PlanCard
                key={plan.id}
                plan={plan}
                isCurrent={plan.slug === current_plan.slug}
                currentPlanSlug={current_plan.slug}
                currentSubscriptionSource={billing.subscription?.source}
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
            {/* Any $0 plan has nothing to bill — surface
                "Not required" instead of "Not connected", which would
                imply a broken Stripe setup. Covers BOTH Founding
                Creator (``monthly=0`` + ``is_purchasable=false``,
                admin-comped) AND Community (``monthly=0`` +
                ``is_purchasable=true``, free non-commercial). Only
                priced plans that lack a live Stripe subscription
                fall through to "Not connected". Note: an ended /
                lapsed / cancelled Stripe subscription cannot reach
                this pill — the backend's subscription query filters
                on ``status IN ('active','trialing')`` so
                ``creator_billing_connected`` can only be True when
                billing is actually healthy. */}
            <StatusBadge
              state={
                payment_setup.creator_billing_connected
                  ? 'connected'
                  : current_plan.monthly_price_cents === 0
                    ? 'not_applicable'
                    : 'not_connected'
              }
            />
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
  currentPlanSlug,
  currentSubscriptionSource,
}: {
  plan: CreatorPlanOut
  isCurrent: boolean
  /** The caller's current plan slug — used to decide upgrade vs
   *  fresh-subscription CTA on the target card. */
  currentPlanSlug: string
  /** ``stripe_paid`` means the caller has a live Stripe subscription
   *  the upgrade endpoint can modify; anything else falls back to
   *  fresh subscription checkout. */
  currentSubscriptionSource: 'stripe_paid' | 'manual_grant' | undefined
}) {
  // "Talk to us" presentation is reserved for plans with truly
  // custom pricing (Organisation) — identified by
  // ``monthly_price_cents === null``. A non-purchasable plan with a
  // fixed price (Founding Creator at $0, or any comped tier) is
  // rendered as a normal priced card because Fresh Collective has
  // already set its commercial terms. ``is_purchasable`` continues
  // to gate the CTA below (no self-service checkout) but does not
  // force enterprise presentation on top.
  const isCustomPricing = plan.monthly_price_cents === null
  const priceLabel = isCustomPricing
    ? 'Talk to us'
    : plan.monthly_price_cents === 0
      ? 'Free'
      : formatPrice(plan.monthly_price_cents, plan.currency)
  const showMonthly = !isCustomPricing && (plan.monthly_price_cents ?? 0) > 0

  // For internal / comped plans (Founding Creator and any future
  // ``is_purchasable=false`` plan with an explicit $0 price) prefer
  // DB-derived bullets that reflect the actual assigned terms
  // (transaction fee %, collective_limit, paid_offers_enabled) over
  // the static ``card_features`` copy on the capability constant,
  // which would otherwise inherit whatever generic language the
  // constant carries. Purchasable plans keep the curated marketing
  // ``card_features`` unchanged.
  const isInternalFreeplan = plan.is_purchasable === false && plan.monthly_price_cents === 0
  const features = isInternalFreeplan
    ? internalPlanFeatures(plan)
    : plan.card_features.length > 0
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
      <p className="font-serif text-[18px] font-semibold text-navy-900">
        {creatorFacingPlanName(plan.slug, plan.name)}
      </p>
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
        ) : isCustomPricing ? (
          // Enterprise / custom-pricing plan (Organisation). No
          // self-service checkout — link to the existing
          // /for-creators marketing page as the interim lead pathway.
          <a
            href="/for-creators"
            className="block w-full rounded-xl px-4 py-2.5 text-center text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Talk to us
          </a>
        ) : (plan.slug === 'creator' || plan.slug === 'pro') ? (
          // Two flows converge here:
          //   * Upgrade — the caller already has a live Stripe
          //     subscription (source='stripe_paid') and the target
          //     is a higher-priced tier (Creator → Creator Portfolio).
          //     Uses POST /api/creator/billing/upgrade which drives
          //     an immediate prorated ``Subscription.modify`` with
          //     ``payment_behavior='pending_if_incomplete'`` — the
          //     3% fee only applies after Stripe confirms payment.
          //     Does NOT create a second Stripe subscription.
          //   * Start subscription — everyone else (no live sub yet,
          //     or downgrade path from Creator Portfolio to Creator,
          //     which is handled by the Manage Billing / dedicated
          //     downgrade flow, not this card).
          currentSubscriptionSource === 'stripe_paid'
            && (currentPlanSlug === 'creator' && plan.slug === 'pro') ? (
            <UpgradeSubscriptionButton
              targetPlanSlug="pro"
              label={`Upgrade to ${creatorFacingPlanName(plan.slug, plan.name)}`}
            />
          ) : (
            <StartSubscriptionButton
              planSlug={plan.slug}
              label={`Start ${creatorFacingPlanName(plan.slug, plan.name)} subscription`}
            />
          )
        ) : (
          // Non-purchasable plans that aren't the current plan and
          // aren't Organisation (e.g. Community shown to a Creator
          // user). Keep quiet — plan-change to a lower tier is an
          // admin action for MVP.
          <button
            disabled
            className="w-full cursor-not-allowed rounded-xl px-4 py-2.5 text-[13px] font-semibold text-black"
            style={{ background: '#F1F5F9', border: '1px solid #E2E8F0', opacity: 0.6 }}
          >
            Not available
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

/**
 * Bullet list for internal / comped plans (``is_purchasable=false``
 * with an explicit $0 price — Founding Creator today). Every line
 * is derived from the plan's actual DB / capability values so no
 * hardcoded per-slug copy leaks into the card. The trailing
 * "Assigned by Fresh Collective" line makes it clear the plan is
 * not something the creator selects themselves.
 */
function internalPlanFeatures(plan: CreatorPlanOut): string[] {
  const out: string[] = []
  if (plan.transaction_fee_basis_points !== null) {
    out.push(`${formatFee(plan.transaction_fee_basis_points)} transaction fee`)
  }
  out.push('No monthly platform charge')
  if (plan.collective_limit !== null) {
    const noun = plan.collective_limit === 1 ? 'Collective' : 'Collectives'
    out.push(`Up to ${plan.collective_limit} ${noun}`)
  } else {
    out.push('Unlimited Collectives')
  }
  if (plan.paid_offers_enabled) {
    out.push('Paid offers enabled')
  }
  out.push('Assigned by Fresh Collective')
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
