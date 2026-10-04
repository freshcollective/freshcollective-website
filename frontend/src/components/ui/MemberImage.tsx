/**
 * The picture beside a member's name, wherever that appears.
 *
 * The server has already decided which of four things this is — the
 * member's own photo, the Fresh Collective card for their initial, the
 * neutral card, or the letter alone — so this component renders what it
 * is told rather than re-deriving the ladder. That is the point: every
 * surface used to make its own decision about avatars and they did not
 * agree.
 *
 * Square at every size, because a photo and an illustrated card have to
 * occupy the same frame. Decorative throughout: the member's name is
 * always adjacent in the markup, so announcing the image as well would
 * read it twice.
 */

'use client'

import { useState } from 'react'
import { resolveMediaUrl } from '@/lib/api'
import type { MemberImage as MemberImageData } from '@/types/platform'

/** Warm stone, identical for everybody. Deliberately not tinted by
 *  anything about the member — a portrait that varies by category is a
 *  badge for a taxonomy nobody asked about. */
const WARM_STONE =
  'radial-gradient(ellipse at 28% 26%, rgba(255,255,255,0.55), transparent 60%),' +
  'linear-gradient(155deg, #EFEDE7 0%, #D8D3CA 100%)'
const INK = '#2E3B47'
const PHOTO_BG = '#F1EFEB'

export default function MemberImage({
  image,
  className = '',
  rounded = 'rounded-none',
}: {
  image: MemberImageData
  className?: string
  /** Callers choose the shape: cards use a square, inline rows a circle. */
  rounded?: string
}) {
  // How many rungs of the ladder this client has had to step down.
  // The server picked the top one it could see; only a photo can still
  // fail after that, and when it does there is a card waiting below it.
  // Counting rather than a boolean because stepping down can happen
  // twice: a broken photo, and then artwork that is itself unreachable.
  const [stepsDown, setStepsDown] = useState(0)

  const rungs = [image.url, image.fallback_url].filter(
    (u): u is string => !!u,
  )
  const current = rungs[stepsDown] ?? null
  const url = resolveMediaUrl(current ?? undefined)

  // A photo is cropped to the frame; a card is drawn for it and must
  // not be. Once the photo has failed, what is showing is a card —
  // so the crop has to step down with it.
  const isPhoto = image.kind === 'photo' && stepsDown === 0

  return (
    <div
      className={`relative overflow-hidden ${rounded} ${className}`}
      style={{
        aspectRatio: '1 / 1',
        background: url && isPhoto ? PHOTO_BG : WARM_STONE,
        // Lets the letter below size itself against this square rather
        // than against a breakpoint, so it holds its proportions at
        // every width the frame is used at.
        containerType: 'inline-size',
      }}
    >
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt=""
          aria-hidden="true"
          // Keyed on the URL so React remounts the element when the
          // source changes; without it the browser can keep the failed
          // image and never request the fallback.
          key={url}
          onError={() => setStepsDown((n) => n + 1)}
          className={`absolute inset-0 h-full w-full ${isPhoto ? 'object-cover' : 'object-contain'}`}
        />
      ) : (
        <span
          aria-hidden="true"
          className="absolute inset-0 flex items-center justify-center font-serif"
          style={{
            color: INK,
            fontSize: 'clamp(0.95rem, 30cqw, 4rem)',
            letterSpacing: '0.01em',
          }}
        >
          {/* A middle dot rather than "?" — a member with no Latin
              initial has not failed at anything. */}
          {image.initial ?? '·'}
        </span>
      )}
    </div>
  )
}
