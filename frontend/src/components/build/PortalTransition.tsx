'use client'

import { useEffect, useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'

/**
 * Portal into Creator Studio (Atlas v1.2). The transition zooms into the
 * chosen Location's Atlas artwork, then travels through ocean, then fades
 * to white ready for the collective's home. No procedural artwork.
 */

interface Props {
  artworkUrl?: string | null
  locationName?: string | null
  onDone: () => void
}

export default function PortalTransition({ artworkUrl, locationName, onDone }: Props) {
  const [phase, setPhase] = useState<0 | 1 | 2 | 3>(0)

  useEffect(() => {
    const timers = [
      setTimeout(() => setPhase(1), 20),
      setTimeout(() => setPhase(2), 900),
      setTimeout(() => setPhase(3), 1800),
      setTimeout(() => onDone(), 2400),
    ]
    return () => timers.forEach(clearTimeout)
  }, [onDone])

  const resolvedUrl = resolveMediaUrl(artworkUrl ?? undefined)

  return (
    <div className="fixed inset-0 z-50 overflow-hidden" aria-hidden="true">
      {/* Zoom layer — the Atlas artwork travelling toward the viewer */}
      <div
        className="absolute inset-0 transition-all ease-out"
        style={{
          transitionDuration: '1000ms',
          transform: `scale(${phase >= 1 ? 1.9 : 0.94})`,
          opacity: phase >= 1 ? 1 : 0,
          transformOrigin: 'center',
          background: '#F4F7F6',
        }}
      >
        {resolvedUrl && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolvedUrl}
            alt={locationName ?? ''}
            style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'center' }}
          />
        )}
      </div>

      {/* Ocean */}
      <div
        className="absolute inset-0 transition-opacity ease-in-out"
        style={{
          transitionDuration: '800ms',
          opacity: phase >= 2 ? 1 : 0,
          background:
            'radial-gradient(70% 50% at 50% 50%, #062F35 0%, #051C27 55%, #030814 100%)',
        }}
      >
        {[
          { top: '22%', delay: '0ms',   width: '30vw', opacity: 0.28 },
          { top: '38%', delay: '260ms', width: '22vw', opacity: 0.20 },
          { top: '55%', delay: '520ms', width: '36vw', opacity: 0.32 },
          { top: '68%', delay: '160ms', width: '18vw', opacity: 0.18 },
          { top: '82%', delay: '380ms', width: '28vw', opacity: 0.24 },
        ].map((s, i) => (
          <span
            key={i}
            className="absolute left-full block h-[1.5px]"
            style={{
              top: s.top,
              width: s.width,
              background: `linear-gradient(90deg, transparent 0%, rgba(255,255,255,${s.opacity}) 50%, transparent 100%)`,
              animation: 'byp-streak 900ms ease-out forwards',
              animationDelay: s.delay,
            }}
          />
        ))}
      </div>

      {/* Arrival veil */}
      <div
        className="absolute inset-0 transition-opacity ease-in-out"
        style={{
          transitionDuration: '500ms',
          opacity: phase >= 3 ? 1 : 0,
          background: '#FFFFFF',
        }}
      />
    </div>
  )
}
