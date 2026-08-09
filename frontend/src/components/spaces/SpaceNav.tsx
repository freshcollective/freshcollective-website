'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

interface Tab {
  label: string
  href: string
  icon: string
  alsoActiveOn?: RegExp
}

interface SpaceNavProps {
  spaceSlug: string
  spaceName: string
  isMember: boolean
  unreadMessageCount?: number
}

/**
 * The collective's tab bar (desktop) + bottom nav (mobile).
 *
 * The old "Stay Connected" button that lived here opened an in-page
 * modal editing per-collective notification preferences. Those
 * preferences now live at ``/settings/stay-connected`` — a global
 * page listing every collective the member belongs to — so this
 * component no longer needs any modal state or launcher.
 */
export default function SpaceNav({ spaceSlug, spaceName: _spaceName, isMember, unreadMessageCount = 0 }: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`

  const tabs: Tab[] = [
    {
      // Language shift: "Community" is being retired as a visible feature
      // label in favour of "Conversations", which pluralises naturally when
      // Channels arrive. Route path stays `/community` for compatibility.
      label: 'Conversations',
      href: `${base}/community`,
      icon: '◈',
    },
    { label: 'Pathways',  href: `${base}/pathways`, icon: '◎' },
    { label: 'Gatherings', href: `${base}/events`,    icon: '◷' },
    { label: 'Members',    href: `${base}/members`,   icon: '◉' },
    { label: 'About',     href: `${base}/about`,    icon: '◇' },
  ]

  function isActive(tab: Tab): boolean {
    if (tab.alsoActiveOn?.test(pathname)) return true
    return pathname.startsWith(tab.href)
  }

  return (
    <>
      {/* ── Desktop: horizontal tab bar ── */}
      <div className="hidden border-b border-border bg-surface md:block">
        <div className="mx-auto max-w-6xl px-10">
          <nav className="flex gap-0">
            {tabs.map((tab) => {
              const active = isActive(tab)
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={[
                    'inline-block shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                    active
                      ? 'font-semibold'
                      : 'border-transparent text-black hover:text-navy-700',
                  ].join(' ')}
                  style={active ? {
                    borderColor: 'var(--fc-accent, #38A09E)',
                    color: 'var(--fc-accent, #0f766e)',
                  } : undefined}
                >
                  {tab.label}
                </Link>
              )
            })}

            {isMember && (
              <Link
                href={`/spaces/${spaceSlug}/messages`}
                className={[
                  'relative inline-flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                  pathname.startsWith(`/spaces/${spaceSlug}/messages`)
                    ? 'font-semibold'
                    : 'border-transparent text-black hover:text-navy-700',
                ].join(' ')}
                style={pathname.startsWith(`/spaces/${spaceSlug}/messages`) ? {
                  borderColor: 'var(--fc-accent, #38A09E)',
                  color: 'var(--fc-accent, #0f766e)',
                } : undefined}
              >
                Messages
                {unreadMessageCount > 0 && (
                  <span className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-white"
                    style={{ background: 'var(--fc-accent, #38A09E)' }}>
                    {unreadMessageCount > 9 ? '9+' : unreadMessageCount}
                  </span>
                )}
              </Link>
            )}
          </nav>
        </div>
      </div>

      {/* ── Mobile: fixed bottom nav ── */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface md:hidden">
        <div className="flex overflow-x-auto overscroll-x-contain">
          {tabs.map((tab) => {
            const active = isActive(tab)
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className="flex min-w-[76px] shrink-0 flex-col items-center gap-0.5 py-2.5 text-center transition-colors"
                style={active ? { color: 'var(--fc-accent, #0f766e)' } : { color: '#000' }}
              >
                <span className="text-base leading-none" aria-hidden="true">
                  {tab.icon}
                </span>
                <span className="whitespace-nowrap text-xs font-medium">{tab.label}</span>
              </Link>
            )
          })}

          {isMember && (
            <Link
              href={`/spaces/${spaceSlug}/messages`}
              className="relative flex min-w-[76px] shrink-0 flex-col items-center gap-0.5 py-2.5 text-center transition-colors"
              style={pathname.startsWith(`/spaces/${spaceSlug}/messages`)
                ? { color: 'var(--fc-accent, #0f766e)' }
                : { color: '#000' }}
            >
              <span className="relative text-base leading-none" aria-hidden="true">
                ✉
                {unreadMessageCount > 0 && (
                  <span className="absolute -right-1.5 -top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px] font-bold text-white"
                    style={{ background: 'var(--fc-accent, #38A09E)' }}>
                    {unreadMessageCount > 9 ? '9' : unreadMessageCount}
                  </span>
                )}
              </span>
              <span className="whitespace-nowrap text-xs font-medium">Messages</span>
            </Link>
          )}
        </div>
        <div style={{ height: 'env(safe-area-inset-bottom)' }} className="bg-surface" />
      </nav>
    </>
  )
}
