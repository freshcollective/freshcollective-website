import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import WorldShell from '@/components/layout/WorldShell'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Uses the shared guard so a stale-but-signed session cookie (JWT
  // signature valid, referenced User no longer exists) cannot land on
  // /dashboard and render "Welcome back, friend." — instead we bounce
  // through /login and preserve ``next=/dashboard`` so the intended
  // destination is reached after signing in.
  await requireAuthenticatedUser()

  // Fresh Collective orientation is now optional and discoverable
  // from Your World — never a gate. The page itself renders a soft
  // "New to Fresh Collective?" card when
  // ``has_completed_onboarding`` is false.
  return <WorldShell>{children}</WorldShell>
}
