'use client'

import { resolveMediaUrl } from '@/lib/api'
import StepShell from '../StepShell'
import type { DraftData, LocationOption } from '@/lib/build-your-collective/types'

export type OpenDestination = 'world_builders' | 'creator_studio'

interface Props {
  draft: DraftData
  location: LocationOption | null
  onOpen: (destination?: OpenDestination) => void
  onBack: () => void
  opening: boolean
  error: string | null
  /** Copy tuning — the same reveal is used for create and edit modes. */
  mode: 'create' | 'change-location' | 'edit-identity'
}

interface Promise {
  emoji: string
  text: string
}

const PROMISES: Promise[] = [
  { emoji: '🌱', text: 'Welcome members' },
  { emoji: '📖', text: 'Tell your story' },
  { emoji: '🧭', text: 'Create meaningful pathways' },
  { emoji: '🤝', text: 'Host gatherings' },
  { emoji: '💬', text: 'Build genuine community' },
]

/**
 * The final wizard step — a single completion screen.
 *
 * Create mode is the emotional peak of the ritual: the Location's
 * artwork, the collective's name, the whisper that it has come to
 * life, and — in the same breath — the invitation into World Builders
 * or straight into Creator Studio. Either primary or secondary CTA
 * performs the POST /open action exactly once.
 *
 * Edit modes (change-location, edit-identity) retain the simpler
 * reveal: artwork + name + identity + welcome message + Save.
 */
export default function ConfirmationStep({
  draft, location, onOpen, onBack, opening, error, mode,
}: Props) {
  const isEdit = mode !== 'create'
  const name = draft.name?.trim() || 'Your collective'
  const artworkUrl = resolveMediaUrl(location?.hero_artwork_url ?? undefined)

  return (
    <StepShell stepIndex={7} spacious onBack={onBack}>
      <div className="mx-auto flex max-w-[720px] flex-col items-center text-center">
        {/* Hero — the Location's curated Atlas artwork.
            Sized to match (and slightly exceed) the onboarding hero
            band so the completion screen reads as the culmination of
            the ritual, not a summary card. */}
        <div
          className="w-full overflow-hidden rounded-3xl"
          style={{
            maxWidth: 720,
            aspectRatio: '3 / 2',
            boxShadow: '0 28px 72px rgba(12, 24, 38, 0.12), 0 6px 20px rgba(12, 24, 38, 0.06)',
            border: '1px solid rgba(12, 24, 38, 0.05)',
            background: '#F4F7F6',
          }}
        >
          {artworkUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={artworkUrl}
              alt={location?.name ?? name}
              style={{
                width: '100%', height: '100%',
                objectFit: 'cover', objectPosition: 'center', display: 'block',
              }}
            />
          ) : (
            <ArtworkPlaceholder label={location?.name ?? name} />
          )}
        </div>

        {isEdit
          ? <EditReveal draft={draft} name={name} />
          : <CreateArrival name={name} />}

        {/* Divider */}
        <div
          className="mt-14 h-[2px] w-14 rounded-full"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, #D4B048 100%)' }}
          aria-hidden="true"
        />

        {isEdit
          ? <EditFooter opening={opening} onOpen={() => onOpen()} error={error} />
          : <CreateNext opening={opening} onOpen={onOpen} error={error} />}
      </div>
    </StepShell>
  )
}

// ---------------------------------------------------------------------------
// Create mode — the emotional arrival + invitation into World Builders
// ---------------------------------------------------------------------------

function CreateArrival({ name }: { name: string }) {
  return (
    <>
      <h1
        className="mt-10 font-serif text-[28px] leading-[1.2] md:text-[36px]"
        style={{ color: '#0C1826' }}
      >
        Welcome to {name}.
      </h1>
      <p
        className="mt-3 text-[15px] italic leading-relaxed"
        style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
      >
        Your collective has come to life.
      </p>
    </>
  )
}

