'use client'

import { useEffect, useRef, useState, useTransition } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import LogoutButton from '@/components/layout/LogoutButton'
import { resolveMediaUrl } from '@/lib/api'
import type { SpaceSummary } from '@/types/platform'

/**
 * Creator Studio Sidebar — the light, editorial navigation column.
 *
 * Information architecture:
 *   - The active collective card sits at the top so the sidebar always
 *     answers "which collective am I in".
 *   - THE COLLECTIVE / OFFERINGS / COMMUNITY / COMMERCE group everything
 *     that belongs to the currently-active collective. Switching
 *     collectives changes what these destinations show.
 *   - ACCOUNT sits separately at the bottom because it belongs to the
 *     signed-in creator across ALL of their collectives.
 *
 * Consumed by:
 *   - app/creator-studio/layout.tsx
 *   - app/creator/layout.tsx
 */

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface NavItem {
  href: string
  label: string
  exact?: boolean
  activeOnPath?: RegExp
  /** Dims until an active collective exists. */
  requiresCollective?: boolean
}

// Collective-scoped nav — everything under these labels is about the
// currently-active collective. Switching collectives changes what
// each destination reveals.
const COLLECTIVE_NAV: { label: string; items: NavItem[] }[] = [
  {
    label: '🌿 THE COLLECTIVE',
    items: [
      { href: '/creator-studio',          label: 'Your World',        exact: true },
      { href: '/creator-studio/home',     label: 'Home',              requiresCollective: true },
      { href: '/creator-studio/settings', label: 'Collective Settings', activeOnPath: /^\/creator\/spaces\/[^/]+$/, requiresCollective: true },
      { href: '/creator-studio/assets',   label: 'Media Library',     requiresCollective: true },
    ],
  },
  {
    label: '📖 OFFERINGS',
    items: [
      { href: '/creator-studio/pathways',  label: 'Pathways',   activeOnPath: /^\/creator\/spaces\/[^/]+\/pathways/, requiresCollective: true },
      { href: '/creator-studio/resources', label: 'Resources',  requiresCollective: true },
    ],
  },
  {
    label: '🤝 COMMUNITY',
    items: [
      { href: '/creator-studio/community',  label: 'Conversations', activeOnPath: /^\/creator\/spaces\/[^/]+\/community/, requiresCollective: true },
      { href: '/creator-studio/gatherings', label: 'Gatherings',    activeOnPath: /^\/creator\/spaces\/[^/]+\/events/,    requiresCollective: true },
      { href: '/creator-studio/people',     label: 'People',        requiresCollective: true },
      { href: '/creator-studio/passes',     label: 'Memberships',   requiresCollective: true },
    ],
  },
  {
    label: '💰 COMMERCE',
    items: [
      { href: '/creator-studio/payments', label: 'Payments' },
      { href: '/creator-studio/billing',  label: 'Billing' },
    ],
  },
]

// Account-scoped nav — belongs to the signed-in creator, not to any
// particular collective. Sits visually separated at the bottom.
const ACCOUNT_NAV: NavItem[] = [
  { href: '/creator-studio/account', label: 'Account' },
]

interface Props {
  user: User
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  collectiveLimit: number
  /** Platform Owner: unlimited collectives, no plan copy in the switcher. */
  isPlatformOwner: boolean
  /** The active collective's Location thumbnail. */
  activeLocationThumbnail?: string | null
}

