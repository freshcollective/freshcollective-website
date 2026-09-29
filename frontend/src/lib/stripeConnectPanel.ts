/**
 * Creator-facing presentation of a Stripe Connect account's state.
 *
 * Pure, so the whole state machine is unit-testable under Node's test
 * runner without importing JSX. The React panel renders exactly what this
 * returns and decides nothing itself — the backend already derived the
 * state from Stripe's own fields, and re-deriving it from local conditions
 * is how two sources of truth start disagreeing.
 *
 * The distinction this module exists to protect
 * ---------------------------------------------
 * ``ready`` means the creator's Stripe account *can* receive transfers and
 * pay out to their bank. It does **not** mean Fresh Collective is sending
 * live sales through it. Those are separate facts with separate fields, and
 * a creator told "you're receiving automatic payouts" while their earnings
 * still go through the manual process has been misled about where their
 * money is. Only ``connect_routing_enabled`` may be read as "live".
 */

import type { CreatorStripeConnectStatus } from '@/types/platform'

export type ConnectPanelTone = 'neutral' | 'progress' | 'attention' | 'good' | 'stopped'

export type ConnectPanelActionKind = 'connect' | 'continue' | 'none'

export interface ConnectPanelView {
  /** Short status word for the badge. */
  badge: string
  tone: ConnectPanelTone
  headline: string
  /** One or two plain sentences. Never raw Stripe JSON. */
  body: string
  /** What the primary button does, if there is one. */
  action: ConnectPanelActionKind
  actionLabel: string | null
  /** Whether a manual "Refresh status" control belongs in this state. */
  showRefresh: boolean
  /**
   * Where the creator's money actually goes right now. Present whenever
   * that could be misread — which is every state except the terminal ones.
   */
  routingNote: string | null
  /** Populated only when Stripe has told us the schedule. */
  scheduleNote: string | null
  /** How many things Stripe is waiting on the creator for, if any. */
  outstandingCount: number
}

const MANUAL_ROUTING_NOTE =
  'Your earnings from sales continue to reach you through Fresh Collective’s ' +
  'existing payout process. We’ll tell you before that changes.'

const LIVE_ROUTING_NOTE =
  'Your share of each sale is now sent to this Stripe account automatically.'

/**
 * "Stripe pays out daily, two days after each sale."
 *
 * Returns null rather than inventing a schedule when Stripe has not told
 * us one — an absent schedule and a daily schedule are different facts.
 */
export function payoutScheduleSentence(
  interval: string | null,
  delayDays: number | null,
): string | null {
  if (!interval) return null
  const cadence =
    interval === 'daily' ? 'every day'
    : interval === 'weekly' ? 'once a week'
    : interval === 'monthly' ? 'once a month'
    : interval === 'manual' ? null
    : null
  if (cadence === null) return null

  if (delayDays === null || delayDays <= 0) {
    return `Stripe pays your balance into your bank account ${cadence}.`
  }
  const days = delayDays === 1 ? 'day' : 'days'
  return (
    `Stripe pays your balance into your bank account ${cadence}, ` +
    `about ${delayDays} ${days} after each sale clears.`
  )
}

/**
 * Plain-language account of who takes what, once FC routes sales through
 * Connect.
 *
 * Deliberately no percentages, no Stripe pricing table and no estimated
 * amounts: the actual processing fee depends on the card used and is only
 * known after each sale, so a number here would be wrong often enough to
 * erode trust. The order is the whole point — Stripe's fee comes out
 * first, then FC's, and the remainder is the creator's.
 *
 * A 0% plan needs its own sentence. "0% fee" is easily heard as "nothing
 * is deducted", and Stripe's processing fee is still deducted.
 */
export function feeDisclosure(platformFeeBasisPoints: number | null): string {
  const base =
    'Once automatic Stripe payouts are switched on for your sales, ' +
    'Stripe’s processing fee comes out of each sale first, then Fresh ' +
    'Collective’s plan fee, and the remainder is paid to you.'
  if (platformFeeBasisPoints === 0) {
    return (
      base +
      ' Your plan’s 0% fee is Fresh Collective’s share — Stripe’s ' +
      'processing fee still applies to every sale.'
    )
  }
  return base
}

function outstandingForCreator(status: CreatorStripeConnectStatus): number {
  return (status.requirements ?? []).filter(
    (r) => r.awaiting_action_from === 'user',
  ).length
}

