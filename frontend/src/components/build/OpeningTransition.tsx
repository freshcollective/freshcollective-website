'use client'

import { useEffect, useState } from 'react'

/**
 * A calm four-beat interlude between the practical-details step and the
 * reveal. Not a spinner — a small ritual. Four fading messages over soft
 * concentric ripples, ~4 seconds total.
 *
 * The component invokes `onDone` after the last message has held for its
 * beat, so the reveal appears just as the last line finishes settling.
 */

const MESSAGES = [
  'Gathering your choices…',
  'Shaping the landscape…',
  'Lighting the campfire…',
  'Your place is almost ready…',
] as const

const BEAT_MS = 1000

interface Props {
  onDone: () => void
}

export default function OpeningTransition({ onDone }: Props) {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    for (let i = 1; i < MESSAGES.length; i++) {
      timers.push(setTimeout(() => setPhase(i), BEAT_MS * i))
    }
    timers.push(setTimeout(onDone, BEAT_MS * MESSAGES.length))
    return () => timers.forEach(clearTimeout)
  }, [onDone])

  return (
    <main
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{
        background:
          'radial-gradient(60% 45% at 50% 50%, rgba(56, 160, 158, 0.05), transparent 65%),' +
          'linear-gradient(180deg, #FFFFFF 0%, #FBFDFD 100%)',
      }}
      aria-live="polite"
      aria-busy="true"
    >
      <div className="relative flex flex-col items-center">
        {/* Soft ripples emanating from a single warm point */}
        <div className="relative mb-14 h-32 w-32" aria-hidden="true">
          {[0, 900, 1800].map((delay, i) => (
            <span
              key={i}
              className="absolute inset-0 rounded-full"
              style={{
                border: '1px solid rgba(56, 160, 158, 0.35)',
                animation: 'byp-ripple 2.6s ease-out infinite',
                animationDelay: `${delay}ms`,
                transformOrigin: 'center',
              }}
            />
          ))}
          <span
            className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
            style={{
              background: 'radial-gradient(circle, #D4B048 0%, rgba(212, 176, 72, 0) 70%)',
              boxShadow: '0 0 22px rgba(212, 176, 72, 0.55)',
              animation: 'byp-drift 3.5s ease-in-out infinite',
            }}
          />
        </div>

        {/* The four messages — cross-fade between beats */}
        <div className="relative h-6 w-full min-w-[320px] text-center">
          {MESSAGES.map((msg, i) => (
            <p
              key={msg}
              className="absolute inset-0 whitespace-nowrap text-[15px] italic transition-opacity duration-[700ms] ease-in-out"
              style={{
                color: 'rgba(12, 24, 38, 0.78)',
                fontFamily: 'Georgia, serif',
                opacity: phase === i ? 1 : 0,
              }}
            >
              {msg}
            </p>
          ))}
        </div>
      </div>
    </main>
  )
}
