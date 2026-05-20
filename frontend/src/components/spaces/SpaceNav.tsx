'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

interface Tab {
  label: string
  href: string
  icon: string
  // Additional paths that should make this tab active
  alsoActiveOn?: RegExp
}

interface SpaceNavProps {
  spaceSlug: string
}

export default function SpaceNav({ spaceSlug }: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`

  const tabs: Tab[] = [
    {
      label: 'Collective',
      href: `${base}/community`,
      icon: '◈',
      // Also active when sitting at the bare space root (redirect target)
      alsoActiveOn: new RegExp(`^/spaces/${spaceSlug}$`),
    },
    {
      label: 'Pathways',
      href: `${base}/pathways`,
      icon: '◎',
    },
    {
      label: 'Gatherings',
      href: `${base}/events`,
      icon: '◷',
    },
    {
      label: 'Members',
      href: `${base}/members`,
      icon: '◉',
    },
    {
      label: 'About',
      href: `${base}/about`,
      icon: '◇',
    },
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
          </nav>
        </div>
      </div>

      {/* ── Mobile: fixed bottom nav ── */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface md:hidden">
        <div className="flex">
          {tabs.map((tab) => {
            const active = isActive(tab)
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={[
                  'flex flex-1 flex-col items-center gap-0.5 py-2.5 text-center transition-colors',
                  active ? 'text-teal-600' : 'text-slate-400',
                ].join(' ')}
              >
                <span className="text-base leading-none" aria-hidden="true">
                  {tab.icon}
                </span>
                <span className="text-[10px] font-medium">{tab.label}</span>
              </Link>
            )
          })}
        </div>
        {/* Safe area spacer for notched phones */}
        <div style={{ height: 'env(safe-area-inset-bottom)' }} className="bg-surface" />
      </nav>
    </>
  )
}
