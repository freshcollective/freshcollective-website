import Link from 'next/link'
import { getMe } from '@/lib/serverApi'
import ChangePasswordForm from '@/components/settings/ChangePasswordForm'
import LogoutButton from '@/components/layout/LogoutButton'
import type { UserProfile } from '@/types/platform'

export default async function SettingsSecurityPage() {
  const profile: UserProfile | null = await getMe()

  return (
    <div>
      <div className="mb-8">
        <h2 className="mb-1 font-serif text-xl text-navy-900">Security</h2>
        <p className="text-sm text-slate-500">
          Manage your account access and credentials.
        </p>
      </div>

      {/* Email */}
      <section className="mb-8">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Email address
        </h3>
        <div className="rounded-xl border border-border bg-surface px-6 py-4">
          <p className="text-sm text-navy-800">{profile?.email}</p>
          <p className="mt-0.5 text-xs text-slate-400">
            To change your email, contact support.
          </p>
        </div>
      </section>

      {/* Password */}
      <section className="mb-8">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Password
        </h3>
        <div className="rounded-xl border border-border bg-surface px-6 py-5">
          <ChangePasswordForm />
        </div>
        <p className="mt-2 text-xs text-slate-400">
          Forgotten your password?{' '}
          <Link href="/forgot-password" className="text-teal-600 hover:underline">
            Reset it here
          </Link>
          .
        </p>
      </section>

      {/* Sign out */}
      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Sign out
        </h3>
        <div className="rounded-xl border border-border bg-surface px-6 py-5">
          <p className="mb-4 text-sm text-slate-500">
            You are signed in on this device. Sign out to end your session.
          </p>
          <LogoutButton className="rounded-lg border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50" />
        </div>
      </section>
    </div>
  )
}
