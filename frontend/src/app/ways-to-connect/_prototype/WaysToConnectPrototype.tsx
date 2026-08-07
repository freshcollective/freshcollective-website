/**
 * Ways to Connect — honest empty state.
 *
 * The design prototype's fake introduction cards (and its session-scoped
 * accept / decline / message plumbing) have been removed. Real
 * introductions will appear here only when the recommendation service
 * genuinely has something to surface. Until then this page tells the
 * truth: nothing shown yet, and here's how it will start.
 *
 * The `_prototype` folder is preserved so the ../page.tsx import path
 * stays stable while the real Ways to Connect surface takes shape.
 * When the recommendation service ships, replace this component (and
 * consider promoting it out of `_prototype/`).
 */

import Link from 'next/link'

export default function WaysToConnectPrototype() {
  return (
    <section className="mx-auto max-w-[720px] px-6 pb-24 pt-4 md:px-8 md:pt-6">
      <div
        className="rounded-3xl bg-white px-8 py-12 text-center md:px-12 md:py-16"
        style={{
          border: '1px solid rgba(12, 24, 38, 0.06)',
          boxShadow: '0 14px 40px rgba(12, 24, 38, 0.06), 0 2px 8px rgba(12, 24, 38, 0.03)',
        }}
      >
        <div className="mx-auto mb-8 flex h-14 w-14 items-center justify-center">
          <svg viewBox="0 0 40 40" width="52" height="52" aria-hidden="true">
            <circle
              cx="15"
              cy="17"
              r="9"
              stroke="#38A09E"
              strokeWidth="1.5"
              fill="none"
              opacity="0.7"
            />
            <circle
              cx="25"
              cy="23"
              r="9"
              stroke="#D4B048"
              strokeWidth="1.5"
              fill="none"
              opacity="0.85"
            />
          </svg>
        </div>

        <h2
          className="font-serif text-[22px] leading-tight md:text-[26px]"
          style={{ color: '#0C1826', letterSpacing: '-0.005em' }}
        >
          Introductions grow from shared experiences.
        </h2>

        <p
          className="mx-auto mt-5 max-w-[520px] text-[15px] leading-[1.75]"
          style={{ color: 'rgba(12, 24, 38, 0.78)', fontFamily: 'Georgia, serif' }}
        >
          As you join collectives, attend gatherings and participate in
          conversations, we&rsquo;ll introduce you to people whose paths
          naturally cross yours.
        </p>

        <p
          className="mx-auto mt-4 max-w-[520px] text-[13.5px] italic leading-[1.7]"
          style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
        >
          Your introductions will appear here as your journey unfolds.
        </p>

        <div className="mt-10">
          <Link
            href="/spaces"
            className="inline-flex items-center rounded-full px-7 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{
              background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
              letterSpacing: '0.06em',
            }}
          >
            Explore Collectives →
          </Link>
        </div>
      </div>
    </section>
  )
}
