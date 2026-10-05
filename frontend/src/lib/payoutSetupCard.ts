/**
 * The one payout-setup prompt on Creator Studio home.
 *
 * Why it is worded as preparation and not as a blocker
 * ----------------------------------------------------
 * Fresh Collective collects payments centrally today and pays creators
 * through its own payout process. A creator with no Stripe Connect
 * account can sell, and does get paid — no checkout path consults
 * Connect readiness, and ``services/connect_payout_model`` answers
 * ``manual`` to anything it cannot decide with certainty.
 *
 * Finishing Stripe onboarding does not change that by itself either:
 * routing also needs ``connect_payouts_enabled_at``, which only Fresh
 * Collective sets. So "set this up before you can sell" would be false,
 * and "your payments now go to Stripe" would be false until that
 * separate decision is made.
 *
 * The copy therefore promises exactly one thing — that this *prepares*
 * the account — which is what Billing has always said.
 *
 * What it is gated on
 * -------------------
 * ``paid_offers_enabled`` from the resolved plan capability, never a
 * plan slug, so Community sees nothing and any future paid tier is
 * included without a code change. And the canonical onboarding state
 * from ``GET /connect/status`` — never ``stripe_connect_connected``,
 * which is a "row exists" boolean and not the same question.
 *
 * The unusual states defer to ``describeConnect``, the existing
 * canonical view-model, rather than inventing a second vocabulary for
 * them: ``transfers_only`` is genuinely "money can arrive but not
 * leave", and ``unsupported`` / ``closed`` must not be dressed up as
 * setup that is nearly done.
 */

import type { CreatorStripeConnectStatus } from '@/types/platform'
// Relative, with the extension: the sibling is a *value* import, and
// the node test runner resolves ESM without the `@/` alias. Same
// pattern as collectiveHomeArtwork.ts and collectiveOverview.ts.
import { describeConnect } from './stripeConnectPanel.ts'

/** Calm by default. ``attention`` only where Stripe genuinely wants
 *  something; ``stopped`` only where nothing the creator does helps. */
export type PayoutCardTone = 'neutral' | 'progress' | 'attention' | 'stopped'

export interface PayoutSetupCardView {
  heading: string
  body: string
  /** Null when there is nothing useful for the creator to press. */
  ctaLabel: string | null
  /** Always the same destination: the payout section of Billing. */
  href: string
  note: string | null
  tone: PayoutCardTone
}

export const PAYOUTS_HREF = '/creator-studio/billing#payouts'

const STRIPE_NOTE = 'Payments and payouts are securely managed by Stripe.'

/** The shared explanation. Says "prepares", because that is all it does. */
const PREPARATION_BODY =
  'Fresh Collective currently manages creator payouts for you. Setting up '
  + 'your payout details prepares your account for automatic payouts '
  + 'through Stripe when they’re enabled. You can keep creating and '
  + 'selling either way.'

/**
 * The card, or null when there should not be one.
 *
 * Null for: a plan that cannot make paid offers, a creator who is
 * already ready, and a missing status (which means the question could
 * not be answered — and a prompt built on a failed fetch is worse than
 * no prompt).
 */
export function payoutSetupCard(
  paidOffersEnabled: boolean,
  status: CreatorStripeConnectStatus | null | undefined,
): PayoutSetupCardView | null {
  if (!paidOffersEnabled) return null
  if (!status) return null
  if (status.state === 'ready') return null

  switch (status.state) {
    case 'not_started':
      return {
        heading: 'Set up payouts',
        body: PREPARATION_BODY,
        ctaLabel: 'Set up payouts',
        href: PAYOUTS_HREF,
        note: STRIPE_NOTE,
        tone: 'neutral',
      }

    case 'onboarding':
    case 'verifying':
      return {
        heading: 'Finish payout setup',
        body: PREPARATION_BODY,
        ctaLabel: 'Finish payout setup',
        href: PAYOUTS_HREF,
        note: STRIPE_NOTE,
        tone: 'progress',
      }

    case 'action_required':
    case 'restricted':
      // Recoverable: Stripe wants something specific and the creator
      // can supply it. Named plainly without alarm — nothing they have
      // built is at risk, and their sales are unaffected.
      return {
        heading: 'Action needed for payouts',
        body: PREPARATION_BODY,
        ctaLabel: 'Continue payout setup',
        href: PAYOUTS_HREF,
        note: STRIPE_NOTE,
        tone: 'attention',
      }

    default: {
      // ``transfers_only``, ``unsupported``, ``closed`` — and anything
      // added to the enum later. Each is a real, specific situation
      // that the canonical view-model already words correctly, and
      // none of them should be flattened into "nearly set up".
      const canonical = describeConnect(status)
      return {
        heading: canonical.headline,
        body: canonical.body,
        ctaLabel: canonical.actionLabel,
        href: PAYOUTS_HREF,
        // No Stripe reassurance line where Stripe is the problem.
        note: canonical.tone === 'stopped' ? null : STRIPE_NOTE,
        tone: canonical.tone === 'good' ? 'neutral' : canonical.tone,
      }
    }
  }
}

export { payoutReadyHeadline } from './stripeConnectPanel.ts'
