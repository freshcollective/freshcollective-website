import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { getMe } from '@/lib/serverApi'

/**
 * `/world` auth guard. Mirrors the /dashboard pattern: require a session
 * and completed onboarding before the World experience is shown.
 */
export default async function WorldLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  const profile = await getMe()
  if (profile && !profile.has_completed_onboarding) {
    redirect('/onboarding')
  }

  return <>{children}</>
}
