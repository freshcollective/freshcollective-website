'use client'

import { useState, useTransition } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'
import CreatorStudioLiteMobile from './CreatorStudioLiteMobile'
import type { LiteData } from './CreatorStudioLiteMobile'
import type { SpaceSummary } from '@/types/platform'

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

const EMPTY_LITE_DATA: LiteData = {
  pathwayCounts: { published: 0, comingSoon: 0, drafts: 0, archived: 0 },
  publishedPathways: [],
  allPathways: [],
  upcomingGatherings: [],
  memberCount: 0,
  leaderCount: 0,
  members: [],
  invitations: [],
  accessRequests: [],
  pendingInvites: 0,
  pendingRequests: 0,
  resourceCount: 0,
  billing: null,
}

interface Props {
  children: React.ReactNode
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  liteData?: LiteData
}

interface NavItem {
  href: string
  label: string
  exact?: boolean
  activeOnPath?: RegExp
}

const NAV_SECTIONS: { label: string; items: NavItem[] }[] = [
  {
    label: 'ACCOUNT',
    items: [
      { href: '/creator-studio',         label: 'Studio Home', exact: true },
      { href: '/creator-studio/billing',  label: 'Billing' },
      { href: '/creator-studio/payments', label: 'Payments' },
    ],
  },
  {
    label: 'CURRENT COLLECTIVE',
    items: [
      { href: '/creator-studio/pathways',   label: 'Pathways',      activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/ },
      { href: '/creator-studio/gatherings', label: 'Gatherings',    activeOnPath: /^\/creator\/spaces\/[^/]+\/events/ },
      { href: '/creator-studio/resources',  label: 'Resources' },
      { href: '/creator-studio/media',      label: 'Brand Library' },
      { href: '/creator-studio/community',  label: 'Community',     activeOnPath: /^\/creator\/spaces\/[^/]+\/community/ },
      { href: '/creator-studio/people',     label: 'People' },
      { href: '/creator-studio/passes',     label: 'Member Passes' },
      { href: '/creator-studio/setup',      label: 'Setup' },
      { href: '/creator-studio/settings',   label: 'Settings',      activeOnPath: /^\/creator\/spaces\/[^/]+$/ },
    ],
  },
]

// ---------------------------------------------------------------------------
// Collective switcher
// ---------------------------------------------------------------------------

