'use client'

/**
 * CommunityCollectiveSignup — the real, live signup for the free
 * Community Collective plan.
 *
 * Unlike PrototypeSignupForm (still used by the paid plans, which reach
 * their account step through Stripe checkout), this component actually:
 *   - POSTs /api/auth/signup to create the Fresh Collective account
 *   - POSTs /api/creator/community/start to grant Creator capability
 *   - forwards into the existing /creator-onboarding flow
 *
 * Why it is a resumable state machine
 * -----------------------------------
 * Signup deliberately creates an *unverified* account (SEC-009), and
 * Creator capability is a trust action that requires verification. So
 * the two steps cannot run back-to-back for a brand-new account: there
 * is an email round-trip in between.
 *
 * Rather than thread "I wanted Community" through the verification
 * email (which would mean changing a shared, all-users flow), this
 * component renders whichever step the visitor is actually at and the
 * page stays safe to revisit or reload:
 *
 *   signed out                        → the signup form
 *   signed in, email unverified       → check your inbox, then continue
 *   signed in, verified, not creator  → one button to open the plan
 *   signed in, already a creator      → straight on to onboarding
 *
 * Nothing here promises anything the backend has not already done. The
 * limits shown on the page are enforced server-side by
 * `app/creator/plan_guards.py`.
 */

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Button from '@/components/ui/Button'
import { PasswordInput } from '@/components/ui/PasswordInput'
import { apiUrl, extractErrorMessage } from '@/lib/api'
import { FreshCollectiveLogo } from '@/components/brand/FreshCollectiveBrand'

/** Which step the visitor is at, decided by the server from /api/auth/me. */
export type CommunityStage =
  | 'signed_out'
  | 'unverified'
  | 'ready'
  | 'already_creator'

const FIELD_CLASS =
  'w-full rounded-lg border border-border bg-surface px-4 py-3 text-sm text-navy-900 placeholder-[#718096] outline-none transition-colors focus:border-teal-500 focus:ring-2 focus:ring-teal-100'

const ONBOARDING_HREF = '/creator-onboarding'

