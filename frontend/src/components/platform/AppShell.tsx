'use client'

import { useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from './utils'

/**
 * Fresh Collective AppShell
 *
 * A slot-based composition that hosts application chrome per §12 and §22.
 * AppShell supports two layout variants:
 *
 *   1. **Top-bar** (default) — horizontal top navigation with brand + primary
 *      destinations + utility. Used by member-facing surfaces and marketing.
 *
 *   2. **Sidebar** — left-anchored sidebar containing everything (brand,
 *      nav, utility). Used by "working density" surfaces (Creator Studio,
 *      Admin) where nav complexity exceeds the 5-item top-bar cap.
 *      On mobile the sidebar collapses into a slide-in drawer triggered
 *      by a hamburger button in a compact top rail.
 *
 * AppShell renders the shell. It does NOT own its own children — each
 * area supplies its own brand + nav content.
 *
 * @see docs/fresh-design-language.md §12
 */

export interface AppShellNavItem {
  label: string
  href: string
  /** Marks the item as the current section. When true it renders the active state. */
  active?: boolean
}

interface AppShellTopBarProps {
  variant?: 'top-bar'
  /** Brand mark rendered at the far left of the top bar. */
  brand: ReactNode
  /** Primary navigation destinations. 2–5 items per §12.1. */
  primary?: readonly AppShellNavItem[]
  /** Right-hand utility cluster (notifications, profile, sign in). */
  utility?: ReactNode
  /** Optional secondary navigation bar rendered below the primary bar. */
  secondary?: ReactNode
  /** Sticky top bar. Defaults to true. */
  sticky?: boolean
  /** When true, the shell uses a transparent overlay style over a dark hero. */
  overlay?: boolean
  className?: string
  children: ReactNode

  /** Sidebar-mode props are not used here. */
  sidebar?: never
  mobileBrand?: never
  sidebarWidth?: never
}

interface AppShellSidebarProps {
  variant: 'sidebar'
  /**
   * Sidebar content — owned entirely by the consumer. On desktop it renders
   * as a fixed-width column; on mobile it becomes a slide-in drawer.
   */
  sidebar: ReactNode
  /**
   * Content rendered next to the hamburger button in the mobile top rail.
   * Typically a small wordmark or section label.
   */
  mobileBrand?: ReactNode
  /** Sidebar width in pixels. Defaults to 248. */
  sidebarWidth?: number
  className?: string
  children: ReactNode

  /** Top-bar props are not used here. */
  brand?: never
  primary?: never
  utility?: never
  secondary?: never
  sticky?: never
  overlay?: never
}

type AppShellProps = AppShellTopBarProps | AppShellSidebarProps

// ---------------------------------------------------------------------------
// AppShell (top-level)
// ---------------------------------------------------------------------------

export function AppShell(props: AppShellProps) {
  if (props.variant === 'sidebar') {
    return <AppShellSidebar {...props} />
  }
  return <AppShellTopBar {...props} />
}

// ---------------------------------------------------------------------------
// Top-bar variant
// ---------------------------------------------------------------------------

function AppShellTopBar({
  brand, primary, utility, secondary,
  sticky = true, overlay = false,
  className, children,
}: AppShellTopBarProps) {
  const items = primary ?? []
  if (items.length > 5) {
    if (typeof console !== 'undefined') {
      console.warn(
        `[Fresh Collective AppShell] Primary navigation has ${items.length} items; §12.1 caps at 5.`,
      )
    }
  }

  const barColour = overlay
    ? 'bg-transparent'
    : 'bg-[color:var(--fc-surface-card)]/95 backdrop-blur-xl'

  const barBorder = overlay
    ? ''
    : 'border-b border-[color:var(--fc-border-hairline)]'

  return (
    <div className={cn('flex min-h-full flex-col', className)}>
      <header
        className={cn(
          sticky ? 'sticky top-0' : '',
          'z-[var(--fc-z-sticky)]',
          barColour,
          barBorder,
        )}
      >
        <div className="mx-auto flex h-16 w-full max-w-[var(--fc-container-app)] items-center justify-between gap-6 px-6 md:px-10">
          <div className="flex min-w-0 items-center gap-8">
            <div className="shrink-0">{brand}</div>
            {items.length > 0 && (
              <nav
                aria-label="Primary"
                className="hidden items-center gap-6 md:flex"
              >
                {items.map((item) => (
                  <AppShellNavLink key={item.href} item={item} overlay={overlay} />
                ))}
              </nav>
            )}
          </div>
          {utility && (
            <div className="flex shrink-0 items-center gap-3">{utility}</div>
          )}
        </div>

        {secondary && (
          <div
            className={cn(
              'border-t border-[color:var(--fc-border-hairline)]',
              overlay ? '' : 'bg-[color:var(--fc-surface-card)]',
            )}
          >
            <div className="mx-auto w-full max-w-[var(--fc-container-app)] px-6 md:px-10">
              {secondary}
            </div>
          </div>
        )}
      </header>

      <main className="flex-1">{children}</main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sidebar variant
// ---------------------------------------------------------------------------

function AppShellSidebar({
  sidebar, mobileBrand, sidebarWidth = 248,
  className, children,
}: AppShellSidebarProps) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const pathname = usePathname()

  // Derived state: close the drawer whenever the URL changes.
  // Uses the React docs "reset state when a prop changes" pattern to avoid
  // the react-hooks/set-state-in-effect rule.
  const [prevPathname, setPrevPathname] = useState(pathname)
  if (prevPathname !== pathname) {
    setPrevPathname(pathname)
    if (drawerOpen) setDrawerOpen(false)
  }

  // Escape closes the drawer.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setDrawerOpen(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  // Lock body scroll while the drawer is open.
  useEffect(() => {
    if (!drawerOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [drawerOpen])

  return (
    <div className={cn('min-h-full', className)}>
      {/* Mobile: sticky top rail with hamburger + brand */}
      <header
        className="sticky top-0 z-[var(--fc-z-sticky)] flex h-14 items-center gap-3 border-b border-[color:var(--fc-border-hairline)] bg-[color:var(--fc-surface-card)] px-4 md:hidden"
      >
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Open navigation"
          aria-expanded={drawerOpen}
          aria-controls="fc-appshell-sidebar"
          className="inline-flex h-10 w-10 items-center justify-center rounded-[var(--fc-radius-md)] text-[color:var(--fc-ink-heading)] transition-colors hover:bg-[color:var(--fc-surface-muted)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40"
        >
          <svg width="20" height="14" viewBox="0 0 20 14" fill="none" aria-hidden="true">
            <line x1="0" y1="1"  x2="20" y2="1"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            <line x1="0" y1="7"  x2="20" y2="7"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            <line x1="0" y1="13" x2="20" y2="13" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
          </svg>
        </button>
        {mobileBrand && <div className="min-w-0 flex-1 truncate">{mobileBrand}</div>}
      </header>

      {/* Desktop: two-column layout (aside + main).
          Mobile: drawer variant sits above content. */}
      <div className="md:flex md:min-h-full" style={{ background: 'var(--fc-surface-page)' }}>
        {/* Mobile drawer backdrop */}
        {drawerOpen && (
          <div
            aria-hidden="true"
            onClick={() => setDrawerOpen(false)}
            className="fixed inset-0 z-[var(--fc-z-drawer-backdrop)] bg-[rgba(15,30,55,0.30)] md:hidden"
            style={{ animation: 'fc-fade-in 180ms ease-out' }}
          />
        )}

        <aside
          id="fc-appshell-sidebar"
          aria-label="Primary navigation"
          className={cn(
            // Desktop: fixed left column, sticky within its own scroll.
            'md:sticky md:top-0 md:h-screen md:shrink-0 md:translate-x-0',
            // Mobile: slide-in from left; hidden off-screen when closed.
            'fixed inset-y-0 left-0 z-[var(--fc-z-drawer)] w-[280px]',
            'transition-transform duration-[var(--fc-motion-drawer)]',
            drawerOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
          )}
          style={{
            width: undefined,
            // Use maxWidth on mobile for slide-in, fixed width on desktop
          }}
        >
          <div
            className="h-full md:w-[248px]"
            style={{ width: `${sidebarWidth}px`, maxWidth: '100vw' }}
          >
            {sidebar}
          </div>
        </aside>

        {/* Main content region. Reserves left space for the sidebar on
            desktop; on mobile the sidebar overlays so no offset needed. */}
        <main className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared link component
// ---------------------------------------------------------------------------

/**
 * AppShellNavLink — one primary-nav link.
 * Fresh Collective uses a subtle underline for the active item (§12.2 style, adapted
 * to the top bar).
 */
function AppShellNavLink({
  item, overlay,
}: { item: AppShellNavItem; overlay: boolean }) {
  const color = overlay
    ? item.active
      ? 'text-[color:var(--fc-ink-inverse)]'
      : 'text-[color:var(--fc-ink-inverse)]/80 hover:text-[color:var(--fc-ink-inverse)]'
    : item.active
      ? 'text-[color:var(--fc-ink-heading)]'
      : 'text-[color:var(--fc-ink-primary)]/70 hover:text-[color:var(--fc-ink-heading)]'
  return (
    <Link
      href={item.href}
      aria-current={item.active ? 'page' : undefined}
      className={cn(
        'relative inline-flex items-center py-2 text-[14px] font-[var(--fc-fw-semibold)] transition-colors duration-[var(--fc-motion-hover)]',
        'focus:outline-none focus-visible:text-[color:var(--fc-accent-700)]',
        color,
      )}
    >
      {item.label}
      {item.active && (
        <span
          aria-hidden="true"
          className="absolute inset-x-0 -bottom-px h-0.5 bg-[color:var(--fc-accent-500)]"
        />
      )}
    </Link>
  )
}

/**
 * AppShellBrand — a minimal wordmark composition that pairs the standard
 * Fresh Collective teal square glyph with a label. Areas may substitute their own
 * brand element by passing anything into the shell's `brand` prop.
 */
export function AppShellBrand({
  href = '/', label = 'Fresh Collective', overlay = false,
}: {
  href?: string
  label?: string
  overlay?: boolean
}) {
  const textColour = overlay
    ? 'text-[color:var(--fc-ink-inverse)]'
    : 'text-[color:var(--fc-ink-heading)]'
  return (
    <Link
      href={href}
      className={cn(
        'group inline-flex items-center gap-2.5',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--fc-accent-500)]/40 focus-visible:ring-offset-2 rounded-[var(--fc-radius-sm)]',
      )}
    >
      <span
        aria-hidden="true"
        className="flex h-7 w-7 items-center justify-center rounded-[var(--fc-radius-md)]"
        style={{ background: 'var(--fc-accent-gradient)' }}
      >
        <span
          className="h-3 w-3 rounded-[3px] bg-[color:var(--fc-ink-inverse)]"
          style={{ opacity: 0.92 }}
        />
      </span>
      <span
        className={cn(
          'text-[15px] font-[var(--fc-fw-semibold)] tracking-[-0.02em] transition-opacity group-hover:opacity-80',
          textColour,
        )}
      >
        {label}
      </span>
    </Link>
  )
}
