import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'

/**
 * `/world` auth guard. Requires a session; the Fresh Collective
 * orientation is no longer a gate — it's an optional card in Your
 * World.
 */
export default async function WorldLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  return <>{children}</>
}
