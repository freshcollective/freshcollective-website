'use client'

import { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import CollectiveSettingsModal from '@/components/spaces/CollectiveSettingsModal'

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
}

export default function SpaceNav({ spaceSlug, spaceName, isMember }: SpaceNavProps) {
  const pathname = usePathname()
  const base = `/spaces/${spaceSlug}`
  const [notifOpen, setNotifOpen] = useState(false)

  const tabs: Tab[] = [
    {
      label: 'Collective',
      href: `${base}/community`,
      icon: '◈',
      alsoActiveOn: new RegExp(`^/spaces/${spaceSlug}$`),
    },
    { label: 'Pathways',  href: `${base}/pathways`, icon: '◎' },
    { label: 'Gatherings', href: `${base}/events`,  icon: '◷' },
    { label: 'Members',   href: `${base}/members`,  icon: '◉' },
    { label: 'About',     href: `${base}/about`,    icon: '◇' },
  ]

  function isActive(tab: Tab): boolean {
    if (tab.alsoActiveOn?.test(pathname)) return true
    return pathname.startsWith(tab.href)
  }

  return (
    <>
      {notifOpen && (
        <CollectiveSettingsModal
          spaceSlug={spaceSlug}
          spaceName={spaceName}
          onClose={() => setNotifOpen(false)}
        />
      )}

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

            {isMember && (
              <button
                onClick={() => setNotifOpen(true)}
                className="inline-block shrink-0 border-b-2 border-transparent px-4 py-3 text-sm font-medium text-slate-500 transition-colors hover:text-navy-700"
              >
                Notifications
              </button>
            )}
          </nav>
        </div>
      </div>

      {/* ── Mobile: fixed bottom nav ── */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-border bg-surface md:hidden">
        <div className="flex overflow-x-auto">
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

          {isMember && (
            <button
              onClick={() => setNotifOpen(true)}
              className="flex flex-1 flex-col items-center gap-0.5 py-2.5 text-center text-slate-400 transition-colors hover:text-teal-600"
            >
              <span className="text-base leading-none" aria-hidden="true">🔔</span>
              <span className="text-[10px] font-medium">Notifications</span>
            </button>
          )}
        </div>
        <div style={{ height: 'env(safe-area-inset-bottom)' }} className="bg-surface" />
      </nav>
    </>
  )
}
