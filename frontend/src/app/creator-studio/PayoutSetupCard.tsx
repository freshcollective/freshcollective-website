import Link from 'next/link'

import type { PayoutSetupCardView } from '@/lib/payoutSetupCard'

/**
 * The payout-setup orientation card on Creator Studio home.
 *
 * Deliberately quiet. This is preparation, not a problem: the creator
 * can sell today and is paid today, and the card exists only because
 * the setup was too easy to miss in Billing. So it is a soft panel
 * rather than a banner, it never uses error red unless Stripe has
 * genuinely stopped something, and it sits below the hero rather than
 * above it — the first thing in Creator Studio should still be their
 * own work.
 *
 * One card, once. There are no payout warnings on any other Studio
 * screen; the rest of the story lives in Billing, which this links to.
 */

const TONE: Record<
  PayoutSetupCardView['tone'],
  { border: string; background: string; accent: string }
> = {
  // Warm stone — reads as guidance.
  neutral: {
    border: 'rgba(12,24,38,0.10)',
    background: '#FBFAF6',
    accent: '#1E6E6C',
  },
  // Teal tint — something is underway.
  progress: {
    border: 'rgba(56,160,158,0.28)',
    background: 'rgba(56,160,158,0.06)',
    accent: '#1E6E6C',
  },
  // Amber, not red. Stripe wants something; nothing is broken.
  attention: {
    border: 'rgba(180,120,36,0.30)',
    background: 'rgba(214,158,46,0.08)',
    accent: '#8A5A10',
  },
  // The only state where something genuinely cannot proceed.
  stopped: {
    border: 'rgba(180,72,60,0.28)',
    background: 'rgba(180,72,60,0.06)',
    accent: '#A3433A',
  },
}

export default function PayoutSetupCard({ view }: { view: PayoutSetupCardView }) {
  const tone = TONE[view.tone]

  return (
    <section
      aria-labelledby="payout-setup-heading"
      className="mb-10 rounded-2xl p-6 md:p-7"
      style={{ background: tone.background, border: `1px solid ${tone.border}` }}
    >
      <h2
        id="payout-setup-heading"
        className="font-[var(--fc-font-serif)] text-[18px] leading-[var(--fc-lh-heading)]"
        style={{ color: '#0C1826' }}
      >
        {view.heading}
      </h2>

      <p
        className="mt-2 max-w-[62ch] text-[length:var(--fc-fs-body)] leading-[var(--fc-lh-body)]"
        style={{ color: 'rgba(12, 24, 38, 0.74)' }}
      >
        {view.body}
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-4">
        {view.ctaLabel && (
          <Link
            href={view.href}
            className="inline-flex items-center rounded-full px-5 py-2.5 text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] text-white transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {view.ctaLabel}
          </Link>
        )}
        {/* Always a way through to the detail, even in the states that
            offer no action — those are the ones a creator most needs to
            read about. */}
        <Link
          href={view.href}
          className="rounded text-[length:var(--fc-fs-body)] font-[var(--fc-fw-semibold)] transition-opacity hover:opacity-70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2"
          style={{ color: tone.accent }}
        >
          {view.ctaLabel ? 'See payout details' : 'See payout details →'}
        </Link>
      </div>

      {view.note && (
        <p
          className="mt-4 text-[length:var(--fc-fs-meta)] leading-[var(--fc-lh-meta)]"
          style={{ color: 'rgba(12, 24, 38, 0.56)' }}
        >
          {view.note}
        </p>
      )}
    </section>
  )
}
