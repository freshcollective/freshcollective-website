import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import WorldShell from '@/components/layout/WorldShell'

export default async function NotificationsLayout({ children }: { children: React.ReactNode }) {
  await requireAuthenticatedUser()
  return <WorldShell>{children}</WorldShell>
}
