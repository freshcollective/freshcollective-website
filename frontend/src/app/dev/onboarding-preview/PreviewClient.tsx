'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import WelcomeStep from '@/components/build/steps/WelcomeStep'
import ConfirmationStep from '@/components/build/steps/ConfirmationStep'
import type { DraftData, LocationOption } from '@/lib/build-your-collective/types'

export type ScreenKey = 'welcome' | 'final'

interface Props {
  initial: ScreenKey
}

/**
 * A stand-in Location + draft so ConfirmationStep renders with plausible
 * content. Nothing here is persisted or POSTed — every callback below is
 * a no-op that surfaces an in-page notice describing what would happen
 * in the live flow.
 *
 * The hero artwork URL is resolved client-side against
 * ``window.location.origin`` so it bypasses ``resolveMediaUrl``'s
 * backend-URL prefixing (which would send the request to :8000 and
 * 404 in dev). It renders blank for one paint until hydration
 * completes, then fills in.
 */
const MOCK_ARTWORK_PATH = '/world/login-hero.png'

const MOCK_LOCATION_BASE: LocationOption = {
  id: 'mock-location',
  key: 'harbour_of_calm',
  name: 'Harbour of Calm',
  description: 'A sheltered bay where creators come to think slowly.',
  hero_artwork_url: null,
  thumbnail_artwork_url: null,
  location_type: 'ATLAS',
}

const MOCK_DRAFT: DraftData = {
  name: 'The Quiet Hour',
  description: 'A weekly gathering for reflective practice.',
  location_id: 'mock-location',
  atmosphere_keys: ['warm', 'reflective', 'grounded', 'unhurried', 'welcoming'],
  colour_palette_key: 'sea-glass',
  identity_statement:
    'A place for practitioners returning to quiet, again and again.',
  welcome_message:
    'Welcome home. Whatever brought you here, there is time for it here — no rush, no roles to perform. Take off your shoes.',
  visibility: 'public',
  pricing_type: 'free',
}

const TOAST_TIMEOUT_MS = 6500

export default function PreviewClient({ initial }: Props) {
  const [screen, setScreen] = useState<ScreenKey>(initial)
  const [artworkUrl, setArtworkUrl] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    // Absolute URL so ConfirmationStep's ``resolveMediaUrl`` returns it
    // unchanged (only relative paths get the backend prefix).
    if (typeof window !== 'undefined') {
      setArtworkUrl(`${window.location.origin}${MOCK_ARTWORK_PATH}`)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    }
  }, [])

  const switchTo = (next: ScreenKey) => {
    setScreen(next)
    const params = new URLSearchParams(searchParams?.toString() ?? '')
    params.set('screen', next)
    router.replace(`/dev/onboarding-preview?${params.toString()}`, { scroll: false })
  }

  const showToast = useCallback((message: string) => {
    setToast(message)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(null), TOAST_TIMEOUT_MS)
  }, [])

  const dismissToast = () => {
    setToast(null)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
  }

  const mockLocation: LocationOption = {
    ...MOCK_LOCATION_BASE,
    hero_artwork_url: artworkUrl,
    thumbnail_artwork_url: artworkUrl,
  }

  return (
    <>
      <PreviewChrome current={screen} onSwitch={switchTo} />

      {screen === 'welcome' && (
        <WelcomeStep
          onBegin={() =>
            showToast('In the live flow, this would move you to the next step of the wizard (Choose your Location).')
          }
        />
      )}

      {screen === 'final' && (
        <ConfirmationStep
          draft={MOCK_DRAFT}
          location={mockLocation}
          mode="create"
          onOpen={(destination) => {
            if (destination === 'world_builders') {
              showToast('In the live flow, this creates the collective and opens World Builders Pathways.')
            } else if (destination === 'creator_studio') {
              showToast("In the live flow, this creates the collective and opens the new collective's Community area.")
            } else {
              showToast('In the live flow, this would create the collective.')
            }
          }}
          onBack={() =>
            showToast('In the live flow, this would return you to the Practical Details step.')
          }
          opening={false}
          error={null}
        />
      )}

      <PreviewToast message={toast} onDismiss={dismissToast} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Fixed top-right pill: screen switcher + always-visible preview notice
// ---------------------------------------------------------------------------

function PreviewChrome({
  current, onSwitch,
}: {
  current: ScreenKey
  onSwitch: (next: ScreenKey) => void
}) {
  const items: { key: ScreenKey; label: string }[] = [
    { key: 'welcome', label: 'Welcome' },
    { key: 'final', label: 'Final' },
  ]
  return (
    <div className="fixed right-4 top-4 z-[9999] flex flex-col items-end gap-2">
      <div
        className="flex items-center gap-1 rounded-full px-2 py-1.5"
        style={{
          background: 'rgba(12, 24, 38, 0.88)',
          boxShadow: '0 6px 20px rgba(12, 24, 38, 0.18)',
          backdropFilter: 'blur(6px)',
        }}
      >
        <span
          className="px-2 text-[10px] font-semibold uppercase tracking-[0.18em]"
          style={{ color: 'rgba(255,255,255,0.55)' }}
        >
          Preview
        </span>
        {items.map((it) => (
          <button
            key={it.key}
            type="button"
            onClick={() => onSwitch(it.key)}
            className="rounded-full px-3 py-1 text-[11px] font-semibold transition-colors"
            style={{
              background: current === it.key ? '#38A09E' : 'transparent',
              color: current === it.key ? '#FFFFFF' : 'rgba(255,255,255,0.75)',
            }}
          >
            {it.label}
          </button>
        ))}
      </div>
      <p
        className="max-w-[300px] rounded-lg px-3 py-1.5 text-right text-[10.5px] italic leading-snug"
        style={{
          background: 'rgba(12, 24, 38, 0.78)',
          color: 'rgba(255,255,255,0.75)',
          fontFamily: 'Georgia, serif',
          boxShadow: '0 4px 14px rgba(12, 24, 38, 0.14)',
          backdropFilter: 'blur(6px)',
        }}
      >
        Preview mode — actions are simulated and no data will be created.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Bottom-centered toast surfacing the intended production action.
// Click to dismiss; auto-dismisses after TOAST_TIMEOUT_MS.
// ---------------------------------------------------------------------------

function PreviewToast({
  message, onDismiss,
}: {
  message: string | null
  onDismiss: () => void
}) {
  if (!message) return null
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-6 z-[9999] flex justify-center px-4"
      role="status"
      aria-live="polite"
    >
      <button
        type="button"
        onClick={onDismiss}
        className="pointer-events-auto flex max-w-[560px] items-start gap-3 rounded-2xl px-5 py-3.5 text-left"
        style={{
          background: 'rgba(12, 24, 38, 0.92)',
          color: '#FFFFFF',
          boxShadow: '0 12px 40px rgba(12, 24, 38, 0.28)',
          backdropFilter: 'blur(8px)',
          animation: 'byp-toast-in 220ms ease-out both',
        }}
      >
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.16em]"
          style={{ background: 'rgba(56, 160, 158, 0.28)', color: '#B7EDE9' }}
        >
          Preview
        </span>
        <span
          className="text-[13px] leading-relaxed italic"
          style={{ fontFamily: 'Georgia, serif', color: 'rgba(255,255,255,0.92)' }}
        >
          {message}
        </span>
        <span
          className="ml-2 shrink-0 text-[11px] opacity-60"
          aria-hidden="true"
          style={{ letterSpacing: '0.06em' }}
        >
          ×
        </span>
      </button>
      <style jsx>{`
        @keyframes byp-toast-in {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  )
}