/**
 * Map a backend state onto what the creator sees.
 *
 * Exhaustive over ``ConnectOnboardingState``. An unrecognised state falls
 * through to the restricted copy rather than to anything reassuring — a
 * state this build does not know about is not grounds for telling someone
 * their payouts are fine.
 */
export function describeConnect(
  status: CreatorStripeConnectStatus,
): ConnectPanelView {
  const outstandingCount = outstandingForCreator(status)
  const routing = status.connect_routing_enabled
    ? LIVE_ROUTING_NOTE
    : MANUAL_ROUTING_NOTE
  const schedule = payoutScheduleSentence(
    status.payout_interval, status.payout_delay_days,
  )

  switch (status.state) {
    case 'not_started':
      return {
        badge: 'Not connected',
        tone: 'neutral',
        headline: 'Get paid directly by Stripe',
        body:
          'Connect a Stripe account and Stripe will pay your share of each ' +
          'sale straight into your bank account. It takes a few minutes, and ' +
          'Stripe collects your details directly — Fresh Collective never ' +
          'sees them.',
        action: 'connect',
        actionLabel: 'Connect Stripe',
        showRefresh: false,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'onboarding':
      return {
        badge: 'Setup started',
        tone: 'progress',
        headline: 'Your Stripe setup isn’t finished',
        body:
          'Stripe still needs a few details before it can pay you. You can ' +
          'pick up where you left off.',
        action: 'continue',
        actionLabel: 'Continue setup',
        showRefresh: true,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'action_required':
      return {
        badge: 'Action needed',
        tone: 'attention',
        headline: 'Stripe needs a bit more from you',
        body:
          outstandingCount > 0
            ? `Stripe has asked for ${outstandingCount} more ${
                outstandingCount === 1 ? 'detail' : 'details'
              } before it can pay you. You’ll be taken to Stripe to add ${
                outstandingCount === 1 ? 'it' : 'them'
              }.`
            : 'Stripe has asked for more information before it can pay you.',
        action: 'continue',
        actionLabel: 'Continue setup',
        showRefresh: true,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'verifying':
      return {
        badge: 'Being reviewed',
        tone: 'progress',
        headline: 'Stripe is reviewing your details',
        body:
          'Nothing is needed from you right now. Stripe checks the details ' +
          'you submitted and this usually takes a short while. You can check ' +
          'again whenever you like.',
        action: 'none',
        actionLabel: null,
        showRefresh: true,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'transfers_only':
      return {
        badge: 'Almost there',
        tone: 'attention',
        headline: 'Add your bank details to receive your money',
        body:
          'Stripe can hold funds for you, but it can’t pay them out yet — ' +
          'it still needs your bank account. Until that’s done, money would ' +
          'sit in your Stripe balance with nowhere to go.',
        action: 'continue',
        actionLabel: 'Add bank details',
        showRefresh: true,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'ready':
      return {
        badge: 'Connected',
        tone: 'good',
        headline: 'Stripe is connected and ready to pay you',
        body:
          'Your Stripe account can receive funds and pay them into your bank ' +
          'account.',
        action: 'none',
        actionLabel: null,
        showRefresh: true,
        routingNote: routing,
        scheduleNote: schedule,
        outstandingCount,
      }

    case 'unsupported':
      return {
        badge: 'Not available',
        tone: 'stopped',
        headline: 'Stripe payouts aren’t available for this account',
        body:
          'Stripe can’t send payouts to an account set up this way. Please ' +
          'get in touch and we’ll work out how to pay you.',
        action: 'none',
        actionLabel: null,
        showRefresh: false,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'closed':
      return {
        badge: 'Closed',
        tone: 'stopped',
        headline: 'This Stripe account is closed',
        body:
          'A closed Stripe account can’t receive payouts, and it can’t be ' +
          'reopened. Please get in touch so we can set up a new one.',
        action: 'none',
        actionLabel: null,
        showRefresh: false,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'restricted':
    default:
      return {
        badge: 'Needs attention',
        tone: 'attention',
        headline: 'Stripe has paused this account',
        body:
          'Stripe needs to look into something before it can pay you, and ' +
          'it isn’t something you can resolve from here. Please get in touch ' +
          'and we’ll help you sort it out with Stripe.',
        action: 'none',
        actionLabel: null,
        showRefresh: true,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }
  }
}
