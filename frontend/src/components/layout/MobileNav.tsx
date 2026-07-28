'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'

interface Props {
  isLoggedIn: boolean
  // Mirrors the backend's discovery_pillar_enabled flag; passed in from
  // PublicHeader so this client component doesn't have to read
  // process.env directly (keeps the flag surface in one place).
  discoveryOn: boolean
  dark?: boolean
}

// Peer destinations for the mobile drawer. Order matches the pillar
// order in docs/foundations/discovery-connection-belonging-v1.1.md.
// "Your World" only appears for signed-in visitors.
function peerNavItems(isLoggedIn: boolean, discoveryOn: boolean): Array<{ href: string; label: string }> {
  const items: Array<{ href: string; label: string }> = []
  if (isLoggedIn && discoveryOn) items.push({ href: '/dashboard', label: 'Your World' })
  items.push({ href: '/spaces', label: 'Explore Collectives' })
  if (discoveryOn) {
    items.push({ href: '/discover-places', label: 'Discover Places' })
    items.push({ href: '/ways-to-connect', label: 'Ways to Connect' })
  }
  return items
}

export default function MobileNav({ isLoggedIn, discoveryOn, dark }: Props) {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()
  const router = useRouter()
  const [prevPath, setPrevPath] = useState(pathname)

  // Reset menu when route changes — derived-state pattern (React docs)
  if (prevPath !== pathname) {
    setPrevPath(pathname)
    if (open) setOpen(false)
  }

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  async function handleLogout() {
    await fetch(apiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' }).catch(() => {})
    router.push('/')
    router.refresh()
  }

  return (
    <div className="md:hidden">
      {/* Hamburger button */}
      <button
        onClick={() => setOpen(!open)}
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-colors"
        style={{ color: dark ? '#FFFFFF' : '#0C1826' }}
      >
        <svg width="20" height="14" viewBox="0 0 20 14" fill="none" aria-hidden="true">
          {open ? (
            <path
              d="M2 2L18 12M18 2L2 12"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
            />
          ) : (
            <>
              <line x1="0" y1="1"  x2="20" y2="1"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
              <line x1="0" y1="7"  x2="20" y2="7"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
              <line x1="0" y1="13" x2="20" y2="13" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            </>
          )}
        </svg>
      </button>

      {/* Overlay + Panel */}
      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 top-16 z-40 bg-black/20 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          />

          {/* Drawer */}
          <div className="absolute inset-x-0 top-16 z-50 px-5 pb-8 pt-4"
            style={{ background: '#0C1826', borderBottom: '1px solid rgba(255,255,255,0.07)', boxShadow: '0 16px 48px rgba(0,0,0,0.50)' }}>

            <nav className="mb-5 space-y-0.5">
              {peerNavItems(isLoggedIn, discoveryOn).map(({ href, label }) => (
                <Link
                  key={href}
                  href={href}
                  className="flex items-center rounded-xl px-4 py-3.5 text-[16px] font-medium transition-colors"
                  style={{ color: '#FFFFFF' }}
                >
                  {label}
                </Link>
              ))}
              {/* Keep Your World reachable in mobile drawer while
                  Discovery is off — this mirrors the desktop
                  right-side shortcut so signed-in visitors don't lose
                  the direct link. Once discoveryOn=true, Your World
                  is the first peer nav item above. */}
              {isLoggedIn && !discoveryOn && (
                <Link
                  href="/dashboard"
                  className="flex items-center rounded-xl px-4 py-3.5 text-[16px] font-medium transition-colors"
                  style={{ color: '#FFFFFF' }}
                >
                  Your World
                </Link>
              )}
            </nav>

            <div className="flex flex-col gap-2.5 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}>
              {isLoggedIn ? (
                <button
                  onClick={handleLogout}
                  className="w-full rounded-xl py-3.5 text-[15px] font-medium transition-colors"
                  style={{ border: '1px solid rgba(255,255,255,0.12)', color: '#FFFFFF' }}
                >
                  Log out
                </button>
              ) : (
                <>
                  <Link
                    href="/login"
                    className="w-full rounded-xl py-3.5 text-center text-[15px] font-medium transition-colors"
                    style={{ border: '1px solid rgba(255,255,255,0.12)', color: '#FFFFFF' }}
                  >
                    Log in
                  </Link>
                  <Link
                    href="/signup"
                    className="w-full rounded-xl py-3.5 text-center text-[15px] font-semibold text-white transition-all"
                    style={{
                      background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                      boxShadow: 'var(--fc-shadow-btn)',
                    }}
                  >
                    Join Fresh Collective
                  </Link>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