function CollectiveSwitcher({
  spaces,
  activeSpace,
  collectiveLimit,
}: {
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
}) {
  const router = useRouter()
  const [selectedSlug, setSelectedSlug] = useState<string | null>(activeSpace?.slug ?? null)
  const [isPending, startTransition] = useTransition()

  const activeSpaceCount = spaces.filter((s) => s.status !== 'archived').length
  const atLimit = activeSpaceCount >= collectiveLimit

  function switchTo(slug: string) {
    if (slug === selectedSlug) return
    setSelectedSlug(slug)
    startTransition(() => {
      document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`
      router.push('/creator-studio')
    })
  }

  return (
    <div className="mt-4">
      {spaces.length > 0 && (
        <div
          className="rounded-2xl p-3"
          style={{
            background: 'rgba(255,255,255,0.96)',
            border: '1px solid rgba(56,160,158,0.28)',
          }}
        >
          <p
            className="mb-2.5 px-1 text-[11px] font-bold uppercase tracking-[0.18em]"
            style={{ color: '#38A09E' }}
          >
            Current collective
          </p>
          <div className="space-y-1.5">
            {spaces.map((s) => {
              const isCurrent = s.slug === selectedSlug
              const isPendingThis = isPending && s.slug === selectedSlug
              return (
                <button
                  key={s.slug}
                  type="button"
                  onClick={() => switchTo(s.slug)}
                  disabled={isPending}
                  className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left outline-none transition-colors"
                  style={{
                    background: isCurrent ? 'rgba(56,160,158,0.10)' : 'transparent',
                    border: isCurrent
                      ? '1px solid rgba(56,160,158,0.28)'
                      : '1px solid transparent',
                    opacity: isPendingThis ? 0.75 : 1,
                  }}
                  onMouseEnter={(e) => {
                    if (!isCurrent && !isPending)
                      (e.currentTarget as HTMLButtonElement).style.background = 'rgba(56,160,158,0.06)'
                  }}
                  onMouseLeave={(e) => {
                    if (!isCurrent)
                      (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  }}
                >
                  <span
                    className="w-full truncate text-[13px] font-semibold leading-snug"
                    style={{ color: isCurrent ? '#0C1826' : '#334155' }}
                  >
                    {s.name}
                  </span>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <span
                      className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                      style={{
                        background: s.status === 'active' ? 'rgba(56,160,158,0.14)' : 'rgba(0,0,0,0.07)',
                        color: s.status === 'active' ? '#38A09E' : '#94a3b8',
                      }}
                    >
                      {s.status === 'active' ? 'Active' : 'Draft'}
                    </span>
                    {isCurrent && (
                      <span
                        className="rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide"
                        style={{
                          background: 'rgba(56,160,158,0.12)',
                          border: '1px solid rgba(56,160,158,0.35)',
                          color: '#38A09E',
                        }}
                      >
                        {isPendingThis ? 'Switching…' : 'Current'}
                      </span>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="mt-2.5 px-1">
        {!atLimit ? (
          <Link
            href="/creator-studio/create-collective"
            className="flex items-center gap-1.5 text-[12px] font-medium transition-opacity hover:opacity-80"
            style={{ color: '#8DE8E6' }}
          >
            <span aria-hidden="true" className="text-[14px] leading-none">+</span>
            Create new collective
          </Link>
        ) : (
          <div>
            <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
              {activeSpaceCount} of {collectiveLimit} collectives used
            </p>
            <Link
              href="/creator-studio/billing"
              className="mt-0.5 block text-[11px] transition-opacity hover:opacity-80"
              style={{ color: 'rgba(141,232,230,0.70)' }}
            >
              View plan →
            </Link>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar inner
// ---------------------------------------------------------------------------

function SidebarInner({
  user,
  spaces,
  activeSpace,
  collectiveLimit,
  pathname,
  onNavClick,
}: {
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  pathname: string
  onNavClick?: () => void
}) {
  function isActive(href: string, exact?: boolean, activeOnPath?: RegExp) {
    if (exact) return pathname === href
    if (pathname.startsWith(href)) return true
    if (activeOnPath && activeOnPath.test(pathname)) return true
    return false
  }

  const hasCollective = !!activeSpace

  return (
    <div
      className="relative flex h-full flex-col overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, #073B3A 0%, #062F35 45%, #051C27 100%)',
      }}
    >
      <div
        className="pointer-events-none absolute inset-0 z-0"
        aria-hidden="true"
        style={{
          background: 'radial-gradient(circle at 20% 0%, rgba(66,199,198,0.20), transparent 32%)',
        }}
      />

      {/* Logo */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link href="/creator-studio" className="flex flex-col gap-1" onClick={onNavClick}>
          <span className="font-serif text-[18px] leading-tight" style={{ color: '#FFFFFF' }}>
            Creator Studio
          </span>
          <span
            className="text-[11px] font-bold uppercase tracking-[0.18em]"
            style={{ color: 'rgba(255,255,255,0.42)' }}
          >
            Fresh Collective
          </span>
        </Link>
        <CollectiveSwitcher spaces={spaces} activeSpace={activeSpace} collectiveLimit={collectiveLimit} />
      </div>

      {/* Nav */}
      <nav className="relative z-10 flex-1 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map(({ label, items }) => (
          <div key={label} className="mb-5">
            <p
              className="mb-1.5 px-4 text-[11px] font-bold uppercase tracking-[0.18em]"
              style={{ color: 'rgba(255,255,255,0.35)' }}
            >
              {label}
            </p>
            <ul className="space-y-0.5">
              {items.map(({ href, label: itemLabel, exact, activeOnPath }) => {
                const active = isActive(href, exact, activeOnPath)
                const dimmed = label === 'CURRENT COLLECTIVE' && !hasCollective
                return (
                  <li key={href}>
                    <Link
                      href={dimmed ? '/creator-studio/create' : href}
                      onClick={onNavClick}
                      className={`flex items-center rounded-xl px-4 py-2.5 text-[15px] font-medium transition-all ${
                        active
                          ? 'bg-white/[12%] text-white'
                          : dimmed
                            ? 'cursor-default text-white/[35%]'
                            : 'text-white/[72%] hover:bg-white/[8%] hover:text-white'
                      }`}
                      tabIndex={dimmed ? -1 : undefined}
                      aria-disabled={dimmed}
                    >
                      {itemLabel}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div
        className="relative z-10 px-5 py-5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.09)' }}
      >
        <Link
          href="/dashboard"
          className="mb-4 block text-[13px] font-medium transition-opacity hover:opacity-90"
          style={{ color: 'rgba(255,255,255,0.68)' }}
        >
          ← Back to platform
        </Link>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px]" style={{ color: 'rgba(255,255,255,0.65)' }}>
            {user.name ?? user.email}
          </span>
          <LogoutButton className="shrink-0 text-[12px] text-white/60 transition-colors hover:text-white/90" />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

export default function CreatorStudioShell({
  children,
  user,
  spaces,
  activeSpace,
  collectiveLimit,
  liteData = EMPTY_LITE_DATA,
}: Props) {
  const pathname = usePathname()

  return (
    <>
      {/* ── Mobile: Creator Studio Lite (full replacement) ── */}
      <div className="md:hidden">
        <CreatorStudioLiteMobile user={user} activeSpace={activeSpace} spaces={spaces} liteData={liteData} />
      </div>

      {/* ── Desktop: Full Creator Studio ── */}
      <div className="hidden min-h-screen md:flex" style={{ background: '#F7F8FA' }}>
        <aside
          className="w-[248px] shrink-0"
          style={{ position: 'sticky', top: 0, height: '100vh' }}
        >
          <SidebarInner
            user={user}
            spaces={spaces}
            activeSpace={activeSpace}
            collectiveLimit={collectiveLimit}
            pathname={pathname}
          />
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </>
  )
}
