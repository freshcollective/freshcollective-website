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
 * One deduction, and it is Fresh Collective's. The creator's commission
 * percentage is named, because it is theirs and fixed by their plan. Stripe's
 * pricing table is not, because Fresh Collective absorbs that cost — quoting
 * a figure a creator never pays would invite them to subtract it.
 *
 * A 0% plan needs its own sentence. "0% commission" is easily heard as a
 * catch — the point is that there genuinely is nothing to deduct, so a
 * Founding Creator receives the full amount of each sale.
 */
export function feeDisclosure(platformFeeBasisPoints: number | null): string {
  const covered =
    'Fresh Collective covers the standard card processing costs on your ' +
    'sales — they are not taken out of your earnings.'
  if (platformFeeBasisPoints === 0) {
    // A Founding Creator pays no commission, so there is nothing to deduct
    // at all. The old copy told them processing fees "still apply", which
    // is now simply untrue and would understate what they receive.
    return (
      'Your Fresh Collective commission is 0%, so you receive the full ' +
      'amount of each sale. ' + covered
    )
  }
  if (platformFeeBasisPoints === null) {
    return (
      'Fresh Collective deducts its platform commission from each sale and ' +
      'you receive the rest. ' + covered
    )
  }
  const pct = (platformFeeBasisPoints / 100).toFixed(
    platformFeeBasisPoints % 100 === 0 ? 0 : 2,
  )
  return (
    `Fresh Collective deducts its ${pct}% platform commission from each ` +
    'sale and you receive the rest. ' + covered
  )
}

/**
 * What the creator must agree to before Fresh Collective will route their
 * sales through Connect.
 *
 * Acknowledging is not enabling. It records that they have seen how the fees
 * fall; whether their money actually changes path stays a deliberate decision
 * by Fresh Collective. Saying so on the button's own screen avoids a creator
 * believing they have switched something on.
 */
export interface FeeAcknowledgementView {
  /** Whether to ask at all. */
  required: boolean
  disclosure: string
  prompt: string
  actionLabel: string
  /** Reassurance that agreeing does not move their money. */
  note: string
}

export function feeAcknowledgement(
  status: CreatorStripeConnectStatus,
  platformFeeBasisPoints: number | null,
): FeeAcknowledgementView {
  return {
    required: !status.fee_disclosure_acknowledged,
    disclosure: feeDisclosure(platformFeeBasisPoints),
    prompt:
      'Before we can switch your sales over, please confirm you’ve read how ' +
      'your earnings are worked out.',
    actionLabel: 'I understand how my earnings are worked out',
    note:
      'Confirming doesn’t switch anything on. Fresh Collective enables ' +
      'automatic payouts separately, and we’ll tell you when yours are live.',
  }
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
/**
 * How a creator's payout position should be described once Stripe has
 * accepted their details.
 *
 * ``ready`` means Stripe is satisfied. It does **not** mean Fresh
 * Collective has switched this creator's sales to Connect — that needs
 * ``connect_payouts_enabled_at``, which only Fresh Collective sets, and
 * which the status payload already surfaces as
 * ``connect_routing_enabled``. So the two can be told apart from
 * existing data, with no new backend field.
 */
export function payoutReadyHeadline(
  status: CreatorStripeConnectStatus,
): string {
  return status.connect_routing_enabled
    ? 'Automatic payouts are active'
    : 'Your payout details are set up'
}


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
        badge: 'Not set up',
        tone: 'neutral',
        headline: 'Get paid into your bank account',
        body:
          'Set up your bank details securely and receive your earnings ' +
          'directly into your nominated account. Stripe handles verification ' +
          'and transfers behind the scenes.',
        action: 'connect',
        actionLabel: 'Set up bank payouts',
        showRefresh: false,
        routingNote: routing,
        scheduleNote: null,
        outstandingCount,
      }

    case 'onboarding':
      return {
        badge: 'Setup started',
        tone: 'progress',
        headline: 'Your bank payout setup isn’t finished',
        body:
          'Stripe still needs a few details before your earnings can reach ' +
          'your bank account. You can pick up where you left off.',
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
        badge: status.connect_routing_enabled ? 'Active' : 'Ready',
        tone: 'good',
        // Two different facts, and conflating them is the one claim
        // that would be untrue. Stripe accepting the details is not
        // the same as Fresh Collective having switched this creator's
        // sales over — that needs a separate decision, and until it is
        // made the old headline ("ready to pay you") promised
        // something that had not happened.
        headline: payoutReadyHeadline(status),
        body: status.connect_routing_enabled
          ? 'Your Stripe account can receive funds and pay them into your '
            + 'bank account.'
          : 'Your Stripe account can receive funds and pay them into your '
            + 'bank account. Fresh Collective still handles your payouts '
            + 'for now — nothing about how you are paid has changed yet.',
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
