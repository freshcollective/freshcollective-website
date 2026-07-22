import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getAdminCollectives, type AdminCollectiveRow, type AdminCollectiveHealth } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'

/**
 * Minimal World Management view of a single Collective.
 *
 * Permission philosophy — read this before adding controls.
 * ────────────────────────────────────────────────────────
 * Creators build and manage their Collectives. World Management oversees
 * the health and safety of the platform. Those are separate concerns and
 * they use separate surfaces.
 *
 * Consequences enforced here:
 *   - This page does NOT link into Creator Studio. A caretaker who needs
 *     to change something inside a Collective goes through an explicit,
 *     purpose-built, auditable admin control — not the creator's own
 *     workspace masquerading as an admin tool.
 *   - This page does NOT currently link into the member-facing
 *     /spaces/{slug} experience either. That route treats platform
 *     admins as moderators (community/page.tsx grants pin/edit/delete
 *     to `role === 'admin'` without checking membership) and bypasses
 *     paywalls for admins (spaces/routes.py:_compute_pathway_access).
 *     A safe read-only "admin preview" mode needs to be built on the
 *     platform side before this page can offer that affordance.
 *
 * Data source: reuses `getAdminCollectives()` and finds the row by slug.
 * That's O(n) in memory but every field the page needs is already
 * derived and batched by the list endpoint (Location artwork, health,
 * activity phrase). When the platform grows past a few dozen live
 * collectives, add a dedicated single-collective admin endpoint.
 */

const INK        = '#0C1826'
const INK_MUTED  = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER = 'rgba(12, 24, 38, 0.42)'
const CARD_BG    = '#FFFFFF'
const CARD_BORDER = '1px solid #E7EEF0'
const CARD_SHADOW = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'

const HEALTH: Record<AdminCollectiveHealth, { dot: string; label: string }> = {
  healthy:         { dot: '#22a598', label: 'Healthy' },
  quiet:           { dot: '#d4b048', label: 'Quiet' },
  needs_attention: { dot: '#d66057', label: 'Needs attention' },
}

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

// ---------------------------------------------------------------------------

export default async function AdminCollectiveDetailPage({
  params,
}: {
  params: Promise<{ slug: string }>
}) {
  const { slug } = await params
  const rows = await getAdminCollectives()
  const row = rows.find((r) => r.slug === slug)
  if (!row) notFound()

  const hero = resolveMediaUrl(row.location_hero_artwork_url ?? row.cover_image_url)
  const healthConfig = HEALTH[row.health] ?? HEALTH.healthy

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
      {/* Back to Collectives */}
      <Link
        href="/admin/collectives"
        className="mb-6 inline-flex items-center gap-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-70"
        style={{ color: INK_MUTED }}
      >
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back to Collectives
      </Link>

      {/* Hero */}
      <Hero row={row} imageUrl={hero} />

      {/* Body: pulse card + review card (currently no safe actions) */}
      <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <PulseCard row={row} healthConfig={healthConfig} />
        <ReviewCard />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function Hero({ row, imageUrl }: { row: AdminCollectiveRow; imageUrl: string | null }) {
  if (!imageUrl) {
    return (
      <header>
        {row.location_name && (
          <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.16em]" style={{ color: INK_SOFTER }}>
            {row.location_name}
          </p>
        )}
        <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
          {row.name}
        </h1>
        {row.creator_name && (
          <p className="mt-2 text-[15px]" style={SERIF_ITALIC}>
            by {row.creator_name}
          </p>
        )}
      </header>
    )
  }
  return (
    <header
      className="relative overflow-hidden rounded-3xl"
      style={{ height: 'clamp(200px, 34vw, 280px)', boxShadow: '0 10px 40px rgba(12, 24, 38, 0.10)' }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={imageUrl}
        alt=""
        className="absolute inset-0 h-full w-full"
        style={{ objectFit: 'cover' }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(to top, rgba(8, 18, 30, 0.75) 0%, rgba(8, 18, 30, 0.42) 30%, rgba(8, 18, 30, 0.10) 60%, rgba(8, 18, 30, 0) 82%)',
        }}
      />
      <div className="relative flex h-full w-full items-end p-7 md:p-10">
        <div className="max-w-[720px]">
          {row.location_name && (
            <p
              className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.20em]"
              style={{ color: 'rgba(255, 255, 255, 0.82)', textShadow: '0 1px 8px rgba(0,0,0,0.45)' }}
            >
              {row.location_name}
            </p>
          )}
          <h1
            className="font-serif text-[30px] leading-tight md:text-[42px]"
            style={{
              // Inline colour overrides the base `h1 { color: var(--color-navy-950) }`
              // in globals.css which would otherwise beat Tailwind's `text-white`
              // utility on element specificity.
              color: '#FFFFFF',
              textShadow: '0 2px 18px rgba(0, 0, 0, 0.55), 0 1px 3px rgba(0, 0, 0, 0.6)',
            }}
          >
            {row.name}
          </h1>
          {row.creator_name && (
            <p
              className="mt-2 text-[14px] italic md:text-[15px]"
              style={{
                color: 'rgba(255, 255, 255, 0.92)',
                fontFamily: 'Georgia, serif',
                textShadow: '0 1px 10px rgba(0, 0, 0, 0.5)',
              }}
            >
              by {row.creator_name}
            </p>
          )}
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------

function PulseCard({
  row, healthConfig,
}: { row: AdminCollectiveRow; healthConfig: { dot: string; label: string } }) {
  const facts: { label: string; value: React.ReactNode }[] = [
    {
      label: 'Members',
      value: (
        <span className="font-serif text-[28px] leading-none" style={{ color: INK }}>
          {row.member_count.toLocaleString('en-AU')}
        </span>
      ),
    },
    {
      label: 'Health',
      value: (
        <span className="inline-flex items-center gap-2 text-[15px]" style={{ color: INK }}>
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: healthConfig.dot }} aria-hidden />
          {healthConfig.label}
        </span>
      ),
    },
    {
      label: 'Activity',
      value: <span className="text-[15px]" style={{ color: INK }}>{row.activity_phrase}</span>,
    },
    {
      label: 'Status',
      value: <span className="text-[15px] capitalize" style={{ color: INK }}>{row.status}</span>,
    },
  ]

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

// ---------------------------------------------------------------------------

// A dedicated caretaker preview of the member-facing experience needs to
// be built before this card can offer a "View member experience" link.
// See the permission-philosophy comment at the top of this file for what
// makes the current /spaces/{slug} route unsafe for admin drop-in.
function ReviewCard() {
  return (
    <section
      className="rounded-2xl px-6 py-5 md:px-7 md:py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <h2 className="mb-3 font-serif text-[20px] leading-tight" style={{ color: INK }}>
        Review
      </h2>
      <p className="text-[13.5px] leading-relaxed" style={{ color: INK_MUTED }}>
        A safe, read-only preview of the member experience is not yet
        available from World Management. Purpose-built moderation and
        support actions will appear here when they exist.
      </p>
    </section>
  )
}