export default function CreatorStudioSidebar({
  user, spaces, activeSpace, collectiveLimit, isPlatformOwner, activeLocationThumbnail = null,
}: Props) {
  const pathname = usePathname()

  function isActive(href: string, exact?: boolean, activeOnPath?: RegExp) {
    if (exact) return pathname === href
    if (pathname.startsWith(href)) return true
    if (activeOnPath && activeOnPath.test(pathname)) return true
    return false
  }

  const hasCollective = !!activeSpace

  return (
    <div className="flex h-full flex-col bg-white" style={{ borderRight: '1px solid #E2E8F0' }}>

      {/* ── Brand ── */}
      <div
        className="flex items-center gap-2.5 px-5 py-4"
        style={{ borderBottom: '1px solid #E2E8F0' }}
      >
        <span
          aria-hidden="true"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          <span className="h-3 w-3 rounded-sm bg-white/95" />
        </span>
        <div>
          <div className="text-[13px] font-semibold leading-none" style={{ color: '#0F172A' }}>
            Fresh Collective
          </div>
          <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Creator Studio
          </div>
        </div>
      </div>

      {/* ── Active collective switcher ── */}
      <CollectiveSwitcher
        spaces={spaces}
        activeSpace={activeSpace}
        activeLocationThumbnail={activeLocationThumbnail}
        collectiveLimit={collectiveLimit}
        isPlatformOwner={isPlatformOwner}
      />

      {/* ── Collective-scoped nav ── */}
      <nav aria-label="Creator Studio" className="flex-1 overflow-y-auto px-3 py-4">
        {COLLECTIVE_NAV.map(({ label, items }) => (
          <div key={label} className="mb-5">
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              {label}
            </p>
            <ul className="space-y-0.5">
              {items.map(({ href, label: itemLabel, exact, activeOnPath, requiresCollective }) => {
                const active = isActive(href, exact, activeOnPath)
                const dimmed = (requiresCollective ?? false) && !hasCollective
                return (
                  <li key={href}>
                    <Link
                      href={dimmed ? '/creator-studio/create' : href}
                      className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                        active
                          ? 'bg-teal-50 text-teal-700'
                          : dimmed
                            ? 'cursor-default text-slate-300'
                            : 'text-slate-700 hover:bg-slate-50 hover:text-slate-900'
                      }`}
                      style={active
                        ? { border: '1px solid rgba(56,160,158,0.20)' }
                        : { border: '1px solid transparent' }}
                      tabIndex={dimmed ? -1 : undefined}
                      aria-current={active ? 'page' : undefined}
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

        {/* ── Account-scoped nav ── visually separated from the
             collective-scoped groups above. Belongs to the creator, not
             to whichever collective they happen to be tending. */}
        <div
          className="mt-6 pt-4"
          style={{ borderTop: '1px solid #E2E8F0' }}
        >
          <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            ACCOUNT
          </p>
          <ul className="space-y-0.5">
            {ACCOUNT_NAV.map(({ href, label: itemLabel }) => {
              const active = pathname.startsWith(href)
              return (
                <li key={href}>
                  <Link
                    href={href}
                    className={`flex items-center rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                      active
                        ? 'bg-teal-50 text-teal-700'
                        : 'text-slate-700 hover:bg-slate-50 hover:text-slate-900'
                    }`}
                    style={active
                      ? { border: '1px solid rgba(56,160,158,0.20)' }
                      : { border: '1px solid transparent' }}
                    aria-current={active ? 'page' : undefined}
                  >
                    {itemLabel}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      </nav>

      {/* ── Footer ── */}
      <div
        className="space-y-2 px-5 py-4"
        style={{ borderTop: '1px solid #E2E8F0' }}
      >
        <p className="truncate text-[11px] text-slate-500">
          {user.name ?? user.email}
        </p>
        <Link
          href="/dashboard"
          className="block text-[12px] text-slate-600 transition-colors hover:text-slate-800"
        >
          ← Back to Your World
        </Link>
        <LogoutButton className="block text-[12px] text-slate-600 transition-colors hover:text-red-500" />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Collective switcher — compact identifier + click-to-switch dropdown.
// "Which collective am I in?" is answered by the artwork thumbnail + name
// + current status. The click affordance is left implicit (the whole card
// is a button with a chevron); we no longer advertise "Switch" as text.
// ---------------------------------------------------------------------------

const STATUS_LABEL: Record<string, string> = {
  active: 'Live',
  draft: 'Draft',
  archived: 'Archived',
}

function CollectiveSwitcher({
  spaces, activeSpace, activeLocationThumbnail, collectiveLimit, isPlatformOwner,
}: {
  spaces: SpaceSummary[]
  activeSpace: SpaceSummary | null
  activeLocationThumbnail: string | null
  collectiveLimit: number
  isPlatformOwner: boolean
}) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [pendingSlug, setPendingSlug] = useState<string | null>(null)
  const [, startTransition] = useTransition()
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (!rootRef.current) return
      if (!rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const activeSpaceCount = spaces.filter((s) => s.status !== 'archived').length
  const atLimit = !isPlatformOwner && activeSpaceCount >= collectiveLimit

  function switchTo(slug: string) {
    if (slug === activeSpace?.slug) { setOpen(false); return }
    setPendingSlug(slug)
    startTransition(() => {
      document.cookie = `fc_creator_space=${slug}; path=/; max-age=86400`
      // Full-refresh the layout tree so the sidebar's activeSpace prop
      // reflects the new cookie. Without refresh() the client router
      // cache serves the previous layout render.
      router.refresh()
      router.push('/creator-studio/home')
      setOpen(false)
      setPendingSlug(null)
    })
  }

  const artworkResolved = resolveMediaUrl(activeLocationThumbnail ?? undefined)

  return (
    <div
      ref={rootRef}
      className="relative px-3 py-4"
      style={{ borderBottom: '1px solid #E2E8F0' }}
    >
      {activeSpace ? (
        <button
          type="button"
          onClick={() => setOpen(v => !v)}
          aria-expanded={open}
          aria-label={`${activeSpace.name} — click to switch collective`}
          className="flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
        >
          <span
            aria-hidden="true"
            className="relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg"
            style={{
              background: artworkResolved
                ? '#F4F7F6'
                : 'linear-gradient(135deg, rgba(56,160,158,0.22) 0%, rgba(85,184,182,0.14) 100%)',
              border: '1px solid rgba(12,24,38,0.06)',
            }}
          >
            {artworkResolved ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={artworkResolved} alt="" className="h-full w-full object-cover" />
            ) : (
              <span className="font-serif text-[13px] text-teal-700">
                {activeSpace.name.charAt(0)}
              </span>
            )}
          </span>

          <div className="min-w-0 flex-1">
            <p className="truncate font-serif text-[14px] leading-tight" style={{ color: '#0C1826' }}>
              {activeSpace.name}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-500">
              {STATUS_LABEL[activeSpace.status] ?? activeSpace.status}
            </p>
          </div>

          <span
            aria-hidden="true"
            className={`shrink-0 text-[10px] text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
          >
            ▾
          </span>
        </button>
      ) : (
        <div className="rounded-xl bg-slate-50 px-3 py-3 text-center">
          <p className="text-[12px] text-slate-500">No collective yet.</p>
          <Link
            href="/build-your-collective"
            className="mt-1 inline-block text-[12px] font-medium text-teal-700 hover:underline"
          >
            Build your first →
          </Link>
        </div>
      )}

      {open && spaces.length > 0 && (
        <div
          className="absolute left-3 right-3 top-full z-20 mt-1 overflow-hidden rounded-xl bg-white"
          style={{
            border: '1px solid #E2E8F0',
            boxShadow: '0 10px 30px rgba(12, 24, 38, 0.10), 0 2px 6px rgba(12, 24, 38, 0.04)',
          }}
        >
          <p className="border-b border-slate-100 px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Your collectives
          </p>
          <ul className="max-h-64 overflow-y-auto py-1">
            {spaces.map((s) => {
              const isCurrent = s.slug === activeSpace?.slug
              const isPendingThis = pendingSlug === s.slug
              return (
                <li key={s.slug}>
                  <button
                    type="button"
                    onClick={() => switchTo(s.slug)}
                    className="flex w-full items-center gap-2.5 px-4 py-2 text-left transition-colors hover:bg-slate-50"
                    style={{ background: isCurrent ? 'rgba(56,160,158,0.06)' : undefined }}
                  >
                    <span className="min-w-0 flex-1">
                      <span
                        className="block truncate font-serif text-[13.5px] leading-tight"
                        style={{ color: isCurrent ? '#0C1826' : '#334155' }}
                      >
                        {s.name}
                      </span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">
                        {STATUS_LABEL[s.status] ?? s.status}
                        {isPendingThis && ' · Switching…'}
                      </span>
                    </span>
                    {isCurrent && (
                      <span
                        className="shrink-0 rounded-full px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.12em]"
                        style={{ background: 'rgba(56,160,158,0.12)', color: '#0f766e' }}
                      >
                        Current
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
          <div className="border-t border-slate-100 px-4 py-2.5">
            {!atLimit ? (
              <Link
                href="/build-your-collective"
                className="flex items-center gap-1.5 text-[12px] font-medium text-teal-700 transition-opacity hover:opacity-80"
                onClick={() => setOpen(false)}
              >
                <span aria-hidden="true" className="text-[14px] leading-none">+</span>
                Build another collective
              </Link>
            ) : (
              <div>
                <p className="text-[11px] text-slate-500">
                  {activeSpaceCount} of {collectiveLimit} collectives used
                </p>
                <Link
                  href="/creator-studio/billing"
                  onClick={() => setOpen(false)}
                  className="mt-0.5 block text-[11px] text-teal-700 transition-opacity hover:opacity-80"
                >
                  View plan →
                </Link>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
