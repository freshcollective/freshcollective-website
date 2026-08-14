import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getSpace, getSpaceEvent, getSpaceEventAboutBlocks, getMe } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import type { EventDetail, PathwayAboutBlock } from '@/types/platform'
import { AboutBlockRenderer } from '@/components/spaces/AboutBlockRenderer'
import { countdownLabel, formatGatheringFullDate, formatGatheringTime } from '@/lib/dateTime'
import GatheringBookingClient from '@/components/spaces/GatheringBookingClient'
import GatheringTicketPurchaseClient from '@/components/spaces/GatheringTicketPurchaseClient'
import {
  gatheringIcon, gatheringLabel, gatheringDescription,
  attendanceFormatLabel,
} from '@/lib/gatheringTypes'
import {
  paletteHex,
  contrastText,
  darkenHex,
  rgbaFromHex,
  type CollectivePaletteMeta,
} from '@/lib/collectivePalette'

interface Props {
  params: Promise<{ slug: string; eventId: string }>
}

const LOCATION_LABEL: Record<string, string> = {
  zoom: 'Live — Zoom',
  in_person: 'In Person',
  async_recorded: 'Recorded Session',
}

type EventState = 'upcoming' | 'live' | 'past-replay' | 'past-no-replay'

function getEventState(event: EventDetail): EventState {
  const now = new Date()
  const start = new Date(event.starts_at)
  const end = event.ends_at
    ? new Date(event.ends_at)
    : new Date(start.getTime() + 60 * 60 * 1000)

  if (now < start) return 'upcoming'
  if (now >= start && now <= end) return 'live'
  return event.recording_url ? 'past-replay' : 'past-no-replay'
}

function formatDuration(startsAt: string, endsAt: string): string {
  const mins = Math.round(
    (new Date(endsAt).getTime() - new Date(startsAt).getTime()) / 60000,
  )
  if (mins < 60) return `${mins} min`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `${h} hr ${m} min` : `${h} hr`
}

function calendarUrls(event: EventDetail) {
  const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z'
  const start = new Date(event.starts_at)
  const end = event.ends_at
    ? new Date(event.ends_at)
    : new Date(start.getTime() + 60 * 60 * 1000)

  const googleParams = new URLSearchParams({
    action: 'TEMPLATE',
    text: event.title,
    dates: `${fmt(start)}/${fmt(end)}`,
    details: event.description ?? '',
    location: event.location_url ?? '',
  })
  const google = `https://calendar.google.com/calendar/render?${googleParams}`

  const outlookParams = new URLSearchParams({
    path: '/calendar/action/compose',
    rru: 'addevent',
    startdt: start.toISOString(),
    enddt: end.toISOString(),
    subject: event.title,
    body: event.description ?? '',
    location: event.location_url ?? '',
  })
  const outlook = `https://outlook.live.com/calendar/0/action/compose?${outlookParams}`

  return { google, outlook }
}

// State badges. Non-semantic states (Upcoming) read from the
// Collective palette via CSS vars; semantic states (Live/Cancelled)
// keep their fixed meaning-colour so the visual cue remains constant
// across every Collective — a red "Cancelled" chip must not become
// palette-primary on The Grove.
const STATE_BADGE: Record<EventState | 'cancelled', { label: string; bg: string; color: string }> = {
  upcoming:         { label: 'Upcoming',           bg: 'var(--fc-accent-soft, rgba(56,160,158,0.10))', color: 'var(--fc-accent, #0f766e)' },
  live:             { label: 'Happening now',       bg: 'rgba(22,163,74,0.10)',  color: '#15803d' },
  'past-replay':    { label: 'Replay available',    bg: 'rgba(21,36,54,0.08)',   color: '#334155' },
  'past-no-replay': { label: 'Gathering ended',     bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
  'cancelled':      { label: 'Cancelled',           bg: 'rgba(239,68,68,0.08)',  color: '#b91c1c' },
}

// ---------------------------------------------------------------------------
// Small presentational primitives for the redesigned page
// ---------------------------------------------------------------------------

/** Simple stroke-icon set — matches the style already used in
 *  ``@/components/platform/*`` (inline SVGs, no external icon
 *  library). Each icon renders at 16 × 16 by default. */

function IconCalendar() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect x="3" y="4.5" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M3 8h14" stroke="currentColor" strokeWidth="1.4" />
      <path d="M7 3v3M13 3v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.4" />
      <path d="M10 5.5V10l2.75 1.75" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function IconMapPin() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="M10 17s5.5-4.5 5.5-9a5.5 5.5 0 10-11 0c0 4.5 5.5 9 5.5 9z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <circle cx="10" cy="8" r="2" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  )
}

