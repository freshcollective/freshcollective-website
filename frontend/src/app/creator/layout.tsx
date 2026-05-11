import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import Link from 'next/link'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { getMe } from '@/lib/serverApi'

export default async function CreatorLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  const authenticated = token ? await verifySessionToken(token) : false
  if (!authenticated) redirect('/login')

  const profile = await getMe()
  if (!profile || !['creator', 'admin'].includes(profile.role)) {
    redirect('/dashboard')
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5 md:px-10">
          <div className="flex items-center gap-3">
            <Link href="/creator" className="font-serif text-lg text-navy-900 hover:text-teal-600">
              Creator Studio
            </Link>
            <span className="text-slate-200">·</span>
            <Link href="/dashboard" className="text-sm text-slate-400 hover:text-navy-700">
              Fresh Collective
            </Link>
          </div>
          <Link href="/dashboard" className="text-sm text-slate-400 hover:text-navy-700">
            ← Back to platform
          </Link>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  )
}
