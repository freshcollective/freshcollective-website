import { redirect } from 'next/navigation'
import { getSession } from '@/lib/auth/session'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Server-side auth guard — middleware is the first line of defence;
  // this layout provides defence-in-depth
  const session = await getSession()
  if (!session) redirect('/login')

  return <>{children}</>
}
