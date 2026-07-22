import AuthPageShell, { AuthTitleAccent } from '@/components/layout/AuthPageShell'
import LoginForm from './LoginForm'
import { getPathwayOverview, getSpaceEvent } from '@/lib/serverApi'
import type { PathwayWithSteps, EventDetail } from '@/types/platform'

/**
 * Discriminated shape so the login form can render either
 *   "Log in to continue with <pathway title>"
 * or
 *   "Log in to buy your ticket for <Gathering title>"
 * with a single prop.
 */
export type CheckoutContext =
  | { kind: 'pathway'; pathwayTitle: string }
  | { kind: 'gathering'; gatheringTitle: string }

async function getCheckoutContext(next?: string): Promise<CheckoutContext | null> {
  if (!next) return null

  // Pathway purchase — existing pattern (unchanged).
  const pathwayMatch = next.match(/^\/spaces\/([^/?#]+)\/pathways\/([^/?#]+)\/checkout/)
  if (pathwayMatch) {
    const [, spaceSlug, pathwaySlug] = pathwayMatch
    try {
      const pathway = (await getPathwayOverview(spaceSlug, pathwaySlug)) as PathwayWithSteps | null
      if (!pathway) return null
      return { kind: 'pathway', pathwayTitle: pathway.title }
    } catch {
      return null
    }
  }

  // Standalone Gathering ticket — the buyer clicked "Buy your ticket"
  // while signed out. The return URL round-trips them back to the
  // detail page (see GatheringTicketPurchaseClient.nextForAuth).
  // Trust boundary: we only look up the title for the auth-page copy;
  // no price / access / user state is read from the URL.
  const gatheringMatch = next.match(/^\/spaces\/([^/?#]+)\/events\/([^/?#]+)/)
  if (gatheringMatch) {
    const [, spaceSlug, eventId] = gatheringMatch
    try {
      const event = (await getSpaceEvent(spaceSlug, eventId)) as EventDetail | null
      if (!event) return null
      if (event.booking_access_type !== 'paid_separately') return null
      return { kind: 'gathering', gatheringTitle: event.title }
    } catch {
      return null
    }
  }

  return null
}

/**
 * Login page — uses the shared AuthPageShell (full-bleed Atlas artwork,
 * navy overlay, transparent header, minimal footer). This file owns only
 * the login-specific welcome copy and the login form.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams
  const checkoutContext = await getCheckoutContext(next)

  return (
    <AuthPageShell
      welcomeTitle={
        <>
          <AuthTitleAccent>Welcome back</AuthTitleAccent>
          <br />
          to your world.
        </>
      }
      welcomeSubtitle="Return to your Collectives, pathways and Gatherings."
    >
      <LoginForm nextUrl={next} checkoutContext={checkoutContext} />
    </AuthPageShell>
  )
}
