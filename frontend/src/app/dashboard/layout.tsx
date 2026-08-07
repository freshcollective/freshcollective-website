import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import WorldShell from '@/components/layout/WorldShell'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  // Fresh Collective orientation is now optional and discoverable
  // from Your World — never a gate. The page itself renders a soft
  // "New to Fresh Collective?" card when
  // ``has_completed_onboarding`` is false.
  return <WorldShell>{children}</WorldShell>
}