function CreateNext({
  opening, onOpen, error,
}: {
  opening: boolean
  onOpen: (destination: OpenDestination) => void
  error: string | null
}) {
  return (
    <>
      <p
        className="mt-14 font-serif text-[22px] leading-tight md:text-[26px]"
        style={{ color: '#0C1826' }}
      >
        Welcome to World Builders.
      </p>
      <p
        className="mx-auto mt-5 max-w-[520px] text-[15px] italic leading-relaxed"
        style={{ color: 'rgba(12, 24, 38, 0.68)', fontFamily: 'Georgia, serif' }}
      >
        This is where you&rsquo;ll learn to shape your collective into a
        place people love to return to.
      </p>

      <p
        className="mt-12 text-[11px] font-semibold uppercase tracking-[0.28em]"
        style={{ color: 'rgba(12, 24, 38, 0.55)' }}
      >
        Together, we&rsquo;ll explore how to
      </p>

      <ul className="mx-auto mt-6 flex max-w-[380px] flex-col gap-3 text-left">
        {PROMISES.map((p) => (
          <li key={p.text} className="flex items-center gap-3">
            <span
              className="shrink-0 text-[17px] leading-none"
              aria-hidden="true"
            >
              {p.emoji}
            </span>
            <span
              className="text-[14px] leading-snug"
              style={{ color: 'rgba(12, 24, 38, 0.78)' }}
            >
              {p.text}
            </span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() => onOpen('world_builders')}
        disabled={opening}
        className="mt-16 rounded-full px-8 py-3.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        style={{
          background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
          letterSpacing: '0.08em',
        }}
      >
        {opening ? 'Opening your collective…' : 'Begin in World Builders →'}
      </button>

      <button
        type="button"
        onClick={() => onOpen('creator_studio')}
        disabled={opening}
        className="mt-8 text-[13px] font-medium transition-opacity hover:opacity-70 disabled:opacity-50"
        style={{ color: 'rgba(12, 24, 38, 0.55)' }}
      >
        Enter Creator Studio →
      </button>

      {error && (
        <p className="mt-6 text-[13px]" style={{ color: '#A64526' }}>
          {error}
        </p>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Edit modes — the simpler reveal (change-location / edit-identity)
// ---------------------------------------------------------------------------

function EditReveal({ draft, name }: { draft: DraftData; name: string }) {
  const identity = draft.identity_statement?.trim() || null
  const welcome = draft.welcome_message?.trim() || null

  return (
    <>
      <h1 className="mt-10 font-serif text-[32px] leading-[1.15] md:text-[40px]" style={{ color: '#0C1826' }}>
        {name}
      </h1>
      {identity && (
        <p
          className="mx-auto mt-4 max-w-[520px] text-[16px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.72)', fontFamily: 'Georgia, serif' }}
        >
          {identity}
        </p>
      )}
      {welcome && (
        <p
          className="mx-auto mt-8 max-w-[540px] text-[14.5px] leading-[1.7] italic"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          {welcome}
        </p>
      )}
    </>
  )
}

function EditFooter({
  opening, onOpen, error,
}: {
  opening: boolean
  onOpen: () => void
  error: string | null
}) {
  return (
    <>
      <div className="mt-10">
        <p className="font-serif text-[22px] leading-tight md:text-[26px]" style={{ color: '#0C1826' }}>
          Your collective is ready.
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
        {opening ? 'Saving…' : 'Save your collective'}
      </button>

      {error && (
        <p className="mt-4 text-[13px]" style={{ color: '#A64526' }}>
          {error}
        </p>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Fallback placeholder when no Location artwork is available
// ---------------------------------------------------------------------------

function ArtworkPlaceholder({ label }: { label: string }) {
  return (
    <svg
      viewBox="0 0 400 260"
      preserveAspectRatio="xMidYMid slice"
      className="h-full w-full"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="conf-ph" cx="0.5" cy="0.5" r="0.65">
          <stop offset="0%" stopColor="#E5F0EF" />
          <stop offset="60%" stopColor="#F4F7F6" />
          <stop offset="100%" stopColor="#FBFDFC" />
        </radialGradient>
      </defs>
      <rect width="400" height="260" fill="url(#conf-ph)" />
      <text
        x="200" y="140" textAnchor="middle"
        fill="rgba(12,24,38,0.45)" fontFamily="Georgia, serif"
        fontStyle="italic" fontSize="16"
      >
        {label}
      </text>
    </svg>
  )
}
