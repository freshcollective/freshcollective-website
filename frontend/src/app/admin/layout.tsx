import { headers } from 'next/headers'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import AdminShell from '@/components/admin/AdminShell'

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

  // Shared guard, but with the admin door. A stale-but-signed session
  // (JWT valid, User row gone) now bounces to /admin/login?next=…
  // instead of falling through to the "Access denied" screen with an
  // effectively-null user.
  const user = await requireAuthenticatedUser({ loginPath: '/admin/login' })

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
