import { redirect } from 'next/navigation'
import { cookies, headers } from 'next/headers'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import AdminShell from '@/components/admin/AdminShell'

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

async function getAdminUser(): Promise<User | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
  const valid = await verifySessionToken(session.value)
  if (!valid) return null
  try {
    const res = await fetch(apiUrl('/api/auth/me'), {
      headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const headerStore = await headers()
  // ``x-pathname`` is set by the proxy middleware (src/proxy.ts) so
  // this server layout can tell which /admin/* URL was requested. App
  // Router does not otherwise surface the current pathname to a layout.
  // Falls back to /admin so the guard fails safe when the header is
  // missing (e.g. during a direct programmatic render).
  const pathname = headerStore.get('x-pathname') ?? '/admin'

  // The admin login page must render WITHOUT the AdminShell chrome and
  // WITHOUT the auth guard — it's the door in. Everything else under
  // /admin/* stays gated.
  if (pathname === '/admin/login' || pathname.startsWith('/admin/login/')) {
    return children
  }

  const user = await getAdminUser()

  if (!user) {
    redirect(`/admin/login?next=${encodeURIComponent(pathname)}`)
  }

  if (user.role !== 'admin') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#F8F9FA]">
        <div className="text-center">
          <h1 className="mb-2 text-xl font-bold text-[#0F172A]">Access denied</h1>
          <p className="mb-6 text-[14px] text-[#000000]">
            You need admin access to view this page.
          </p>
          <a
            href="/dashboard"
            className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
          >
            Back to Your World
          </a>
        </div>
      </div>
    )
  }

  return (
    <AdminShell userEmail={user.email}>
      {children}
    </AdminShell>
  )
}
