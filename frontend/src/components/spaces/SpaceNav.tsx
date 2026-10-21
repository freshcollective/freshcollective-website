'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import CountBadge from '@/components/platform/CountBadge'

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
  /** Unseen Collective activity per category, from the Phase 2 count
   *  endpoint. Absent means "not supplied" and renders no badge, so a
   *  caller that has not threaded it keeps today's behaviour. */
  unseenByCategory?: Record<string, number>
  /** ``Space.show_member_directory``. When a Collective has closed its
   *  directory the Members tab is not offered, so the tab bar and the
   *  Collective Home agree about which doorways exist. Defaults to
   *  ``true`` so a caller that has not loaded the Space yet keeps the
   *  long-standing behaviour. */
  showMemberDirectory?: boolean
  /** Areas this viewer may reach, from ``SpaceResponse.area_access``.
   *  The server resolved it; the tab bar renders it and decides
   *  nothing of its own. Undefined means "not supplied" and keeps the
   *  previous behaviour for any caller that has not threaded it. */
  reachableAreas?: string[]
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
/** Tab label → the area whose policy governs it. */
const AREA_FOR_TAB: Record<string, string> = {
  Conversations: 'conversations',
  Pathways: 'pathways',
  Gatherings: 'gatherings',
  Members: 'members',
  About: 'about',
  Offerings: 'offerings',
}

export default function SpaceNav({
  spaceSlug, spaceName: _spaceName, isMember,
  unreadMessageCount = 0, showMemberDirectory = true, reachableAreas,
  unseenByCategory,
}: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`

  // Only the three member categories carry an activity badge.
  // Members and About never do, and Messages keeps its own.
  const unseenFor = (label: string): number => {
    const area = AREA_FOR_TAB[label]
    if (!area || !unseenByCategory) return 0
    return unseenByCategory[area] ?? 0
  }

  const tabs: Tab[] = [
    // About comes first on purpose. It is the doorway that reads for
    // everyone — a visitor who has not joined, and a member returning
    // to re-read what this Collective is for — and the Collective root
    // already sends signed-out visitors to ``/about``, so leading with
    // it makes the tab bar agree with where the Collective already
    // opens. Order here drives both the desktop tab bar and the mobile
    // bottom nav; there is one array so the two cannot disagree.
    { label: 'About',     href: `${base}/about`,    icon: '◇' },
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
    // Last, after the member destinations. An Offering is something you
    // take away rather than somewhere you go, and putting the shopfront
    // ahead of the Collective's own life would say the wrong thing
    // about what this platform is for.
    //
    // No flag check and no pilot check here. ``offerings`` is absent
    // from ``reachableAreas`` unless the feature is on AND this
    // Collective is in the Offerings pilot — the backend resolves both
    // in ``area_access.resolve_area_access`` — so the filter below
    // hides the tab for the same reason it hides any area this viewer
    // cannot reach. The tab bar does not need to know either switch
    // exists, which is why rolling the pilot out needed no frontend
    // change at all.
    { label: 'Offerings',  href: `${base}/offerings`, icon: '◆' },
  ]
    .filter((tab) => tab.label !== 'Members' || showMemberDirectory)
    // Area policy decides which doorways exist for this viewer. The
    // server already answered; hiding a tab whose route would 404 is
    // the whole point, and computing it again here is how the tab bar
    // and the Home came to disagree about Members.
    .filter((tab) => reachableAreas === undefined
      || reachableAreas.includes(AREA_FOR_TAB[tab.label] ?? ''))

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
                    'relative inline-flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
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
                  <CountBadge
                    count={unseenFor(tab.label)}
                    label={`in ${tab.label}`}
                  />
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
                <CountBadge count={unreadMessageCount} label="in Messages" />
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
                className="relative flex min-w-[76px] shrink-0 flex-col items-center gap-0.5 py-2.5 text-center transition-colors"
                style={active ? { color: 'var(--fc-accent, #0f766e)' } : { color: '#000' }}
              >
                <span className="relative text-base leading-none">
                  <span aria-hidden="true">{tab.icon}</span>
                  <CountBadge
                    count={unseenFor(tab.label)}
                    variant="corner"
                    label={`in ${tab.label}`}
                  />
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
                <CountBadge
                  count={unreadMessageCount}
                  variant="corner"
                  label="in Messages"
                />
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