export default function CommunityCollectiveSignup({
  stage: initialStage,
}: {
  stage: CommunityStage
}) {
  const router = useRouter()
  const [stage, setStage] = useState<CommunityStage>(initialStage)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [resent, setResent] = useState(false)

  /** Grant Creator capability and move into the existing onboarding. */
  async function openCommunityPlan() {
    setError(null)
    setBusy(true)
    try {
      const res = await fetch(apiUrl('/api/creator/community/start'), {
        method: 'POST',
        credentials: 'include',
      })
      if (!res.ok) {
        if (res.status === 403) {
          // Verification is the only 403 this endpoint raises.
          setStage('unverified')
          setError('Please confirm your email address first.')
          return
        }
        const data = await res
          .json()
          .catch(() => ({ detail: 'Unable to open your Collective.' }))
        setError(extractErrorMessage(data))
        return
      }
      const body = await res.json().catch(() => null)
      router.push(body?.next ?? ONBOARDING_HREF)
      router.refresh()
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function handleSignup(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setBusy(true)

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
        const data = await res
          .json()
          .catch(() => ({ detail: 'Unable to create account.' }))
        setError(extractErrorMessage(data))
        return
      }
      // The account exists and the visitor is signed in, but is not yet
      // verified — so Creator capability cannot be granted in this tick.
      setStage('unverified')
      router.refresh()
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function resendVerification() {
    setError(null)
    setBusy(true)
    try {
      const res = await fetch(apiUrl('/api/auth/verify-email/resend'), {
        method: 'POST',
        credentials: 'include',
      })
      // A cooldown response is not a failure worth alarming anyone about:
      // either way, a link is already on its way.
      setResent(res.ok || res.status === 429)
      if (!res.ok && res.status !== 429) {
        setError('Unable to send a new link right now. Please try again shortly.')
      }
    } catch {
      setError('Unable to connect to the server. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="w-full max-w-[440px] rounded-2xl bg-white p-8 md:p-10"
      style={{
        boxShadow: '0 24px 60px rgba(5, 11, 20, 0.35), 0 2px 8px rgba(5, 11, 20, 0.20)',
      }}
    >
      <div className="mb-6 flex justify-center">
        <FreshCollectiveLogo role="primary_light_logo" href="/" />
      </div>

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {stage === 'signed_out' && (
        <>
          <div className="mb-6 text-center">
            <h2 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Create your Fresh Collective account
            </h2>
            <p
              className="text-[14px] italic leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              A single account carries your membership, your Creator work,
              and everything you build.
            </p>
          </div>

          <form onSubmit={handleSignup} className="space-y-5">
            <div>
              <label
                htmlFor="name"
                className="mb-1.5 block text-sm font-medium text-navy-900"
              >
                Full name
              </label>
              <input
                id="name"
                name="name"
                type="text"
                autoComplete="name"
                required
                placeholder="Your name"
                className={FIELD_CLASS}
              />
            </div>

            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-sm font-medium text-navy-900"
              >
                Email address
              </label>
              <input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                placeholder="you@example.com"
                className={FIELD_CLASS}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm font-medium text-navy-900"
              >
                Password
              </label>
              <PasswordInput
                id="password"
                name="password"
                autoComplete="new-password"
                required
                placeholder="At least 8 characters"
                className={FIELD_CLASS}
              />
              <p className="mt-1.5 text-xs" style={{ color: '#718096' }}>
                Minimum 8 characters.
              </p>
            </div>

            <Button
              type="submit"
              variant="primary"
              size="md"
              className="w-full"
              disabled={busy}
            >
              {busy ? 'Creating your account…' : 'Create my account'}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm" style={{ color: '#5A6B7D' }}>
            Already have an account?{' '}
            <Link
              href="/login?next=%2Fsignup%2Fcreator%3Fplan%3Dcommunity"
              className="font-semibold text-teal-700 hover:underline"
            >
              Log in
            </Link>
          </p>
        </>
      )}

      {stage === 'unverified' && (
        <>
          <div className="mb-6 text-center">
            <h2 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Confirm your email address
            </h2>
            <p
              className="text-[14px] leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              Your account is created. We&rsquo;ve sent you a confirmation
              link — open it, then come back here to open your Community
              Collective.
            </p>
          </div>

          <Button
            type="button"
            variant="primary"
            size="md"
            className="w-full"
            disabled={busy}
            onClick={openCommunityPlan}
          >
            {busy ? 'Checking…' : 'I’ve confirmed — continue'}
          </Button>

          <p className="mt-5 text-center text-sm" style={{ color: '#5A6B7D' }}>
            {resent ? (
              <span>A new confirmation link is on its way.</span>
            ) : (
              <button
                type="button"
                onClick={resendVerification}
                disabled={busy}
                className="font-semibold text-teal-700 hover:underline disabled:opacity-60"
              >
                Send the confirmation link again
              </button>
            )}
          </p>
        </>
      )}

      {stage === 'ready' && (
        <>
          <div className="mb-6 text-center">
            <h2 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              Open your Community Collective
            </h2>
            <p
              className="text-[14px] leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              You&rsquo;re signed in and confirmed. This adds Creator
              capability to your account on the free Community plan, then
              walks you through building your first Collective.
            </p>
          </div>

          <Button
            type="button"
            variant="primary"
            size="md"
            className="w-full"
            disabled={busy}
            onClick={openCommunityPlan}
          >
            {busy ? 'Opening…' : 'Open my Community Collective'}
          </Button>
        </>
      )}

      {stage === 'already_creator' && (
        <>
          <div className="mb-6 text-center">
            <h2 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
              You already have Creator capability
            </h2>
            <p
              className="text-[14px] leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              Pick up where you left off — your Collectives and your plan
              live in Creator Studio.
            </p>
          </div>

          <Button
            type="button"
            variant="primary"
            size="md"
            className="w-full"
            disabled={busy}
            onClick={openCommunityPlan}
          >
            {busy ? 'Opening…' : 'Continue'}
          </Button>

          <p className="mt-5 text-center text-sm" style={{ color: '#5A6B7D' }}>
            <Link
              href="/creator-studio"
              className="font-semibold text-teal-700 hover:underline"
            >
              Go to Creator Studio
            </Link>
          </p>
        </>
      )}
    </div>
  )
}
