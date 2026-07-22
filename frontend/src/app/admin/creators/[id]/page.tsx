import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getAdminCreators, type AdminCreatorRow, type AdminCreatorHealth } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import { AvatarPortrait } from '../CreatorsShell'
import ContactCard from './ContactCard'

/**
 * World Management view of a single Creator.
 *
 * Permission philosophy — same as /admin/collectives/{slug}. Read this
 * before adding controls.
 * ────────────────────────────────────────────────────────────────────
 * Creators own and manage their Collectives. World Management observes
 * and supports. Intervention should be explicit, purpose-built and
 * auditable — not a shortcut through the creator's own workspace.
 *
 * Consequences enforced here:
 *   - No link into Creator Studio.
 *   - No "log in as" / impersonation.
 *   - No plan editing (that lives on Creator Plans).
 *   - No moderation actions (that lives on Community Care).
 *   - No caretaker notes yet — needs a real product decision about
 *     whether the creator can see them and how they're audited.
 *   - The Contact card offers copy-to-clipboard and mailto: only; the
 *     caretaker composes their own message.
 *
 * Data source: reuses `getAdminCreators()` and finds the row by id.
 * Same rationale as /admin/collectives/{slug} — every field the page
 * needs is already derived and batched by the list endpoint.
 */

const INK        = '#0C1826'
const INK_MUTED  = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const CARD_BG    = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'

const HEALTH: Record<AdminCreatorHealth, { dot: string; label: string }> = {
  flourishing:   { dot: '#22a598', label: 'Flourishing' },
  new:           { dot: '#4c78d4', label: 'New' },
  quiet:         { dot: '#d4b048', label: 'Quiet' },
  needs_support: { dot: '#d66057', label: 'Needs support' },
}

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

const SMALL_NUMBER_WORDS = [
  'zero', 'one', 'two', 'three', 'four', 'five',
  'six', 'seven', 'eight', 'nine', 'ten',
] as const

function spellCount(n: number): string {
  const word = SMALL_NUMBER_WORDS[n]
  if (!word) return String(n)
  return word.charAt(0).toUpperCase() + word.slice(1)
}

// ---------------------------------------------------------------------------

export default async function CreatorDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const rows = await getAdminCreators()
  const row = rows.find((r) => r.id === id)
  if (!row) notFound()

  const health = HEALTH[row.health] ?? HEALTH.new

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      <Link
        href="/admin/creators"
        className="mb-6 inline-flex items-center gap-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-70"
        style={{ color: INK_MUTED }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back to Creators
      </Link>

      {/* Hero */}
      <header className="flex flex-col items-start gap-6 md:flex-row md:items-center">
        <AvatarPortrait url={resolveMediaUrl(row.avatar_url)} name={row.name ?? row.email} size={112} />
        <div className="min-w-0">
          <h1 className="font-serif text-[30px] leading-tight md:text-[40px]" style={{ color: INK }}>
            {row.name ?? row.email}
          </h1>
          <p className="mt-2 text-[15px]" style={SERIF_ITALIC}>
            Building since {monthYear(row.created_at)}
          </p>
        </div>
      </header>

      {/* Pulse + Contact */}
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PulseCard row={row} healthLabel={health.label} healthDot={health.dot} />
        <ContactCard email={row.email} name={row.name} />
      </div>

      {/* The world they've built */}
      <section className="mt-10">
        <h2 className="mb-2 font-serif text-[22px] leading-tight md:text-[24px]" style={{ color: INK }}>
          The world they've built
        </h2>
        <p className="mb-5 max-w-[560px] text-[13.5px] leading-relaxed" style={SERIF_ITALIC}>
          {row.collectives.length === 0
            ? 'No collectives yet — this is a builder still finding their first place.'
            : row.collectives.length === 1
              ? 'One collective, tended by them.'
              : `${spellCount(row.collectives.length)} collectives are flourishing in the world.`}
        </p>
        {row.collectives.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {row.collectives.map((c) => {
              const cover = resolveMediaUrl(c.location_hero_artwork_url)
              return (
                <Link
                  key={c.id}
                  href={`/admin/collectives/${c.slug}`}
                  className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5"
                  style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                >
                  <div className="relative w-full overflow-hidden" style={{ aspectRatio: '5 / 3', background: '#F5F8FA' }}>
                    {cover && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={cover}
                        alt=""
                        className="absolute inset-0 h-full w-full"
                        style={{ objectFit: 'cover' }}
                      />
                    )}
                  </div>
                  <div className="p-4">
                    {c.location_name && (
                      <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.16em]" style={{ color: INK_SOFTER }}>
                        {c.location_name}
                      </p>
                    )}
                    <p className="font-serif text-[18px] leading-tight" style={{ color: INK }}>
                      {c.name}
                    </p>
                  </div>
                </Link>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------

function PulseCard({
  row, healthLabel, healthDot,
}: { row: AdminCreatorRow; healthLabel: string; healthDot: string }) {
  const facts: { label: string; value: React.ReactNode }[] = [
    {
      label: 'Members reached',
      value: (
        <span className="font-serif text-[28px] leading-none" style={{ color: INK }}>
          {row.total_members_reached.toLocaleString('en-AU')}
        </span>
      ),
    },
    {
      label: 'Health',
      value: (
        <span className="inline-flex items-center gap-2 text-[15px]" style={{ color: INK }}>
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: healthDot }} aria-hidden />
          {healthLabel}
        </span>
      ),
    },
    {
      label: 'Activity',
      value: <span className="text-[15px]" style={{ color: INK }}>{row.activity_phrase}</span>,
    },
    {
      label: 'Published collectives',
      value: <span className="text-[15px]" style={{ color: INK }}>{row.published_collective_count}</span>,
    },
  ]
  // Draft row only appears when there's something to say — a caretaker
  // shouldn't have to read "0 drafts" on every profile.
  if (row.draft_collective_count > 0) {
    facts.push({
      label: 'Draft collectives',
      value: <span className="text-[15px]" style={{ color: INK }}>{row.draft_collective_count}</span>,
    })
  }

  return (
    <section
      className="rounded-2xl px-6 py-5 md:px-7 md:py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <h2 className="mb-4 font-serif text-[20px] leading-tight" style={{ color: INK }}>
        Pulse
      </h2>
      <dl className="divide-y" style={{ borderColor: 'rgba(12, 24, 38, 0.06)' }}>
        {facts.map((f) => (
          <div key={f.label} className="flex items-center justify-between py-3.5 first:pt-0 last:pb-0">
            <dt className="text-[12px] font-semibold uppercase tracking-[0.14em]" style={{ color: INK_SOFTER }}>
              {f.label}
            </dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

function monthYear(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const name = MONTHS[d.getMonth()]
  const nowYear = new Date().getFullYear()
  return d.getFullYear() === nowYear ? name : `${name} ${d.getFullYear()}`
}
