'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl, extractErrorMessage } from '@/lib/api'

function getSafeRedirect(next?: string): string {
  if (!next) return '/dashboard'
  if (/^\/(?!\/|\\)/.test(next)) return next
  return '/dashboard'
}

type CheckoutContext =
  | { kind: 'pathway'; pathwayTitle: string }
  | { kind: 'gathering'; gatheringTitle: string }

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

  const signupHref = nextUrl ? `/signup?next=${encodeURIComponent(nextUrl)}` : '/signup'

  return (
    <div
      className="w-full max-w-[440px] rounded-2xl bg-white p-8 md:p-10"
      style={{
        boxShadow: '0 24px 60px rgba(5, 11, 20, 0.35), 0 2px 8px rgba(5, 11, 20, 0.20)',
      }}
    >
      {/* Brand mark — full wordmark, centered and given room to breathe.
          Larger and deliberately placed rather than a tiny floating icon. */}
      <div className="mb-7 flex justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/fresh-collective-logo-navy-gold-white.png"
          alt="Fresh Collective"
          style={{ height: '44px', width: 'auto' }}
        />
      </div>

      <div className="mb-7 text-center">
        {checkoutContext?.kind === 'pathway' ? (
          <>
            <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Log in to continue
            </h1>
            <p className="text-sm text-[#5A6B7D]">
              Continuing with{' '}
              <span className="font-medium text-navy-900">{checkoutContext.pathwayTitle}</span>.
            </p>
          </>
        ) : checkoutContext?.kind === 'gathering' ? (
          <>
            <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Log in to buy your ticket
            </h1>
            <p className="text-sm text-[#5A6B7D]">
              For{' '}
              <span className="font-medium text-navy-900">{checkoutContext.gatheringTitle}</span>.
            </p>
          </>
        ) : (
          <>
            <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Welcome back
            </h1>
            <p
              className="text-[14px] italic leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              Your world is ready when you are.
            </p>
          </>
        )}
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
          <PasswordInput
            id="password"
            name="password"
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

      {/* Sign-up prompt — sits below the primary action so returning users
          hit Log in first; new visitors still find the invitation. */}
      <p className="mt-6 text-center text-sm" style={{ color: '#5A6B7D' }}>
        New to Fresh Collective?{' '}
        <Link
          href={signupHref}
          className="font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
        >
          Join us
        </Link>
      </p>
    </div>
  )
}
