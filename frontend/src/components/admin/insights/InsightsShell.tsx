'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'

import { type ReportingHealth, describeHealth, fetchHealth } from '@/lib/insights'
import { WM_HUE } from '@/lib/wm-palette'

const PAGE_BG = '#FBFDFC'
const INK = '#0C1826'
const INK_MUTED = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE = '1px solid rgba(12, 24, 38, 0.08)'

/**
 * The six places to look, and one honest statement about the data.
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
  { href: '/admin/insights/growth', label: 'Growth', blurb: 'Who is arriving, and how fast' },
  { href: '/admin/insights/belonging', label: 'Belonging', blurb: 'Who stays, and who comes back' },
  { href: '/admin/insights/collectives', label: 'Collectives', blurb: 'How each community is faring' },
  { href: '/admin/insights/creators', label: 'Creators', blurb: 'How creators are getting on' },
  { href: '/admin/insights/participation', label: 'Participation', blurb: 'What people are actually doing' },
  { href: '/admin/insights/money', label: 'Money', blurb: 'What comes in, and whose it is' },
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
    <div className="min-h-full" style={{ background: PAGE_BG }}>
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
                          background: WM_HUE.teal.bg,
                          border: `1px solid ${WM_HUE.teal.border}`,
                          color: WM_HUE.teal.text,
                          fontWeight: 600,
                        }
                      : {
                          background: '#FFFFFF',
                          border: '1px solid #E7EEF0',
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
        background: WM_HUE[state.hue].bg,
        border: `1px solid ${WM_HUE[state.hue].border}`,
        color: WM_HUE[state.hue].text,
      }}
    >
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: WM_HUE[state.hue].dot }}
      />
      <span>{state.label}</span>
    </Link>
  )
}


export { HAIRLINE, INK, INK_MUTED, INK_SOFTER, PAGE_BG }
