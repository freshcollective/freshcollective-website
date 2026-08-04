'use client'

/**
 * CompleteFlow — the client-side state machine for /checkout/complete.
 *
 * The server component fetches a safe summary of the PurchaseIntent
 * (status, plan display name, claim_email, whether an account exists
 * for that email, whether the current viewer has an active session
 * that matches the intent's consumer) and hands it to this component.
 * From there, the client picks one of seven rendered states honestly:
 *
 *   consumed-by-me     → "Welcome" splash + auto-redirect to /creator-studio
 *   paid-auto-claim    → POST /claim → welcome
 *   paid-signup-needed → signup form (email locked to claim_email)
 *   paid-sign-in       → "Sign in to activate" prompt
 *   paid-wrong-user    → "This purchase belongs to X" warning
 *   pending            → "Waiting for payment confirmation" (polls)
 *   expired-or-cancelled → "This checkout was cancelled"
 *
 * There is no prototype language, no preview URL. Every visible
 * action reflects real backend state.
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import Button from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl, extractErrorMessage } from '@/lib/api'
import type { PurchaseByTokenResponse } from '@/lib/serverApi'

const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

interface Props {
  token: string
  initialData: PurchaseByTokenResponse
  currentUserEmail: string | null
  currentUserName: string | null
}

type Flow =
  | { kind: 'welcome' }
  | { kind: 'auto-claim' }
  | { kind: 'signup' }
  | { kind: 'signin-needed' }
  | { kind: 'wrong-user' }
  | { kind: 'pending' }
  | { kind: 'expired-or-cancelled' }
  | { kind: 'error'; message: string }

export default function CompleteFlow({
  token, initialData, currentUserEmail, currentUserName,
}: Props) {
  const router = useRouter()
  const [flow, setFlow] = useState<Flow>(() =>
    resolveFlow(initialData, currentUserEmail),
  )

  // Poll while payment is pending — Stripe webhook may arrive slightly
  // after the visitor returns from Checkout.
  useEffect(() => {
    if (flow.kind !== 'pending') return
    const started = Date.now()
    const timer = setInterval(async () => {
      if (Date.now() - started > 30_000) {
        // Give up gracefully — the visitor can refresh.
        clearInterval(timer)
        return
      }
      try {
        const res = await fetch(
          apiUrl(`/api/purchases/by-token?token=${encodeURIComponent(token)}`),
          { credentials: 'include', cache: 'no-store' },
        )
        if (!res.ok) return
        const data: PurchaseByTokenResponse = await res.json()
        const next = resolveFlow(data, currentUserEmail)
        if (next.kind !== 'pending') {
          clearInterval(timer)
          setFlow(next)
        }
      } catch {
        // ignore — retry on the next tick
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [flow.kind, token, currentUserEmail])

  // Auto-claim as soon as we know it's safe.
  useEffect(() => {
    if (flow.kind !== 'auto-claim') return
    (async () => {
      try {
        const res = await fetch(apiUrl('/api/purchases/claim'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ token }),
        })
        if (res.ok) {
          setFlow({ kind: 'welcome' })
          return
        }
        const body = await res.json().catch(() => ({}))
        setFlow({ kind: 'error', message: extractErrorMessage(body) })
      } catch {
        setFlow({ kind: 'error', message: 'Could not reach the server.' })
      }
    })()
  }, [flow.kind, token])

  // Welcome splash → auto-redirect to Creator Studio.
  useEffect(() => {
    if (flow.kind !== 'welcome') return
    const t = setTimeout(() => router.push('/creator-studio'), 1800)
    return () => clearTimeout(t)
  }, [flow.kind, router])

  return (
    <div className="mx-auto max-w-[560px]">
      {renderFlow(flow, {
        planDisplayName: initialData.plan_display_name,
        claimEmail: initialData.claim_email,
        currentUserEmail,
        currentUserName,
        token,
        setFlow,
      })}
    </div>
  )
}

// ---------------------------------------------------------------------
// State selection
// ---------------------------------------------------------------------

export function resolveFlow(
  data: PurchaseByTokenResponse,
  currentUserEmail: string | null,
): Flow {
  const email = (currentUserEmail ?? '').trim().toLowerCase()
  const claimEmail = (data.claim_email ?? '').trim().toLowerCase()

  if (data.status === 'consumed') {
    if (data.consumed_by_current_user) return { kind: 'welcome' }
    // Someone else has already claimed it — show a soft error rather
    // than pretend the purchase belongs to the viewer.
    return {
      kind: 'error',
      message:
        'This purchase has already been claimed on another account. If you believe that is not right, please contact support.',
    }
  }

  if (data.status === 'pending') return { kind: 'pending' }

  if (data.status === 'cancelled' || data.status === 'expired' || data.status === 'refunded') {
    return { kind: 'expired-or-cancelled' }
  }

  // data.status === 'paid' from here on.
  if (data.claim_token_expired) {
    return {
      kind: 'error',
      message:
        'This claim link has expired. Please contact support to have it re-issued.',
    }
  }

  // Not logged in yet.
  if (!email) {
    if (data.claim_email_has_account) return { kind: 'signin-needed' }
    return { kind: 'signup' }
  }

  // Logged in — check the current session matches the paying email.
  if (claimEmail && email !== claimEmail) return { kind: 'wrong-user' }

  return { kind: 'auto-claim' }
}

// ---------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------

interface RenderCtx {
  planDisplayName: string | null
  claimEmail: string | null
  currentUserEmail: string | null
  currentUserName: string | null
  token: string
  setFlow: (f: Flow) => void
}

function renderFlow(flow: Flow, ctx: RenderCtx): React.ReactNode {
  switch (flow.kind) {
    case 'welcome':
      return <Welcome planDisplayName={ctx.planDisplayName} />
    case 'auto-claim':
      return <ActivatingSplash planDisplayName={ctx.planDisplayName} />
    case 'pending':
      return <PendingWait />
    case 'expired-or-cancelled':
      return <CancelledCard />
    case 'signup':
      return <SignupCard {...ctx} />
    case 'signin-needed':
      return <SignInPromptCard {...ctx} />
    case 'wrong-user':
      return <WrongUserCard {...ctx} />
    case 'error':
      return <ErrorCard message={flow.message} />
  }
}

function Welcome({ planDisplayName }: { planDisplayName: string | null }) {
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
          letterSpacing: '-0.025em',
          color: NAVY,
        }}
      >
        Welcome to Fresh Collective.
      </h1>
      {planDisplayName && (
        <p
          className="mt-4 font-serif italic"
          style={{ color: TEAL_DEEP, fontSize: '1.15rem' }}
        >
          Your {planDisplayName} plan is active.
        </p>
      )}
      <p
        className="mt-6 text-[15px] italic"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Taking you to Creator Studio…
      </p>
      <div className="mt-8">
        <Link
          href="/creator-studio"
          className="inline-flex items-center rounded-full px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
            letterSpacing: '0.04em',
            boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
          }}
        >
          Continue to Creator Studio →
        </Link>
      </div>
    </div>
  )
}

function ActivatingSplash({ planDisplayName }: { planDisplayName: string | null }) {
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        Activating your {planDisplayName ?? 'Creator'} plan…
      </h1>
      <p
        className="mt-4 text-[15px] italic"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        This only takes a moment.
      </p>
    </div>
  )
}

function PendingWait() {
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        Confirming your payment…
      </h1>
      <p
        className="mt-4 max-w-[420px] text-[15px] italic mx-auto leading-relaxed"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Stripe is telling us about the payment. This usually takes a
        few seconds. This page will refresh itself.
      </p>
    </div>
  )
}

function CancelledCard() {
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        Checkout was cancelled.
      </h1>
      <p
        className="mt-4 text-[15px] italic"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        No payment was taken. You can choose a plan again whenever
        you&rsquo;re ready.
      </p>
      <div className="mt-8">
        <Link
          href="/for-creators#plans"
          className="text-[14px] font-semibold transition-opacity hover:opacity-80"
          style={{ color: TEAL_DEEP }}
        >
          Back to creator plans →
        </Link>
      </div>
    </div>
  )
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        We couldn&rsquo;t finish activating your plan.
      </h1>
      <p
        className="mt-4 max-w-[440px] mx-auto text-[15px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        {message}
      </p>
    </div>
  )
}

function SignInPromptCard({ claimEmail, token }: RenderCtx) {
  const nextParam = encodeURIComponent(`/checkout/complete?token=${token}`)
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        Sign in to activate your plan.
      </h1>
      {claimEmail && (
        <p
          className="mt-4 text-[15px] italic"
          style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
        >
          You&rsquo;ve already got an account under{' '}
          <span style={{ color: NAVY, fontStyle: 'normal', fontWeight: 600 }}>
            {claimEmail}
          </span>
          . Signing in will connect this purchase to it.
        </p>
      )}
      <div className="mt-8">
        <Link
          href={`/login?next=${nextParam}`}
          className="inline-flex items-center rounded-full px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
            letterSpacing: '0.04em',
            boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
          }}
        >
          Sign in
        </Link>
      </div>
    </div>
  )
}

function WrongUserCard({ claimEmail, currentUserEmail, token }: RenderCtx) {
  const nextParam = encodeURIComponent(`/checkout/complete?token=${token}`)
  return (
    <div className="text-center">
      <h1
        className="font-serif leading-[1.06]"
        style={{
          fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        You&rsquo;re signed in as a different account.
      </h1>
      <p
        className="mt-4 max-w-[460px] mx-auto text-[15px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        This purchase belongs to{' '}
        <span style={{ fontWeight: 600 }}>{claimEmail}</span>. You&rsquo;re
        currently signed in as{' '}
        <span style={{ fontWeight: 600 }}>{currentUserEmail}</span>. Sign
        out and back in with the correct account to activate the plan.
      </p>
      <div className="mt-8 flex justify-center gap-3">
        <Link
          href={`/login?next=${nextParam}`}
          className="inline-flex items-center rounded-full px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
            letterSpacing: '0.04em',
          }}
        >
          Switch accounts
        </Link>
      </div>
    </div>
  )
}

function SignupCard(ctx: RenderCtx) {
  const { token, claimEmail, planDisplayName, setFlow } = ctx
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    const form = e.currentTarget
    const name = (form.elements.namedItem('name') as HTMLInputElement).value.trim()
    const password = (form.elements.namedItem('password') as HTMLInputElement).value
    try {
      const res = await fetch(apiUrl('/api/purchases/claim-with-signup'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ token, name, password }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(extractErrorMessage(body) || 'Could not create your account.')
        return
      }
      setFlow({ kind: 'welcome' })
      // Ensure server components re-fetch with the new session cookie.
      router.refresh()
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="rounded-2xl bg-white p-8 md:p-10"
      style={{
        boxShadow: '0 24px 60px rgba(12, 24, 38, 0.10), 0 2px 8px rgba(12, 24, 38, 0.06)',
      }}
    >
      <div className="mb-6 text-center">
        <h1
          className="font-serif leading-[1.06]"
          style={{
            fontSize: 'clamp(1.75rem, 3.6vw, 2.25rem)',
            letterSpacing: '-0.02em',
            color: NAVY,
          }}
        >
          Create your Fresh Collective account
        </h1>
        {planDisplayName && (
          <p
            className="mt-3 font-serif italic"
            style={{ color: TEAL_DEEP, fontSize: '1.1rem' }}
          >
            One step from your {planDisplayName} plan.
          </p>
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
            value={claimEmail ?? ''}
            readOnly
            aria-readonly="true"
            className="w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 outline-none opacity-80"
          />
          <p className="mt-1.5 text-xs" style={{ color: '#718096' }}>
            Locked to the email used at Stripe Checkout.
          </p>
        </div>

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

        <Button type="submit" variant="primary" size="md" className="w-full" disabled={submitting}>
          {submitting ? 'Creating your account…' : 'Create account and activate'}
        </Button>
      </form>
    </div>
  )
}
