import AuthPageShell, { AuthTitleAccent } from '@/components/layout/AuthPageShell'
import SignupForm from './SignupForm'
import { getPathwayOverview, getSpaceEvent } from '@/lib/serverApi'
import type { PathwayWithSteps, EventDetail } from '@/types/platform'

interface Props {
  searchParams: Promise<{ next?: string }>
}

/**
 * Discriminated union — the signup form renders a different helper line
 * for "unlock a pathway" vs "buy a Gathering ticket".
 */
export type CheckoutContext =
  | {
      kind: 'pathway'
      pathwayTitle: string
      optionName: string | null
      optionDescription: string | null
      priceLabel: string | null
    }
  | { kind: 'gathering'; gatheringTitle: string; priceLabel: string | null }

function fmtPrice(cents: number, currency: string): string {
  const sym = currency.toUpperCase() === 'AUD' ? '$' : currency
  const n = cents / 100
  return `${sym}${n % 1 === 0 ? n.toFixed(0) : n.toFixed(2)} ${currency.toUpperCase()}`
}

async function getCheckoutContext(next?: string): Promise<CheckoutContext | null> {
  if (!next) return null

  // Pathway purchase — existing pattern.
  const pathwayMatch = next.match(/^\/spaces\/([^/?#]+)\/pathways\/([^/?#]+)\/checkout/)
  if (pathwayMatch) {
    const [, spaceSlug, pathwaySlug] = pathwayMatch
    try {
      const pathway = (await getPathwayOverview(spaceSlug, pathwaySlug)) as PathwayWithSteps | null
      if (!pathway) return null

      const qIdx = next.indexOf('?')
      const qs = qIdx >= 0 ? new URLSearchParams(next.slice(qIdx + 1)) : null
      const optionId = qs?.get('payment_option_id') ?? null
      const scheduleId = qs?.get('payment_option_schedule_id') ?? null

      if (optionId && pathway.payment_options.length > 0) {
        const opt = pathway.payment_options.find(o => o.id === optionId) ?? null
        const sched = (opt && scheduleId)
          ? (opt.schedules.find(s => s.id === scheduleId) ?? null)
          : null
        const priceCents = sched?.total_amount_cents ?? opt?.effective_price_cents ?? null
        const currency = opt?.currency ?? 'AUD'
        return {
          kind: 'pathway',
          pathwayTitle: pathway.title,
          optionName: opt?.name ?? null,
          optionDescription: opt?.description ?? null,
          priceLabel: priceCents != null ? fmtPrice(priceCents, currency) : null,
        }
      }

      return {
        kind: 'pathway',
        pathwayTitle: pathway.title,
        optionName: null,
        optionDescription: null,
        priceLabel: pathway.price_cents != null
          ? fmtPrice(pathway.price_cents, pathway.currency ?? 'AUD')
          : null,
      }
    } catch {
      return null
    }
  }

  // Standalone Gathering ticket purchase.
  const gatheringMatch = next.match(/^\/spaces\/([^/?#]+)\/events\/([^/?#]+)/)
  if (gatheringMatch) {
    const [, spaceSlug, eventId] = gatheringMatch
    try {
      const event = (await getSpaceEvent(spaceSlug, eventId)) as EventDetail | null
      if (!event) return null
      if (event.booking_access_type !== 'paid_separately') return null
      const priceLabel = event.ticket_price_cents != null && event.ticket_currency
        ? fmtPrice(event.ticket_price_cents, event.ticket_currency)
        : null
      return { kind: 'gathering', gatheringTitle: event.title, priceLabel }
    } catch {
      return null
    }
  }

  return null
}

/**
 * Sign-up page — shares the AuthPageShell with /login so both pages read
 * as one coherent entry experience. This file owns only the sign-up
 * welcome copy and the sign-up form.
 */
export default async function SignUpPage({ searchParams }: Props) {
  const { next } = await searchParams
  const checkoutContext = await getCheckoutContext(next)

  return (
    <AuthPageShell
      welcomeTitle={
        <>
          <AuthTitleAccent>Step into a world</AuthTitleAccent>
          <br />
          built for belonging.
        </>
      }
      welcomeSubtitle="Discover Collectives, join Gatherings and create what matters to you."
    >
      <SignupForm nextUrl={next} checkoutContext={checkoutContext} />
    </AuthPageShell>
  )
}
