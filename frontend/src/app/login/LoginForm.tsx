'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import AuthCard from '@/components/layout/AuthCard'
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

  // The heading + subtitle differ depending on whether the visitor
  // arrived from a purchase flow. AuthCard's ``title`` / ``subtitle``
  // props take React nodes so the pathway/gathering context can still
  // render inline emphasis on the title's second line.
  let title: React.ReactNode = 'Welcome back'
  let subtitle: React.ReactNode = 'Your world is ready when you are.'
  if (checkoutContext?.kind === 'pathway') {
    title = 'Log in to continue'
    subtitle = (
      <>
        Continuing with{' '}
        <span className="font-medium text-navy-900">{checkoutContext.pathwayTitle}</span>.
      </>
    )
  } else if (checkoutContext?.kind === 'gathering') {
    title = 'Log in to buy your ticket'
    subtitle = (
      <>
        For{' '}
        <span className="font-medium text-navy-900">{checkoutContext.gatheringTitle}</span>.
      </>
    )
  }

  return (
    <AuthCard title={title} subtitle={subtitle} error={error}>
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
    </AuthCard>
  )
}
