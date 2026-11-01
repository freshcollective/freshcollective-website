'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'

import { type ReportingHealth, describeHealth, fetchHealth } from '@/lib/insights'
import {
  HUE_UI,
  INK as FC_INK,
  SURFACE,
  toneStyle,
} from '@/lib/insights-palette'

// Clean white behind the reporting content. Sections separate by
// spacing and a hairline rather than by sitting on a grey wash — the
// design language permits exactly one grey and it is for disabled ink.
const PAGE_BG = SURFACE.page
const INK = FC_INK.heading
const INK_MUTED = FC_INK.muted
const INK_SOFTER = FC_INK.faint
const HAIRLINE = '1px solid rgba(12, 24, 38, 0.08)'

/**
 * The eight places to look, and one honest statement about the data.
 *
 * World Insights is where Fresh Collective gets understood as a
 * business; Mother World stays the welcoming overview and World History
 * stays the audit trail. Keeping those three separate is deliberate —
 * each answers a different question, and a page that tried to answer all
 * three would answer none of them well.
 *
 * The data-health indicator lives in the header rather than a footer
 * link, because the moment to learn that last night's rebuild failed is
 * *before* reading the figures, not after.
 */
const TABS: { href: string; label: string; blurb: string }[] = [
  // First, and where the area opens. A starting point for the seven
  // that follow rather than an eighth collection of every metric.
  { href: '/admin/insights/overview', label: 'Overview', blurb: 'How Fresh Collective is doing' },
  { href: '/admin/insights/growth', label: 'Growth', blurb: 'Who is arriving, and how fast' },
  { href: '/admin/insights/belonging', label: 'Belonging', blurb: 'Who stays, and who comes back' },
  { href: '/admin/insights/collectives', label: 'Collectives', blurb: 'How each community is faring' },
  { href: '/admin/insights/creators', label: 'Creators', blurb: 'How creators are getting on' },
  { href: '/admin/insights/participation', label: 'Participation', blurb: 'What people are actually doing' },
  { href: '/admin/insights/money', label: 'Money', blurb: 'What comes in, and whose it is' },
  // Last, and deliberately not folded into Creators. World Builders is
  // classified internal_operations and stays excluded from every
  // Production figure on the other six — which is why it needs a tab
  // of its own rather than a share of theirs.
  { href: '/admin/insights/world-builders', label: 'World Builders', blurb: 'Where creators learn to build' },
]

export function InsightsShell({
  title,
  intro,
  children,
}: {
  title: string
  intro: string
  children: React.ReactNode
}) {
  const pathname = usePathname()

  return (
    // ``min-w-0`` is load-bearing, not tidiness. The application
    // ``body`` is a flex container, so every child of it defaults to
    // ``min-width: auto`` and refuses to shrink below its content's
    // min-content width. One table with a min-width inside a card
    // inside this shell therefore widened the whole page and made the
    // body scroll sideways, instead of scrolling inside its own
    // container. Allowing the shell to shrink is what keeps wide
    // content's overflow local to the element that owns it.
    <div className="min-h-full min-w-0" style={{ background: PAGE_BG }}>
      <div className="mx-auto max-w-[1180px] px-5 py-8 md:px-8">
        <header className="mb-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1
                className="font-serif text-[30px] leading-tight md:text-[34px]"
                style={{ color: INK }}
              >
                World Insights
              </h1>
              <p
                className="mt-1.5 max-w-[62ch] text-[14px]"
                style={{
                  color: INK_MUTED,
                  fontFamily: 'Georgia, serif',
                  fontStyle: 'italic',
                }}
              >
                Understanding how Fresh Collective is growing, connecting and
                thriving.
              </p>
            </div>
            <DataHealthIndicator />
          </div>

          <nav
            aria-label="World Insights sections"
            className="mt-5 flex flex-wrap gap-1.5"
          >
            {TABS.map(({ href, label, blurb }) => {
              const active = pathname === href
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? 'page' : undefined}
                  title={blurb}
                  className="rounded-lg px-3.5 py-2 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
                  style={
                    active
                      ? {
                          background: HUE_UI.teal.bg,
                          border: `1px solid ${HUE_UI.teal.border}`,
                          color: HUE_UI.teal.text,
                          fontWeight: 600,
                        }
                      : {
                          background: '#FFFFFF',
                          border: `1px solid ${SURFACE.cardEdge}`,
                          color: INK_MUTED,
                        }
                  }
                >
                  {label}
                </Link>
              )
            })}
          </nav>
        </header>

        <section>
          <h2
            className="font-serif text-[22px] leading-tight"
            style={{ color: INK }}
          >
            {title}
          </h2>
          <p className="mt-1 max-w-[70ch] text-[13.5px]" style={{ color: INK_MUTED }}>
            {intro}
          </p>
          <div className="mt-5">{children}</div>
        </section>
      </div>
    </div>
  )
}

/**
 * A standing statement about whether the figures can be trusted.
 *
 * Deliberately not only a tick. The states that matter are the awkward
 * ones: recording switched off, a rebuild that failed, a run that never
 * finished. A green light that cannot go amber trains somebody to stop
 * looking at it.
 *
 * "No activity yet" is never reported as a problem — a quiet week on a
 * small platform is normal, and calling it a failure would be the same
 * mistake in the other direction.
 */
export function DataHealthIndicator() {
  const [health, setHealth] = useState<ReportingHealth | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then(setHealth)
      .catch(() => setFailed(true))
    return () => controller.abort()
  }, [])

  const state = describeHealth(health, failed)

  return (
    <Link
      href="/admin/insights/data-health"
      className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[12.5px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#246B6A]"
      style={{
        background: toneStyle(state.hue).bg,
        border: `1px solid ${toneStyle(state.hue).border}`,
        color: toneStyle(state.hue).text,
      }}
    >
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: toneStyle(state.hue).dot }}
      />
      <span>{state.label}</span>
    </Link>
  )
}


export { HAIRLINE, INK, INK_MUTED, INK_SOFTER, PAGE_BG }
