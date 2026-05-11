'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

interface Tab {
  label: string
  href: string
  exact?: boolean
}

interface SpaceNavProps {
  spaceSlug: string
}

export default function SpaceNav({ spaceSlug }: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`

  const tabs: Tab[] = [
    { label: 'Home', href: base, exact: true },
    { label: 'Pathways', href: `${base}/pathways` },
    { label: 'Community', href: `${base}/community` },
    { label: 'Events', href: `${base}/events` },
    { label: 'Members', href: `${base}/members` },
  ]

  function isActive(tab: Tab) {
    if (tab.exact) return pathname === tab.href
    return pathname.startsWith(tab.href)
  }

  return (
    <div className="border-b border-border bg-surface">
      <div className="mx-auto max-w-6xl px-6 md:px-10">
        <nav className="flex gap-0 overflow-x-auto">
          {tabs.map((tab) => (
            <Link
              key={tab.href}
              href={tab.href}
              className={[
                'inline-block shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors',
                isActive(tab)
                  ? 'border-teal-500 text-navy-900'
                  : 'border-transparent text-slate-500 hover:text-navy-700',
              ].join(' ')}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  )
}
