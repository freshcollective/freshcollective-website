import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'

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
  await requireAuthenticatedUser()
  return <>{children}</>
}
