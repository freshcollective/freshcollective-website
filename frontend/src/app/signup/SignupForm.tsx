'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl, extractErrorMessage } from '@/lib/api'

function getSafeRedirect(next?: string): string {
  // Default post-signup destination is Your World. The Fresh Collective
  // orientation is now optional and discoverable there — signup is no
  // longer expected to funnel every new account through the tour.
  // Contextual entry points (join a Collective, buy a Pathway, book a
  // Gathering) pass their own `next` param and remain honored.
  if (!next) return '/dashboard'
  if (/^\/(?!\/|\\)/.test(next)) return next
  return '/dashboard'
}

type CheckoutContext =
  | {
      kind: 'pathway'
      pathwayTitle: string
      optionName: string | null
      optionDescription: string | null
      priceLabel: string | null
    }
  | { kind: 'gathering'; gatheringTitle: string; priceLabel: string | null }

function buildSignupSubcopy(ctx: CheckoutContext): string {
  const tail = ' Create a free account so we can save your access and connect your payment to your profile.'
  if (ctx.kind === 'gathering') {
    const price = ctx.priceLabel ? ` for ${ctx.priceLabel}` : ''
    return `You're buying a ticket to ${ctx.gatheringTitle}${price}.${tail}`
  }
  // pathway
  if (ctx.optionName) {
    const desc = ctx.optionDescription ? ` — ${ctx.optionDescription}` : ''
    const price = ctx.priceLabel ? ` for ${ctx.priceLabel}` : ''
    return `You're choosing ${ctx.optionName}${desc}${price}.${tail}`
  }
  if (ctx.priceLabel) {
    return `You're unlocking ${ctx.pathwayTitle} for ${ctx.priceLabel}.${tail}`
  }
  return `Create a free account to continue with ${ctx.pathwayTitle}.`
}

export default function SignupForm({
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
    const name = (form.elements.namedItem('name') as HTMLInputElement).value.trim()
    const email = (form.elements.namedItem('email') as HTMLInputElement).value.trim()
    const password = (form.elements.namedItem('password') as HTMLInputElement).value

    try {
      const res = await fetch(apiUrl('/api/auth/signup'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name, email, password }),
      })

      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: 'Unable to create account.' }))
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

  const loginHref = nextUrl ? `/login?next=${encodeURIComponent(nextUrl)}` : '/login'

  return (
    <div
      className="w-full max-w-[440px] rounded-2xl bg-white p-8 md:p-10"
      style={{
        boxShadow: '0 24px 60px rgba(5, 11, 20, 0.35), 0 2px 8px rgba(5, 11, 20, 0.20)',
      }}
    >
      {/* Brand mark — matches the login card exactly. */}
      <div className="mb-7 flex justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/fresh-collective-logo-navy-gold-white.png"
          alt="Fresh Collective"
          style={{ height: '44px', width: 'auto' }}
        />
      </div>

      <div className="mb-7 text-center">
        {checkoutContext ? (
          <>
            <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              {checkoutContext.kind === 'gathering'
                ? 'Create an account to continue to ticket checkout'
                : 'Create your account to continue'}
            </h1>
            <p className="text-sm leading-relaxed" style={{ color: '#5A6B7D' }}>
              {buildSignupSubcopy(checkoutContext)}
            </p>
          </>
        ) : (
          <>
            <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Create your account
            </h1>
            <p
              className="text-[14px] italic leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              Your world begins here.
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
          <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-navy-900">
            Full name
          </label>
          <input
            id="name"
            name="name"
            type="text"
            autoComplete="name"
            required
            placeholder="Your name"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
        </div>

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
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-navy-900">
            Password
          </label>
          <PasswordInput
            id="password"
            name="password"
            autoComplete="new-password"
            required
            minLength={8}
            placeholder="At least 8 characters"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100"
          />
          <p className="mt-1.5 text-xs" style={{ color: '#718096' }}>Minimum 8 characters.</p>
        </div>

        <Button type="submit" variant="primary" size="md" className="w-full" disabled={loading}>
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              Creating account…
            </span>
          ) : (
            'Create account'
          )}
        </Button>
      </form>

      {/* Account-switch link — mirrors the login card's "New to FC?" line. */}
      <p className="mt-6 text-center text-sm" style={{ color: '#5A6B7D' }}>
        Already have an account?{' '}
        <Link
          href={loginHref}
          className="font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
        >
          Log in
        </Link>
      </p>
    </div>
  )
}