function IconMonitor() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <rect x="2.5" y="4" width="15" height="10" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M7 17h6M10 14v3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function IconUser() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="7" r="3" stroke="currentColor" strokeWidth="1.4" />
      <path d="M4 17c1.2-3 3.5-4.5 6-4.5s4.8 1.5 6 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

function IconUsers() {
  return (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="8" cy="7.5" r="2.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M3.5 16.5c.8-2.4 2.5-3.6 4.5-3.6s3.7 1.2 4.5 3.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="14" cy="6.5" r="2" stroke="currentColor" strokeWidth="1.4" />
      <path d="M13 12.7c.4-.1.8-.15 1.2-.15 1.7 0 3.1 1 3.8 2.9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

/** One row in the practical-details block — icon + label + value.
 *  All rows share one bordered container so we avoid the "grid of
 *  equal-weight boxes" look that made the previous pass feel
 *  dashboard-y. */
interface DetailRowPalette {
  /** Background of the icon chip. */
  iconBg: string
  /** Icon stroke colour. */
  iconFg: string
  /** Small "DATE" / "TIME" label above the value. */
  eyebrow: string
  /** Value text — needs to sit legibly on the panel surface. */
  value: string
  /** Secondary text (secondary lines, hints). */
  secondary: string
}

function DetailRow({
  icon, label, palette, children,
}: {
  icon: React.ReactNode
  label: string
  palette: DetailRowPalette
  children: React.ReactNode
}) {
  return (
    <div className="flex gap-3">
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
        style={{ background: palette.iconBg, color: palette.iconFg }}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p
          className="text-[10.5px] font-semibold uppercase tracking-[0.14em]"
          style={{ color: palette.eyebrow }}
        >
          {label}
        </p>
        <div
          className="mt-0.5 text-[14px] leading-snug"
          style={{ color: palette.value }}
        >
          {children}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

export default async function EventDetailPage({ params }: Props) {
  const { slug, eventId } = await params
  const [space, event, aboutBlocks, me]: [
    Awaited<ReturnType<typeof getSpace>>,
    Awaited<ReturnType<typeof getSpaceEvent>>,
    PathwayAboutBlock[],
    Awaited<ReturnType<typeof getMe>>,
  ] = await Promise.all([
    getSpace(slug),
    getSpaceEvent(slug, eventId),
    getSpaceEventAboutBlocks(slug, eventId),
    getMe(),
  ])

  if (!event) notFound()

  const isAuthenticated = !!me
  const loginHref = `/login?next=/spaces/${slug}/events/${eventId}`

  const timezone = space?.timezone ?? 'Australia/Melbourne'
  const formatFullDate = (iso: string) => formatGatheringFullDate(iso, timezone)
  const formatTime     = (iso: string) => formatGatheringTime(iso, timezone)

  const isCancelled = event.status === 'cancelled'
  const state = isCancelled ? 'cancelled' as const : getEventState(event)
  const badge = STATE_BADGE[state]
  const locationLabel = event.attendance_format
    ? attendanceFormatLabel(event.attendance_format)
    : (LOCATION_LABEL[event.location_type] ?? event.location_type)
  const typeIcon = gatheringIcon(event.gathering_type)
  const typeLabel = gatheringLabel(event.gathering_type)
  const typeDescription = gatheringDescription(event.gathering_type)
  const { google: googleCalUrl, outlook: outlookCalUrl } = calendarUrls(event)
  const icsUrl = `/api/spaces/${slug}/events/${eventId}/calendar.ics`

  const isPast = state === 'past-replay' || state === 'past-no-replay'
  const countdown = isCancelled || isPast
    ? null
    : countdownLabel(event.starts_at, event.ends_at ?? null)
  const showCountdown = !!countdown && countdown !== 'Ended' && countdown !== 'Live now'
  // Duration string once, so both the hero and the WHEN block can reuse it.
  const durationLabel = event.ends_at ? formatDuration(event.starts_at, event.ends_at) : null

  const placesRemaining = event.spots_remaining
  const isReservedByMe = event.my_booking_status === 'confirmed'
  const isFull = placesRemaining !== null && placesRemaining === 0 && !isReservedByMe

  // Hero cover fallback: Gathering's own thumbnail → parent Series
  // cover → soft gradient. Series children in a bulk-created term
  // (EMBODY sessions) inherit the term identity for free without
  // requiring per-session uploads.
  //
  // Both fields arrive as *relative* URLs (``/api/uploads/...``)
  // from the backend, so they MUST be piped through
  // ``resolveMediaUrl`` to become absolute — the frontend runs on
  // :3000 and the backend on :8000, so a raw src would 404 against
  // the frontend origin and render as an empty gradient.
  // (Fix for the M1 review issue where the inherited Series
  //  cover wasn't appearing on Saturday EMBODY Session — Empowerment.)
  const heroCoverUrl =
    resolveMediaUrl(event.thumbnail_url ?? undefined)
    ?? resolveMediaUrl(event.series_cover_image_url ?? undefined)
    ?? null

  // Where line — one sentence: "In person · South Croydon, VIC" /
  // "Online" / "Hybrid · Yarra Hills". The locality is safe to
  // expose to everyone (see backend ``_derive_venue_locality``);
  // the street address stays behind the attendee gate below.
  const attendanceLabel =
    event.attendance_format === 'in_person' ? 'In person'
    : event.attendance_format === 'hybrid' ? 'Hybrid'
    : 'Online'
  const whereSummary = event.venue_locality
    ? `${attendanceLabel} \u00b7 ${event.venue_locality}`
    : attendanceLabel

  // ── Palette resolution ─────────────────────────────────────
  // Collective palette drives the practical-details panel + the
  // booking-panel eyebrow so a Gathering visibly belongs to its
  // Collective. Falls back to a neutral slate treatment when the
  // Collective has no palette hydrated (older Spaces).
  //
  // Every text/icon colour on the panel derives from a SINGLE picked
  // contrast text (``panelText``) so a dark panel gets white + white
  // at reduced alpha everywhere, and a light panel gets charcoal +
  // charcoal at reduced alpha everywhere. This kills two prior bugs:
  //   1. Eyebrows used to be tinted with the palette's *secondary* hex
  //      (Terracotta secondary = dark purple #5B3D57 → muddy purple
  //      on rust — unreadable).
  //   2. Icon chips on a light palette used to render the icon in
  //      ``primaryHex`` — same colour as the panel bg → invisible.
  // For borderline-light primaries where white text would flunk WCAG
  // on the raw primary, we darken the surface enough that white is
  // safe. Panel remains obviously "this Collective's colour" — just
  // deepened, not neutralised.
  const palette: CollectivePaletteMeta | null = space?.colour_palette ?? null
  const primaryHex = paletteHex('primary', palette) ?? '#0F172A'      // slate-900 fallback
  const accentHex  = paletteHex('accent',  palette) ?? primaryHex

  const panelText = contrastText(primaryHex)        // white for dark/medium; charcoal for light
  const panelOnDark = panelText === '#ffffff'
  // White-text panels: aggressive darken so warm-medium primaries
  // (Terracotta, Honey & Cream, Rose & Sage) reach comfortable WCAG
  // contrast under a small vertical gradient.
  // Dark-text panels: light palette stays as-is so the surface still
  // *reads* as light (Snow & Sky, pale washes).
  const panelBg    = panelOnDark ? darkenHex(primaryHex, 0.15) : primaryHex
  const panelBgTop = panelOnDark ? darkenHex(primaryHex, 0.24) : darkenHex(primaryHex, 0.06)

  const eyebrowColour        = rgbaFromHex(panelText, 0.72)
  const secondaryTextOnPanel = rgbaFromHex(panelText, panelOnDark ? 0.75 : 0.62)
  const iconChipBg           = rgbaFromHex(panelText, panelOnDark ? 0.12 : 0.08)
  const iconChipFg           = rgbaFromHex(panelText, panelOnDark ? 0.90 : 0.75)
  const rowDivider           = rgbaFromHex(panelText, 0.12)
  const detailPalette: DetailRowPalette = {
    iconBg: iconChipBg,
    iconFg: iconChipFg,
    eyebrow: eyebrowColour,
    value: panelText,
    secondary: secondaryTextOnPanel,
  }

  // Booking-panel accent (eyebrow, small links) — always on white.
  const bookingEyebrow = primaryHex

  return (
    <div className="mx-auto w-full max-w-[980px]">

      {/* Back link — prefers the Series page when this Gathering
          belongs to one, so the member returns to context. */}
      <div className="mb-4">
        <Link
          href={
            event.series_slug
              ? `/spaces/${slug}/gathering-series/${event.series_slug}`
              : `/spaces/${slug}/events`
          }
          className="inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-500 transition-colors hover:text-slate-700"
        >
          <span aria-hidden="true">←</span>
          <span>
            {event.series_slug ? `Back to ${event.series_title ?? 'Series'}` : 'Back to Gatherings'}
          </span>
        </Link>
      </div>

      {/* ──────── Compact image-led hero ────────
          Cover image (event → parent Series → gradient fallback)
          + overlay for legibility + the key identity only:
            ▸ title
            ▸ date · time · format
            ▸ Upcoming / Live / Past state
          Series linkage is a chip inside the hero; when the
          Gathering belongs to a Series, the eyebrow reads
          "Part of {series title}" and links to the Series page.
      */}
      <div className="relative mb-6 overflow-hidden rounded-2xl border border-border bg-white shadow-sm">
        {heroCoverUrl ? (
          <div className="relative h-56 w-full overflow-hidden md:h-64">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={heroCoverUrl}
              alt=""
              className="h-full w-full object-cover"
            />
            <div
              aria-hidden="true"
              className="absolute inset-0"
              style={{
                // 5-stop layered scrim — near-opaque under the text
                // block, thick coverage across the middle to defeat
                // busy/high-frequency artwork, still lets the top of
                // the image breathe. Tested visually on light logo
                // covers, warm rust palettes, dark stock. See parallel
                // implementation on the Series hero for the same
                // rationale.
                background:
                  'linear-gradient(to top, rgba(0,0,0,0.86) 0%, rgba(0,0,0,0.70) 22%, rgba(0,0,0,0.50) 46%, rgba(0,0,0,0.32) 72%, rgba(0,0,0,0.20) 100%)',
              }}
            />
            {isCancelled && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                <span className="rounded-full bg-white/90 px-4 py-1.5 text-sm font-semibold text-slate-700">
                  Cancelled
                </span>
              </div>
            )}
            <HeroOverlay
              slug={slug}
              event={event}
              badge={badge}
              state={state}
              countdown={countdown}
              showCountdown={showCountdown}
              locationLabel={locationLabel}
              formatFullDate={formatFullDate}
              formatTime={formatTime}
              typeIcon={typeIcon}
              typeLabel={typeLabel}
              variant="over-image"
            />
          </div>
        ) : (
          // No cover art — plain warm-neutral card. Deliberately not
          // palette-tinted here: the shell is Fresh Collective's, and
          // the Collective palette shows up further down the page on
          // CTAs + sidebar. This keeps the frame calm on Collectives
          // whose palette wouldn't render well as a large soft field.
          <div
            className="relative w-full"
            style={{
              background:
                'linear-gradient(135deg, rgba(15,23,42,0.05) 0%, rgba(15,23,42,0.02) 60%, rgba(255,255,255,0) 100%)',
            }}
          >
            <div className="px-6 pb-6 pt-6 md:px-8">
              <HeroOverlay
                slug={slug}
                event={event}
                badge={badge}
                state={state}
                countdown={countdown}
                showCountdown={showCountdown}
                locationLabel={locationLabel}
                formatFullDate={formatFullDate}
                formatTime={formatTime}
                typeIcon={typeIcon}
                typeLabel={typeLabel}
                variant="on-tint"
              />
            </div>
          </div>
        )}
      </div>

      {/* Two-column layout — booking panel is stacked first on
          mobile (order-1) and second on desktop (order-2), so a
          member on a phone sees the reservation action right
          after the hero. */}
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">

        {/* ── Left column: editorial content ── */}
        <div className="order-2 flex flex-col gap-8 lg:order-1">

          {/* Practical details — palette-branded panel that gives
              the Gathering a strong sense of "belonging to this
              Collective". Background comes from the Collective's
              primary palette hex; ``contrastText`` picks white or
              slate-900 for the value text so any palette works.
              Icons + eyebrows use soft tints of the same primary
              so the panel stays cohesive without extra colours. */}
          <section
            className="rounded-2xl px-6 py-5 shadow-sm md:px-7 md:py-6"
            style={{
              background: `linear-gradient(180deg, ${panelBgTop} 0%, ${panelBg} 100%)`,
              color: panelText,
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2 sm:gap-x-8 sm:gap-y-5">
              <DetailRow icon={<IconCalendar />} label="Date" palette={detailPalette}>
                {formatFullDate(event.starts_at)}
              </DetailRow>
              <DetailRow icon={<IconClock />} label="Time" palette={detailPalette}>
                {formatTime(event.starts_at)}{durationLabel && ` \u00b7 ${durationLabel}`}
              </DetailRow>
              <DetailRow
                icon={event.attendance_format === 'in_person' ? <IconMapPin /> : <IconMonitor />}
                label={event.attendance_format === 'in_person' ? 'Where' : 'Format'}
                palette={detailPalette}
              >
                <div className="space-y-0.5">
                  <p>{whereSummary}</p>
                  {/* Venue name is member-safe (always exposed in
                      the API) — treated as a secondary line for
                      Creators who chose to name their venue. */}
                  {event.attendance_format !== 'online' && event.venue_name && (
                    <p className="text-[12.5px]" style={{ color: detailPalette.secondary }}>
                      {event.venue_name}
                    </p>
                  )}
                  {/* Full street address is attendee-gated on the
                      server — surfaces here only for confirmed
                      attendees + caretakers. */}
                  {event.attendance_format !== 'online' && event.venue_address
                    && event.venue_address !== event.venue_locality && (
                    <p className="text-[12.5px]" style={{ color: detailPalette.secondary }}>
                      {event.venue_address}
                    </p>
                  )}
                  {event.attendance_format !== 'in_person' && event.location_url && (
                    <a
                      href={event.location_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block break-all text-[12.5px] font-semibold underline-offset-2 hover:underline"
                      style={{ color: panelText }}
                    >
                      {event.location_url}
                    </a>
                  )}
                  {!event.location_url
                    && (event.attendance_format === 'online' || event.attendance_format === 'hybrid')
                    && !isPast && (
                    <p className="text-[12.5px] italic" style={{ color: detailPalette.secondary }}>
                      Meeting link shared with attendees before the Gathering.
                    </p>
                  )}
                </div>
              </DetailRow>
              {event.host_name && (
                <DetailRow icon={<IconUser />} label="Hosted by" palette={detailPalette}>
                  {event.host_name}
                </DetailRow>
              )}
              {event.capacity != null && (
                <DetailRow icon={<IconUsers />} label="Places" palette={detailPalette}>
                  {placesRemaining === 0
                    ? 'All places taken'
                    : placesRemaining != null
                      ? `${placesRemaining} of ${event.capacity} remaining`
                      : `${event.capacity} places`}
                </DetailRow>
              )}
            </div>
            {/* Silence the linter for the divider colour we don't
                currently render — kept in scope for a future
                between-row rule if the panel grows. */}
            <span aria-hidden="true" className="hidden" style={{ background: rowDivider }} />
          </section>

          {/* About — three-tier fallback (MF8):
              1. Rich About blocks authored via the Creator About tab
                 render through the shared ``AboutBlockRenderer``.
              2. Legacy short ``event.description`` if no blocks yet.
              3. A one-line italic type description as a final fallback.
              Never combine tiers — only ever one is shown. Access
              instructions remain a separate attendee-only panel below. */}
          <section>
            <div className="mb-3 flex items-center gap-3">
              <span
                aria-hidden="true"
                className="h-[1px] w-8"
                style={{ background: accentHex }}
              />
              <h2 className="font-serif text-[19px] text-navy-900">About this Gathering</h2>
            </div>
            {aboutBlocks.length > 0
              ? (
                <div className="space-y-4">
                  {aboutBlocks.map((b) => (
                    <AboutBlockRenderer key={b.id} block={b} collectivePalette={palette} />
                  ))}
                </div>
              )
              : event.description
                ? (
                  <div className="max-w-[62ch] space-y-3 text-[15px] leading-[1.75] text-navy-900">
                    {event.description.split('\n').filter(Boolean).map((para: string, i: number) => (
                      <p key={i}>{para}</p>
                    ))}
                  </div>
                )
                : (
                  <p className="max-w-[62ch] text-[14.5px] italic leading-relaxed text-slate-600">
                    {typeDescription}
                  </p>
                )
            }
          </section>

          {/* Access / arrival instructions — attendee-only. Kept
              as a tinted note since the content is genuinely
              actionable ("what to do when you arrive"). */}
          {event.access_instructions && (
            <section
              className="rounded-2xl border px-6 py-5"
              style={{
                borderColor: 'var(--fc-accent-line, rgba(56,160,158,0.20))',
                background: 'var(--fc-accent-tint, rgba(56,160,158,0.05))',
              }}
            >
              <p
                className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                {event.attendance_format === 'in_person' ? 'Arrival instructions' : 'Access instructions'}
              </p>
              <div className="space-y-3">
                {event.access_instructions.split('\n').filter(Boolean).map((para: string, i: number) => (
                  <p key={i} className="text-[14px] leading-relaxed text-navy-900">{para}</p>
                ))}
              </div>
            </section>
          )}

          {/* Live / past-replay / past-no-replay actions. */}
          {state === 'live' && (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 px-5 py-4">
              {event.location_url && event.attendance_format !== 'in_person' ? (
                <a
                  href={event.location_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'var(--fc-accent, #0d9488)' }}
                >
                  Join now →
                </a>
              ) : event.attendance_format === 'in_person' ? (
                <p className="text-[13px] text-emerald-900">
                  Happening in person now{event.venue_name ? ` at ${event.venue_name}` : ''}.
                </p>
              ) : (
                <p className="text-[13px] text-emerald-900">Join link will be available shortly.</p>
              )}
            </div>
          )}

          {state === 'past-replay' && event.recording_url && (
            <a
              href={event.recording_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex w-fit items-center rounded-full bg-navy-900 px-5 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-navy-800"
            >
              Watch replay →
            </a>
          )}

          {state === 'past-no-replay' && (
            <p className="text-[13px] italic text-slate-500">
              A replay of this Gathering will be available here once it has been processed.
            </p>
          )}

          {/* Add to calendar — tertiary. One quiet line, no
              bordered box. */}
          {(state === 'upcoming' || state === 'live') && (
            <p className="text-[13px] text-slate-500">
              <span className="mr-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                Add to calendar:
              </span>
              <a
                href={googleCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium transition-opacity hover:opacity-80"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                Google
              </a>
              <span className="mx-1.5 text-slate-300">·</span>
              <a
                href={outlookCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium transition-opacity hover:opacity-80"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                Outlook
              </a>
              <span className="mx-1.5 text-slate-300">·</span>
              <a
                href={icsUrl}
                download
                className="font-medium transition-opacity hover:opacity-80"
                style={{ color: 'var(--fc-accent, #0f766e)' }}
              >
                Download .ics
              </a>
            </p>
          )}
        </div>

        {/* ── Right column: reservation panel — sticky on desktop,
            first on mobile so a phone visitor sees "can I attend"
            immediately after the hero. */}
        <aside className="order-1 lg:sticky lg:top-6 lg:order-2">
          {/* Clean white action surface — deliberately quieter than
              the palette panel on the left so the CTA reads as the
              member's action, not just more branding. Only the
              eyebrow + the accent rule below carry palette colour. */}
          <div
            className="rounded-2xl border bg-white px-6 py-6 shadow-sm"
            style={{ borderColor: 'rgba(0,0,0,0.06)' }}
          >
            <p
              className="mb-4 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
              style={{ color: bookingEyebrow }}
            >
              {isCancelled
                ? 'Status'
                : event.booking_access_type === 'invitation_only'
                  ? 'Invitation only'
                  : event.booking_access_type === 'paid_separately'
                    ? 'Ticket'
                    : 'Reserve your place'}
            </p>

            {/* Invitation-only surfaces on its own — bookings don't
                apply and the copy needs a different tone. */}
            {isCancelled ? (
              <p className="text-[15px] font-semibold text-red-700">
                This Gathering has been cancelled
              </p>
            ) : event.booking_access_type === 'invitation_only' ? (
              <p className="text-[13.5px] leading-relaxed text-slate-700">
                This Gathering is by invitation. Contact the Creator
                if you&rsquo;d like to attend.
              </p>
            ) : event.booking_access_type === 'paid_separately' ? (
              <GatheringTicketPurchaseClient
                spaceSlug={slug}
                eventId={event.id}
                eventTitle={event.title}
                priceCents={event.ticket_price_cents}
                currency={event.ticket_currency}
                salesEnabled={event.sales_enabled}
                isAuthenticated={isAuthenticated}
                isPast={isPast}
                isCancelled={isCancelled}
                initialMyBookingStatus={event.my_booking_status}
                spotsRemaining={event.spots_remaining}
                capacity={event.capacity}
              />
            ) : event.requires_booking ? (
              <GatheringBookingClient
                eventId={event.id}
                spaceSlug={slug}
                requiresBooking={event.requires_booking}
                capacity={event.capacity}
                initialBookedCount={event.booked_count}
                initialSpotsRemaining={event.spots_remaining}
                bookingNote={event.booking_note}
                initialMyBookingStatus={event.my_booking_status as 'confirmed' | 'cancelled' | null}
                initialCanBook={event.can_book}
                initialCanCancelBooking={event.can_cancel_booking}
                isPast={isPast}
                recurrenceSeriesId={event.recurrence_series_id}
                accessType={event.booking_access_type as 'all_members' | 'pathway_required'}
                userHasPathwayAccess={event.user_has_pathway_access}
                bookingAccessType={event.booking_access_type}
                seriesTitle={event.series_title}
                userHasSeriesPass={event.user_has_series_pass ?? false}
                isAuthenticated={isAuthenticated}
                loginHref={loginHref}
              />
            ) : (
              <p className="text-[15px] font-semibold text-navy-900">
                {isPast
                  ? 'This Gathering has ended'
                  : isFull
                    ? 'All places taken'
                    : 'Open to everyone in this Collective'}
              </p>
            )}

            {/* Series linkage in the booking panel — for members
                without a pass, this is the primary "how do I get
                access" affordance. The booking clients above
                already show their own access-required copy; we
                just add the outbound link. */}
            {event.booking_access_type === 'included_with_series'
              && !isCancelled
              && !isPast
              && !(event.user_has_series_pass ?? false)
              && event.series_slug && (
              <div
                className="mt-4 pt-4"
                style={{ borderTop: `1px solid ${rgbaFromHex(primaryHex, 0.14)}` }}
              >
                <Link
                  href={`/spaces/${slug}/gathering-series/${event.series_slug}`}
                  className="inline-flex items-center text-[13px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: primaryHex }}
                >
                  View ways to join {event.series_title ?? 'this Series'} →
                </Link>
              </div>
            )}
          </div>
        </aside>

      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Presentational sub-components — small, server-side, no state
// ---------------------------------------------------------------------------

interface HeroOverlayProps {
  slug: string
  event: EventDetail
  badge: { label: string; bg: string; color: string }
  state: EventState | 'cancelled'
  countdown: string | null
  showCountdown: boolean
  locationLabel: string
  formatFullDate: (iso: string) => string
  formatTime: (iso: string) => string
  typeIcon: string
  typeLabel: string
  /** ``over-image`` = overlaid on a photo (bright text); ``on-tint``
   *  = sat on a soft tint (navy text). Same content either way. */
  variant: 'over-image' | 'on-tint'
}

function HeroOverlay({
  slug, event, badge, state, countdown, showCountdown,
  locationLabel, formatFullDate, formatTime, typeIcon, typeLabel, variant,
}: HeroOverlayProps) {
  const white = variant === 'over-image'
  const textPrimary = white ? '#FFFFFF' : '#0F172A'
  const textSecondary = white ? 'rgba(255,255,255,0.90)' : 'rgba(15,23,42,0.70)'
  // Chips are contrast-safe rather than palette-tinted so the hero
  // looks intentional on every Collective. Over an image every chip
  // sits on a translucent white background with white text; on the
  // no-cover variant the same chip reads as a soft neutral field.
  const chipBg = white ? 'rgba(255,255,255,0.14)' : 'rgba(15,23,42,0.06)'
  const chipText = white ? '#FFFFFF' : '#0F172A'
  const seriesChipBg = white ? 'rgba(255,255,255,0.20)' : 'rgba(15,23,42,0.08)'
  const seriesChipText = white ? '#FFFFFF' : '#0F172A'

  const container = white
    ? 'absolute inset-x-0 bottom-0 z-10 p-5 md:p-6'
    : 'relative'

  // Belt-and-braces: even with the strong overlay above, a firm
  // text shadow keeps white title/meta legible on the pathological
  // case (a bright/high-frequency spot lands directly under the
  // text block). Only applied over image variants.
  const textShadow = white ? '0 1px 14px rgba(0,0,0,0.65)' : undefined

  return (
    <div className={container} style={{ textShadow }}>
      {/* Chip row — type · Series link · state · countdown */}
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-medium"
          style={{ background: chipBg, color: chipText }}
        >
          <span aria-hidden="true">{typeIcon}</span>{typeLabel}
        </span>
        {event.series_slug && event.series_title && (
          <Link
            href={`/spaces/${slug}/gathering-series/${event.series_slug}`}
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-medium transition-opacity hover:opacity-90"
            style={{ background: seriesChipBg, color: seriesChipText }}
            title={`View ${event.series_title}`}
          >
            <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" fill="none">
              <path d="M5 1l4 4-4 4-4-4z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
            </svg>
            Part of {event.series_title}
          </Link>
        )}
        <span
          className={`inline-block rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider${state === 'live' ? ' animate-pulse' : ''}`}
          style={{ background: badge.bg, color: badge.color }}
        >
          {badge.label}
        </span>
        {showCountdown && countdown && (
          <span
            className="inline-block rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold"
            style={{ background: chipBg, color: chipText }}
          >
            {countdown}
          </span>
        )}
      </div>

      <h1
        className="font-serif text-2xl leading-tight md:text-3xl"
        style={{ color: textPrimary }}
      >
        {event.title}
      </h1>

      <p className="mt-2 text-[13px]" style={{ color: textSecondary }}>
        {formatFullDate(event.starts_at)} · {formatTime(event.starts_at)} · {locationLabel}
      </p>
    </div>
  )
}

