/**
 * The square at the top of a person card.
 *
 * Two states and only two: the member's photo when the server has
 * decided it is visible here, otherwise a polished initial on a warm
 * neutral gradient. No shared-Collective artwork, no Place artwork,
 * no category colour — the person is the visual, and standing in
 * something else's image for a missing photo would quietly make the
 * card about that thing instead.
 *
 * The gradient is deliberately warm-stone and deliberately the same
 * for everybody. An earlier prototype tinted it by the *kind* of
 * overlap, which turned a portrait into a badge for a taxonomy the
 * member never asked about. Most members have no photo, so this state
 * is the common one and has to look considered rather than absent.
 */

'use client'

import { useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'

const WARM_STONE =
  'radial-gradient(ellipse at 28% 26%, rgba(255,255,255,0.55), transparent 60%),' +
  'linear-gradient(155deg, #EFEDE7 0%, #D8D3CA 100%)'
const INK = '#2E3B47'
const PHOTO_BG = '#F1EFEB'

function initialFor(name: string): string {
  const letter = name.trim().charAt(0)
  return letter ? letter.toUpperCase() : '·'
}

export default function PersonPortrait({
  name,
  avatarUrl,
}: {
  /** Always a real name — unnamed members never receive a card. */
  name: string
  avatarUrl: string | null
}) {
  const [failed, setFailed] = useState(false)
  const resolved = failed ? null : resolveMediaUrl(avatarUrl ?? undefined)

  return (
    <div
      className="relative w-full overflow-hidden"
      style={{
        // Square against the card's width, whatever that width is —
        // a photo or, later, an illustrated alphabet card needs the
        // same frame at every breakpoint.
        aspectRatio: '1 / 1',
        background: resolved ? PHOTO_BG : WARM_STONE,
        // Declared here so the initial below can size itself against
        // this square. It was previously on the span itself, which
        // made the span its own container and left `cqw` measuring
        // the wrong box.
        containerType: 'inline-size',
      }}
    >
      {resolved ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={resolved}
          // The name is already the card's heading directly below, so
          // repeating it here would have a screen reader say it twice.
          alt=""
          aria-hidden="true"
          onError={() => setFailed(true)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <span
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center font-serif"
          style={{
            color: INK,
            // Scales with the square rather than a breakpoint, so the
            // initial keeps its proportions whether the card is 296px
            // wide on a desktop or the full width of a phone.
            fontSize: 'clamp(2.25rem, 30cqw, 4rem)',
            letterSpacing: '0.01em',
          }}
        >
          {initialFor(name)}
        </span>
      )}
    </div>
  )
}
