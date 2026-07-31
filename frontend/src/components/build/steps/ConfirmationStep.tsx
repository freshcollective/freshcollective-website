'use client'

import { resolveMediaUrl } from '@/lib/api'
import StepShell from '../StepShell'
import type { DraftData, LocationOption } from '@/lib/build-your-collective/types'

interface Props {
  draft: DraftData
  location: LocationOption | null
  onOpen: () => void
  onBack: () => void
  opening: boolean
  error: string | null
  /** Copy tuning — the same reveal is used for create and edit modes. */
  mode: 'create' | 'change-location' | 'edit-identity'
}

/**
 * The reveal — a memorable arrival.
 *
 * Hero: the chosen Location's curated Atlas artwork. Below: the collective's
 * name, its identity statement, its welcome message (if written), the Atlas
 * passage, and the invitation button. No procedural artwork, no upload
 * status, no preview notes.
 */
export default function ConfirmationStep({
  draft, location, onOpen, onBack, opening, error, mode,
}: Props) {
  const name = draft.name?.trim() || 'Your collective'
  const identity = draft.identity_statement?.trim() || null
  const welcome = draft.welcome_message?.trim() || null
  const artworkUrl = resolveMediaUrl(location?.hero_artwork_url ?? undefined)

  const isEdit = mode !== 'create'
  const buttonLabel = isEdit ? 'Save your collective' : 'Open your collective'

  return (
    <StepShell stepIndex={7} spacious onBack={onBack}>
      <div className="mx-auto flex max-w-[760px] flex-col items-center pt-2 text-center">
        {/* Hero — the Location's curated Atlas artwork */}
        <div
          className="mb-10 w-full overflow-hidden rounded-3xl"
          style={{
            maxWidth: 680,
            aspectRatio: '3 / 2',
            boxShadow: '0 24px 60px rgba(12, 24, 38, 0.10), 0 4px 16px rgba(12, 24, 38, 0.05)',
            border: '1px solid rgba(12, 24, 38, 0.05)',
            background: '#F4F7F6',
          }}
        >
          {artworkUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={artworkUrl}
              alt={location?.name ?? name}
              style={{ width: '100%', height: '100%', objectFit: 'cover', objectPosition: 'center', display: 'block' }}
            />
          ) : (
            <ArtworkPlaceholder label={location?.name ?? name} />
          )}
        </div>

        {/* Name */}
        <h2 className="font-serif text-[32px] leading-[1.15] md:text-[40px]" style={{ color: '#0C1826' }}>
          {name}
        </h2>

        {/* Identity statement */}
        {identity && (
          <p
            className="mx-auto mt-4 max-w-[520px] text-[16px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
          >
            {identity}
          </p>
        )}

        {/* Teal → gold accent line */}
        <div
          className="mt-8 h-[2px] w-16 rounded-full"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, #D4B048 100%)' }}
          aria-hidden="true"
        />

        {/* Welcome message — quieter, shown when the creator wrote one */}
        {welcome && (
          <p
            className="mx-auto mt-8 max-w-[540px] text-[14.5px] leading-[1.7] italic"
            style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
          >
            {welcome}
          </p>
        )}

        {/* Atlas passage */}
        <div className="mt-10">
          <p className="font-serif text-[22px] leading-tight md:text-[26px]" style={{ color: '#0C1826' }}>
            Your collective is ready.
          </p>
          <p
            className="mt-1.5 text-[15px] italic"
            style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
          >
            Let&apos;s welcome people home.
          </p>
        </div>

        <button
          type="button"
          onClick={onOpen}
          disabled={opening}
          className="mt-10 rounded-full px-8 py-3.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{
            background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
            letterSpacing: '0.08em',
          }}
        >
          {opening ? 'Opening…' : buttonLabel}
        </button>

        {error && (
          <p className="mt-4 text-[13px]" style={{ color: '#A64526' }}>
            {error}
          </p>
        )}
      </div>
    </StepShell>
  )
}

function ArtworkPlaceholder({ label }: { label: string }) {
  return (
    <svg viewBox="0 0 400 260" preserveAspectRatio="xMidYMid slice" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id="conf-ph" cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%" stopColor="#E5F0EF" />
          <stop offset="60%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="400" height="260" fill="url(#conf-ph)" />
      <text x="200" y="140" textAnchor="middle" fill="rgba(12,24,38,0.45)" fontFamily="Georgia, serif" fontStyle="italic" fontSize="16">
        {label}
      </text>
    </svg>
  )
}
