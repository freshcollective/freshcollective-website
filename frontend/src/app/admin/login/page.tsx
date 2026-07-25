import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import { apiUrl } from '@/lib/api'
import { verifySessionToken, SESSION_COOKIE } from '@/lib/session'
import AdminLoginForm from './AdminLoginForm'

export const metadata = { title: 'Sign in — World Management' }

/**
 * Admin login page — a separate, quieter door into World Management
 * that visually matches the light editorial admin shell. Uses the
 * shared /api/auth/login endpoint but role-gates the session client-
 * side so only administrators can pass through.
 *
 * If a signed-in admin visits this page directly, we send them
 * straight through to the admin area rather than making them log in
 * again.
 */
export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>
}) {
  const { next } = await searchParams

  // Auto-forward already-signed-in admins.
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (session) {
    const valid = await verifySessionToken(session.value)
    if (valid) {
      try {
        const res = await fetch(apiUrl('/api/auth/me'), {
          headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
          cache: 'no-store',
        })
        if (res.ok) {
          const me = await res.json().catch(() => null)
          if (me?.role === 'admin') {
            const dest = next && next.startsWith('/admin') ? next : '/admin'
            redirect(dest)
          }
        }
      } catch {
        // Ignore — fall through to the login form.
      }
    }
  }

  return (
    <div
      className="flex min-h-screen items-center justify-center px-6 py-10"
      style={{ background: '#F8F9FA' }}
    >
      <AdminLoginForm nextUrl={next} />
    </div>
  )
}
