import Link from 'next/link'
import { cookies } from 'next/headers'
import { apiUrl } from '@/lib/api'
import { SESSION_COOKIE } from '@/lib/session'
import ChangePasswordForm from '@/components/settings/ChangePasswordForm'
import LogoutButton from '@/components/layout/LogoutButton'

/**
 * Admin Account — where an administrator manages the credentials for
 * their own admin identity. Deliberately separate from World-level
 * settings (which affect the platform, not the person). Reuses the
 * shared ChangePasswordForm and existing /api/auth/me/change-password
 * endpoint, so no backend changes are introduced.
 */

interface Me { id: string; email: string; name: string | null; role: string }

async function getMe(): Promise<Me | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
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

export default async function AdminAccountPage() {
  const me = await getMe()

  return (
    <div className="mx-auto max-w-[720px]">

      {/* Page header */}
      <div className="mb-8">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Admin
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Your account</h1>
        <p
          className="mt-2 max-w-md text-[14.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          The credentials that let you sign in to World Management.
        </p>
      </div>

      {/* Email — read-only, changing email happens through support */}
      <section className="mb-6 rounded-2xl bg-white p-6" style={{ border: '1px solid #E2E8F0' }}>
        <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Email address
        </p>
        <p className="text-[15px] text-navy-900">
          {me?.email ?? <span className="italic text-slate-400">Unknown</span>}
        </p>
        <p className="mt-1 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
          To change your email, contact Fresh Collective support.
        </p>
      </section>

      {/* Password change */}
      <section className="mb-6 rounded-2xl bg-white p-6" style={{ border: '1px solid #E2E8F0' }}>
        <p className="mb-4 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Password
        </p>
        <ChangePasswordForm />
        <p className="mt-4 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}>
          Forgotten your password?{' '}
          <Link href="/forgot-password" className="text-teal-700 not-italic underline underline-offset-2 hover:text-teal-800">
            Reset it here
          </Link>
          .
        </p>
      </section>

      {/* Sign out */}
      <section className="rounded-2xl bg-white p-6" style={{ border: '1px solid #E2E8F0' }}>
        <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Sign out
        </p>
        <p className="mb-4 text-[13.5px] leading-relaxed text-slate-600">
          You are signed in as {me?.email ?? 'an administrator'} on this device.
        </p>
        <LogoutButton
          className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-[13px] font-medium text-slate-700 transition-colors hover:border-red-200 hover:text-red-500"
        />
      </section>

    </div>
  )
}
