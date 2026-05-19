'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

interface Tab {
  label: string
  href: string
  exact?: boolean
  icon: string
}

interface SpaceNavProps {
  spaceSlug: string
}

export default function SpaceNav({ spaceSlug }: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`

  const tabs: Tab[] = [
    { label: 'Home',      href: base,                  exact: true, icon: '⌂' },
    { label: 'Pathways',  href: `${base}/pathways`,                 icon: '◎' },
    { label: 'Community', href: `${base}/community`,                icon: '◈' },
    { label: 'Events',    href: `${base}/events`,                   icon: '◷' },
    { label: 'Members',   href: `${base}/members`,                  icon: '◉' },
  ]

  function isActive(tab: Tab): boolean {
    if (tab.exact) return pathname === tab.href
    return pathname.startsWith(tab.href)
  }

  // Detect whether the user is inside a specific pathway (not just the pathway list).
  // Matches /spaces/[slug]/pathways/[pathwaySlug] and any sub-routes.
  const pathwayMatch = pathname.match(
    new RegExp(`^/spaces/${spaceSlug}/pathways/([^/]+)(/.*)?$`),
  )
  const pathwaySlug = pathwayMatch?.[1] ?? null

  const aboutHref    = pathwaySlug ? `${base}/pathways/${pathwaySlug}/about` : null
  const overviewHref = pathwaySlug ? `${base}/pathways/${pathwaySlug}`       : null

  const isAboutTabActive    = !!aboutHref    && pathname === aboutHref
  // "Pathway" tab is active on the overview AND any step page, but not the About page
  const isPathwayTabActive  = !!overviewHref && pathname.startsWith(overviewHref) && pathname !== aboutHref

  // On mobile, switch from flex-1 (fill width) to fixed min-width when pathway
  // tabs are present so the row can scroll horizontally.
  const mobileTabClass = (active: boolean) =>
    [
      'flex flex-col items-center gap-0.5 py-2.5 text-center transition-colors shrink-0',
      pathwaySlug ? 'min-w-[62px]' : 'flex-1',
      active ? 'text-teal-600' : 'text-slate-400',
    ].join(' ')

  return (
    <>
      {/* ── Desktop: horizontal tab bar ── */}
      <div className="hidden border-b border-border bg-surface md:block">
        <div className="mx-auto max-w-6xl px-10">
          <nav className="flex gap-0">
            {/* Collective-level tabs */}
            {tabs.map((tab) => (
              <Link
                key={tab.href}
                href={tab.href}
                className={[
                  'inline-block shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                  isActive(tab)
                    ? 'border-teal-500 font-semibold text-teal-700'
                    : 'border-transparent text-slate-500 hover:text-navy-700',
                ].join(' ')}
              >
                {tab.label}
              </Link>
            ))}

            {/* Pathway-level tabs — only visible when inside a specific pathway */}
            {pathwaySlug && aboutHref && overviewHref && (
              <>
                {/* Thin visual divider between collective and pathway tabs */}
                <div className="mx-3 self-center h-4 w-px bg-slate-200" aria-hidden="true" />

                <Link
                  href={aboutHref}
                  className={[
                    'inline-block shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                    isAboutTabActive
                      ? 'border-teal-500 font-semibold text-teal-700'
                      : 'border-transparent text-slate-500 hover:text-navy-700',
                  ].join(' ')}
                >
                  About
                </Link>

                <Link
                  href={overviewHref}
                  className={[
                    'inline-block shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                    isPathwayTabActive
                      ? 'border-teal-500 font-semibold text-teal-700'
                      : 'border-transparent text-slate-500 hover:text-navy-700',
                  ].join(' ')}
                >
                  Pathway
                </Link>
              </>
            )}
          </nav>
        </div>
      </div>

      {/* ── Mobile: fixed bottom nav ── */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface md:hidden">
        {/* overflow-x-auto lets the row scroll when pathway tabs are added */}
        <div className="flex overflow-x-auto">
          {tabs.map((tab) => {
            const active = isActive(tab)
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={mobileTabClass(active)}
              >
                <span className="text-base leading-none" aria-hidden="true">
                  {tab.icon}
                </span>
                <span className="text-[10px] font-medium">
                  {tab.label}
                </span>
              </Link>
            )
          })}

          {/* Pathway-level tabs on mobile */}
          {pathwaySlug && aboutHref && overviewHref && (
            <>
              <Link
                href={aboutHref}
                className={mobileTabClass(isAboutTabActive)}
              >
                <span className="text-base leading-none" aria-hidden="true">◇</span>
                <span className="text-[10px] font-medium">About</span>
              </Link>

              <Link
                href={overviewHref}
                className={mobileTabClass(isPathwayTabActive)}
              >
                <span className="text-base leading-none" aria-hidden="true">▷</span>
                <span className="text-[10px] font-medium">Pathway</span>
              </Link>
            </>
          )}
        </div>
        {/* Safe area spacer for notched phones */}
        <div style={{ height: 'env(safe-area-inset-bottom)' }} className="bg-surface" />
      </nav>
    </>
  )
}
