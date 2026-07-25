'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl, extractErrorMessage } from '@/lib/api'

/** Only accept safe absolute-path redirects; default to /admin. */
function getSafeAdminRedirect(next?: string): string {
  if (!next) return '/admin'
  // Must start with '/', must not be a protocol-relative URL or backslash.
  if (!/^\/(?!\/|\\)/.test(next)) return '/admin'
  // Never let this login send a caller outside the admin area.
  if (!next.startsWith('/admin')) return '/admin'
  return next
}

interface Props {
  nextUrl?: string
}

/**
 * Admin-facing login form. Submits to the shared /api/auth/login
 * endpoint (no backend change), then verifies the resulting session
 * belongs to an admin. Non-admin sessions are immediately signed out
 * with a clear message so this door only opens for administrators.
 */
export default function AdminLoginForm({ nextUrl }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setLoading(true)

    const form = e.currentTarget
    const email = (form.elements.namedItem('email') as HTMLInputElement).value.trim()
    const password = (form.elements.namedItem('password') as HTMLInputElement).value

    try {
      const loginRes = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })

      if (!loginRes.ok) {
        const data = await loginRes.json().catch(() => ({ detail: 'Invalid email or password.' }))
        setError(extractErrorMessage(data))
        return
      }

      // Session established. Now verify it belongs to an admin. If it
      // doesn't, immediately sign out and refuse — this door is for
      // administrators only.
      const meRes = await fetch(apiUrl('/api/auth/me'), { credentials: 'include' })
      if (!meRes.ok) {
        setError('Signed in, but could not verify your role. Please try again.')
        await fetch(apiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' }).catch(() => {})
        return
      }
      const me = await meRes.json().catch(() => null) as { role?: string } | null
      if (!me || me.role !== 'admin') {
        setError('This login is for administrators only.')
        await fetch(apiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' }).catch(() => {})
        return
      }

      router.push(getSafeAdminRedirect(nextUrl))
      router.refresh()
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="w-full max-w-[420px] rounded-2xl bg-white p-8"
      style={{
        border: '1px solid #E2E8F0',
        boxShadow: '0 10px 30px rgba(12, 24, 38, 0.06), 0 2px 6px rgba(12, 24, 38, 0.03)',
      }}
    >
      {/* Brand — matches the admin sidebar mark rather than the
          consumer-facing wordmark used at /login. */}
      <div className="mb-6 flex items-center gap-2.5">
        <span
          aria-hidden="true"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-teal-500"
        >
          <span className="h-3 w-3 rounded-sm bg-white" />
        </span>
        <div>
          <div className="text-[13px] font-semibold leading-none" style={{ color: '#0F172A' }}>
            Fresh Collective
          </div>
          <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
            World Management
          </div>
        </div>
      </div>

      <div className="mb-6">
        <h1 className="font-serif text-[22px] leading-tight text-navy-900">
          Sign in to World Management.
        </h1>
        <p
          className="mt-2 text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          This entrance is for administrators. If you are looking for your Fresh Collective account,{' '}
          <Link href="/login" className="text-teal-700 underline underline-offset-2 hover:text-teal-800">
            sign in here
          </Link>
          .
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="mb-1.5 block text-[13px] font-medium text-navy-900">
            Email address
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="password" className="text-[13px] font-medium text-navy-900">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-[11.5px] text-teal-700 underline-offset-4 transition-colors hover:text-teal-800 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <PasswordInput
            id="password"
            name="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            className="w-full rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 text-[14px] text-navy-900 placeholder-slate-400 outline-none transition-colors focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="mt-2 w-full rounded-lg px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Signing in…
            </span>
          ) : (
            'Sign in'
          )}
        </button>
      </form>
    </div>
  )
}
