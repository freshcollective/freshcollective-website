'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { apiUrl, extractErrorMessage } from '@/lib/api'

function getSafeRedirect(next?: string): string {
  if (!next) return '/dashboard'
  if (/^\/(?!\/|\\)/.test(next)) return next
  return '/dashboard'
}

type CheckoutContext = {
  pathwayTitle: string
}

export default function LoginForm({
  nextUrl,
  checkoutContext,
}: {
  nextUrl?: string
  checkoutContext?: CheckoutContext | null
}) {
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
      const res = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Invalid email or password.' }))
        setError(extractErrorMessage(data))
        return
      }

      router.push(getSafeRedirect(nextUrl))
      router.refresh()
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="w-full max-w-sm rounded-xl border border-border bg-surface p-8 md:p-10"
      style={{ boxShadow: 'var(--fc-shadow-md)' }}
    >
      <div className="mb-8">
        <div className="mb-5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/brand/fresh-collective-logo-navy-gold-white.png"
            alt="Fresh Collective"
            style={{ height: '34px', width: 'auto' }}
          />
        </div>
        {checkoutContext ? (
          <>
            <h1 className="mb-2 font-serif text-3xl text-navy-900">Log in to continue</h1>
            <p className="mb-2 text-sm text-[#718096]">
              Continuing with{' '}
              <span className="font-medium text-navy-900">{checkoutContext.pathwayTitle}</span>.
            </p>
          </>
        ) : (
          <h1 className="mb-2 font-serif text-3xl text-navy-900">Welcome back.</h1>
        )}
        <p className="text-sm text-[#718096]">
          Don&apos;t have an account?{' '}
          <Link
            href={nextUrl ? `/signup?next=${encodeURIComponent(nextUrl)}` : '/signup'}
            className="text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
          >
            Sign up
          </Link>
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-navy-900">
            Email address
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            placeholder="you@example.com"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <label htmlFor="password" className="text-sm font-medium text-navy-900">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

        <Button type="submit" variant="primary" size="md" className="w-full" disabled={loading}>
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Signing in…
            </span>
          ) : (
            'Log in'
          )}
        </Button>
      </form>
    </div>
  )
}
