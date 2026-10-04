'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'

/**
 * What Ways to Connect looks like to somebody who has not joined in.
 *
 * Deliberately **not** the empty state. Those two pages mean opposite
 * things and used to look identical: "we have not found anyone yet"
 * invites you to wait, while this one is waiting on you. Showing the
 * first to an opted-out member is a quiet lie, and hiding the feature
 * from them instead is worse — they would have no way back to it.
 *
 * So the nav entry, the Your World doorway and this route all stay
 * visible regardless of participation. The launch flag decides whether
 * the product exists; this setting decides whether one person takes
 * part. Keeping those separate is what gives somebody a route back in.
 *
 * The copy says what switching it on does and what it does not do. It
 * does not describe the eligibility rules — two signals, one realised,
 * five categories — because that is a derivation a member never asked
 * about and could not act on. "A Gathering you both attended, a Pathway
 * you are both walking" is the true shape of it at the level that
 * matters, and the thing people most want to know about a feature like
 * this is what it will not reveal.
 */

export default function WaysToConnectOptIn() {
  const router = useRouter()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [, startTransition] = useTransition()

  async function turnOn() {
    setSaving(true)
    setError(null)
    try {
      // The same endpoint Account Settings uses. One write path for one
      // setting — a second one here would be a second place for the
      // semantics to drift.
      const res = await fetch(apiUrl('/api/auth/me'), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ways_to_connect_enabled: true }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(
          typeof data.detail === 'string'
            ? data.detail
            : 'That didn’t save. Please try again.',
        )
        return
      }
      // Re-read rather than switching the view locally: what appears
      // next is computed server-side from what this member genuinely
      // shares, and it may well be the empty state.
      startTransition(() => router.refresh())
    } catch {
      setError('Network error. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="mx-auto max-w-[620px] px-6 pb-24 pt-2 md:px-8">
      <div
        className="rounded-2xl bg-white p-7 md:p-9"
        style={{ border: '1px solid rgba(12,24,38,0.08)' }}
      >
        <h2
          className="font-[var(--fc-font-serif)] text-[20px] leading-[var(--fc-lh-heading)]"
          style={{ color: '#0C1826' }}
        >
          Ways to Connect is currently turned off.
        </h2>

        <p
          className="mt-3 font-[var(--fc-font-serif)] text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)]"
          style={{ color: 'rgba(12, 24, 38, 0.78)' }}
        >
          Turn it on when you’re ready to discover people you’ve
          genuinely crossed paths with through Fresh Collective.
        </p>

        <div
          className="mt-6 rounded-xl p-5"
          style={{ background: '#FAFAF8', border: '1px solid rgba(12,24,38,0.07)' }}
        >
          <p
            className="text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)]"
            style={{ color: 'rgba(12, 24, 38, 0.78)' }}
          >
            When Ways to Connect is on, Fresh Collective may introduce
            you to people you’ve shared meaningful experiences with —
            such as a Gathering you both attended, or a Pathway you’re
            both exploring. Simply being in the same Collective is never
            enough on its own.
          </p>
          <p
            className="mt-3 text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)]"
            style={{ color: 'rgba(12, 24, 38, 0.78)' }}
          >
            We never reveal your email address, phone number or any other
            private contact details. Nobody can message you until you
            have both said hello, and you can turn this off again at any
            time.
          </p>
        </div>

        {error && (
          <p
            className="mt-4 text-[length:var(--fc-fs-meta)] leading-[var(--fc-lh-meta)]"
            style={{ color: '#B4483C' }}
          >
            {error}
          </p>
        )}

        <div className="mt-7 flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={turnOn}
            disabled={saving}
            className="rounded-full px-5 py-2.5 text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Turning on…' : 'Turn on Ways to Connect'}
          </button>
          {/* Settings remains the home of the setting; this is a
              pointer to it, not a second way to change it. No invented
              "Learn more" destination — there is no privacy surface
              that covers this, and a link to one that does not exist
              would be worse than the paragraphs above. */}
          <Link
            href="/settings/profile"
            className="rounded text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
            style={{ color: '#2F8F8D' }}
          >
            Manage in Settings
          </Link>
        </div>
      </div>
    </section>
  )
}
