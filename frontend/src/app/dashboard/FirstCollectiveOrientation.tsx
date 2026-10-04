'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

/**
 * One-time orientation after a creator finishes their first Collective.
 *
 * Build Your Collective now hands off to Your World rather than straight
 * into Creator Studio, so a first-time Creator sees the member view
 * first — which is the point. The catch is that their new Collective
 * and the Creator Studio card both live in the "For creators" band, and
 * on a normal desktop viewport that band sits below the fold. Nothing
 * is missing; it just isn't visible yet.
 *
 * So this is a pointer, not a dashboard: one line saying where things
 * are, and a control that scrolls there. It deliberately does not
 * repeat the Collective card or the Creator Studio card at the top —
 * Your World is a member's home, and duplicating the creator surfaces
 * into it would make it a Creator dashboard.
 *
 * Shown only when ``?creator_onboarding=complete`` is present, and only
 * to a Creator. The query string is cleared as soon as it has been
 * consumed, so a reload or any later visit is the ordinary dashboard —
 * the prompt can never become permanent furniture. Nothing is
 * persisted: the handoff carries the state, so a creator who chose
 * "Begin in World Builders" instead simply never sees it.
 */
export default function FirstCollectiveOrientation({
  targetId,
}: {
  /** Element id of the existing "For creators" band to scroll to. */
  targetId: string
}) {
  const router = useRouter()
  const [dismissed, setDismissed] = useState(false)

  // Consume the param immediately so a refresh doesn't re-show this.
  // `scroll: false` keeps the reader where they are; replace() leaves
  // no history entry to go "back" into.
  useEffect(() => {
    router.replace('/dashboard', { scroll: false })
  }, [router])

  if (dismissed) return null

  function showMeWhere() {
    const target = document.getElementById(targetId)
    if (!target) return
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    // Leave the prompt in place during the scroll; it reads as the
    // thing that brought you here rather than vanishing mid-motion.
  }

  return (
    <div
      className="mb-8 rounded-2xl border p-5 md:p-6"
      style={{
        background: 'rgba(56,160,158,0.06)',
        borderColor: 'rgba(56,160,158,0.26)',
      }}
      role="status"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="font-serif text-[19px] leading-snug text-navy-900">
            Your Collective is ready <span aria-hidden="true">🌱</span>
          </p>
          <p
            className="mt-1.5 text-[14px] leading-relaxed"
            style={{ color: 'rgba(12,24,38,0.70)' }}
          >
            You&rsquo;ll find it below in your creator area, alongside
            World Builders. Head to Creator Studio when you&rsquo;re
            ready to keep building.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={showMeWhere}
            className="inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Show me where <span aria-hidden="true">↓</span>
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="text-[13px] font-medium text-slate-600 transition-colors hover:text-slate-900"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}
