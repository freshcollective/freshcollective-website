import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'

/**
 * `/world` auth guard. Requires a session; the Fresh Collective
 * orientation is no longer a gate — it's an optional card in Your
 * World.
 */
export default async function WorldLayout({ children }: { children: React.ReactNode }) {
  await requireAuthenticatedUser()
  return <>{children}</>
}
