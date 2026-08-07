import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'

/**
 * `/build-your-collective` — the guided creator ritual (Atlas v1.2).
 *
 * Auth guard: requires a session. Member orientation is no longer a
 * gate — Creators arrive here via /creator-onboarding, which owns
 * the Creator-specific welcome. Members without a completed
 * orientation still reach this route through the ordinary Creator
 * activation flow.
 */
export default async function BuildYourCollectiveLayout({
  children,
}: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  return <>{children}</>
}
