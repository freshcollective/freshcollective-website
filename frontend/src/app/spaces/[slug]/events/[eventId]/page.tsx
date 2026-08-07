import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getSpace, getSpaceEvent, getMe } from '@/lib/serverApi'
import type { EventDetail } from '@/types/platform'
import { countdownLabel, formatGatheringFullDate, formatGatheringTime } from '@/lib/dateTime'
import GatheringBookingClient from '@/components/spaces/GatheringBookingClient'
import GatheringTicketPurchaseClient from '@/components/spaces/GatheringTicketPurchaseClient'
import { formatMoneyCents } from '@/lib/formatMoney'
import {
  gatheringIcon, gatheringLabel, gatheringDescription,
  attendanceFormatLabel,
  accessTypeMeta,
} from '@/lib/gatheringTypes'

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

const STATE_BADGE: Record<EventState | 'cancelled', { label: string; bg: string; color: string }> = {
  upcoming:         { label: 'Upcoming',           bg: 'rgba(56,160,158,0.10)', color: '#0f766e' },
  live:             { label: 'Happening now',       bg: 'rgba(22,163,74,0.10)',  color: '#15803d' },
  'past-replay':    { label: 'Replay available',    bg: 'rgba(21,36,54,0.08)',   color: '#334155' },
  'past-no-replay': { label: 'Gathering ended',     bg: 'rgba(0,0,0,0.05)',      color: '#94a3b8' },
  'cancelled':      { label: 'Cancelled',           bg: 'rgba(239,68,68,0.08)',  color: '#b91c1c' },
}

// ---------------------------------------------------------------------------
// Small server-side sub-components for the at-a-glance panel
// ---------------------------------------------------------------------------

function GlanceSection({
  title, children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="border-t border-border first:border-t-0">
      <div className="px-5 pt-4">
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.16em]"
           style={{ color: 'rgba(12,24,38,0.48)' }}>
          {title}
        </p>
      </div>
      <div className="px-5 pb-4 pt-2 space-y-1.5">
        {children}
      </div>
    </div>
  )
}

function GlanceRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4">
      <span className="w-24 shrink-0 text-[12px] text-black">{label}</span>
      <span className="min-w-0 whitespace-pre-line text-[14px] text-navy-900">{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------

export default async function EventDetailPage({ params }: Props) {
  const { slug, eventId } = await params
  const [space, event, me] = await Promise.all([
    getSpace(slug),
    getSpaceEvent(slug, eventId),
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
  const access = accessTypeMeta(event.booking_access_type)
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

  return (
    <div className="max-w-3xl">

      {/* Back link */}
      <div className="mb-6">
        <Link
          href={`/spaces/${slug}/events`}
          className="text-sm text-black transition-colors hover:text-teal-600"
        >
          ← Gatherings
        </Link>
      </div>

      {/* ──────── Gathering Hero ────────
          Feels like arriving at a destination:
            ▸ cover image (if any)
            ▸ type-icon + label chip
            ▸ state pill + countdown
            ▸ large title
            ▸ date · time · duration · host · format · access
      */}
      <div
        className="relative mb-8 overflow-hidden rounded-2xl"
        style={{
          background: '#071824',
          border: '1px solid rgba(66,199,198,0.10)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        {event.thumbnail_url && (
          <div className="relative h-52 w-full overflow-hidden">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={event.thumbnail_url}
              alt={event.title}
              className="h-full w-full object-cover"
            />
            {isCancelled && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                <span className="rounded-full bg-white/90 px-4 py-1.5 text-sm font-semibold text-slate-700">
                  Cancelled
                </span>
              </div>
            )}
          </div>
        )}
        <div className="px-7 py-8 md:px-9">
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />

          {/* Chip row — type · state · optional countdown */}
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-medium"
              style={{ background: 'rgba(255,255,255,0.12)', color: '#FFFFFF' }}
            >
              <span aria-hidden="true">{typeIcon}</span>{typeLabel}
            </span>
            <span
              className={`inline-block rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-wide${state === 'live' ? ' animate-pulse' : ''}`}
              style={{ background: badge.bg, color: badge.color }}
            >
              {badge.label}
            </span>
            {showCountdown && (
              <span
                className="inline-block rounded-full px-3 py-1 text-[11px] font-semibold"
                style={{ background: 'rgba(85,215,210,0.12)', color: '#D9FFFD' }}
              >
                {countdown}
              </span>
            )}
          </div>

          <h1 className="mb-2 leading-snug">
            <span
              className="inline-block text-2xl font-semibold md:text-3xl"
              style={{
                background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              {event.title}
            </span>
          </h1>

          {/* Second line of the hero — date/time/duration + host + format */}
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px]" style={{ color: '#FFFFFF' }}>
            <span>{formatFullDate(event.starts_at)}</span>
            <span>{formatTime(event.starts_at)}</span>
            {durationLabel && <span>{durationLabel}</span>}
            <span>{locationLabel}</span>
            {event.host_name && (
              <span style={{ opacity: 0.85 }}>Hosted by {event.host_name}</span>
            )}
          </div>

          {/* Access badge — subtle, sits at the bottom of the hero */}
          <div className="mt-4">
            <span
              className="inline-block rounded-full px-3 py-1 text-[11.5px] font-medium"
              style={{
                background:
                  access.value === 'paid_separately' ? 'rgba(212,176,72,0.20)'
                  : access.value === 'invitation_only' ? 'rgba(180,140,200,0.20)'
                  : 'rgba(255,255,255,0.10)',
                color:
                  access.value === 'paid_separately' ? '#F8DC80'
                  : access.value === 'invitation_only' ? '#E8D0F0'
                  : '#FFFFFF',
              }}
            >
              {access.label}
              {access.value === 'paid_separately'
                && event.ticket_price_cents != null
                && event.ticket_currency
                && ` \u00b7 ${formatMoneyCents(event.ticket_price_cents, event.ticket_currency)}`}
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px] lg:items-start">

        {/* ── Left column: at-a-glance + description + actions ── */}
        <div className="order-2 flex flex-col gap-6 lg:order-1">

          {/* ─── At a glance panel — the unified source of truth ─── */}
          <div className="overflow-hidden rounded-2xl border border-border bg-white">
            <div className="border-b border-border px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                At a glance
              </p>
            </div>

            <GlanceSection title="WHEN">
              <GlanceRow label="Date" value={formatFullDate(event.starts_at)} />
              <GlanceRow label="Time" value={formatTime(event.starts_at)} />
              {durationLabel && <GlanceRow label="Duration" value={durationLabel} />}
            </GlanceSection>

            <GlanceSection title="WHERE">
              <GlanceRow label="Format" value={locationLabel} />
              {event.venue_name && (
                <GlanceRow label="Venue" value={event.venue_name} />
              )}
              {event.venue_address && (
                <GlanceRow label="Address" value={event.venue_address} />
              )}
              {event.location_url && (
                <GlanceRow
                  label="Meeting link"
                  value={
                    <a
                      href={event.location_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-teal-700 underline break-all hover:text-teal-800"
                    >
                      {event.location_url}
                    </a>
                  }
                />
              )}
              {!event.location_url
                && (event.attendance_format === 'online' || event.attendance_format === 'hybrid')
                && !isPast && (
                <GlanceRow
                  label="Meeting link"
                  value={
                    <span className="italic text-slate-500">
                      Shared with attendees before this Gathering.
                    </span>
                  }
                />
              )}
            </GlanceSection>

            <GlanceSection title="WHO">
              {event.host_name && <GlanceRow label="Host" value={event.host_name} />}
              {event.capacity != null && (
                <GlanceRow label="Capacity" value={`${event.capacity} places`} />
              )}
              {placesRemaining != null && event.capacity != null && (
                <GlanceRow
                  label="Places"
                  value={
                    placesRemaining === 0
                      ? 'All places taken'
                      : `${placesRemaining} remaining`
                  }
                />
              )}
              {!event.host_name && event.capacity == null && (
                <p className="text-[13px] italic text-slate-500">Open to everyone who can view this Gathering.</p>
              )}
            </GlanceSection>

            <GlanceSection title="ACCESS">
              <GlanceRow
                label={
                  access.value === 'paid_separately' && event.ticket_price_cents != null && event.ticket_currency
                    ? `${access.label} \u00b7 ${formatMoneyCents(event.ticket_price_cents, event.ticket_currency)}`
                    : access.label
                }
                value={
                  access.value === 'free'
                    ? 'No payment required. Visibility and membership rules apply separately.'
                    : access.value === 'included_with_collective'
                      ? 'Included with active Collective membership.'
                      : access.value === 'included_with_pathway'
                        ? 'Included for members enrolled in the linked Pathway.'
                        : access.value === 'invitation_only'
                          ? 'Members register only when a Creator adds them.'
                          : 'Your ticket reserves one place and gives you access to this Gathering only.'
                }
              />
            </GlanceSection>
          </div>

          {/* Access / arrival instructions — only for attendees; server scrubs otherwise */}
          {event.access_instructions && (
            <div className="rounded-2xl border border-border bg-white px-6 py-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                {event.attendance_format === 'in_person' ? 'Arrival instructions' : 'Access instructions'}
              </p>
              <div className="space-y-3">
                {event.access_instructions.split('\n').filter(Boolean).map((para: string, i: number) => (
                  <p key={i} className="text-[14px] leading-relaxed text-black">{para}</p>
                ))}
              </div>
            </div>
          )}

          {/* Paid Gatherings render their purchase state in the right-column
              panel (GatheringTicketPurchaseClient). No inline "coming soon"
              banner in the main flow. */}

          {access.value === 'invitation_only' && !isCancelled && (
            <div
              className="rounded-2xl px-6 py-5"
              style={{ background: 'rgba(126,66,145,0.06)', border: '1px solid rgba(126,66,145,0.25)' }}
            >
              <p className="mb-1 text-[13px] font-semibold" style={{ color: '#6B2C7A' }}>
                Invitation only
              </p>
              <p className="text-[13.5px] leading-relaxed" style={{ color: '#6B2C7A' }}>
                This Gathering is by invitation. Please contact the
                Creator if you&rsquo;d like to attend.
              </p>
            </div>
          )}

          {/* Description */}
          {event.description ? (
            <div className="rounded-2xl border border-border bg-white px-6 py-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                About this Gathering
              </p>
              <div className="space-y-3">
                {event.description.split('\n').filter(Boolean).map((para: string, i: number) => (
                  <p key={i} className="text-[15px] leading-[1.8] text-black">{para}</p>
                ))}
              </div>
            </div>
          ) : (
            // Fall back to the type description so every Gathering still
            // has a small, warm framing sentence when the caretaker
            // hasn't added one of their own.
            <div className="rounded-2xl border border-border bg-white px-6 py-5">
              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                About this Gathering
              </p>
              <p className="text-[15px] italic leading-relaxed text-black" style={{ fontFamily: 'Georgia, serif' }}>
                {typeDescription}
              </p>
            </div>
          )}

          {/* State-aware action buttons */}
          {state === 'upcoming' && (
            <div className="flex flex-wrap gap-3">
              {event.location_url && (
                <a
                  href={event.location_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center rounded-full px-6 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'var(--fc-accent, #0d9488)' }}
                >
                  Join now →
                </a>
              )}
              <a
                href={googleCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hidden items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-black transition-colors hover:border-slate-300 hover:text-navy-900 md:inline-flex"
              >
                Google Calendar
              </a>
              <a
                href={outlookCalUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hidden items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-black transition-colors hover:border-slate-300 hover:text-navy-900 md:inline-flex"
              >
                Outlook
              </a>
              <a
                href={icsUrl}
                download
                className="hidden items-center rounded-full border border-slate-200 px-6 py-2.5 text-sm font-medium text-black transition-colors hover:border-slate-300 hover:text-navy-900 md:inline-flex"
              >
                Download .ics
              </a>
            </div>
          )}

          {state === 'live' && (
            <div>
              {event.location_url ? (
                <a
                  href={event.location_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center rounded-full px-6 py-2.5 text-sm font-semibold text-white transition-opacity hover:opacity-90"
                  style={{ background: 'var(--fc-accent, #0d9488)' }}
                >
                  Join now →
                </a>
              ) : (
                <p className="text-sm text-black">Join link will be available shortly.</p>
              )}
            </div>
          )}

          {state === 'past-replay' && event.recording_url && (
            <a
              href={event.recording_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex w-fit items-center rounded-full bg-navy-900 px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-navy-800"
            >
              Watch replay →
            </a>
          )}

          {state === 'past-no-replay' && (
            <p className="text-sm text-black">
              A replay of this Gathering will be available here once it has been processed.
            </p>
          )}

        </div>

        {/* ── Right column: reservation panel — first on mobile, second on desktop ── */}
        <div className="order-1 lg:sticky lg:top-6 lg:order-2">
          <div
            className="rounded-2xl border bg-white p-5"
            style={{ borderColor: 'rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            <div
              className="mb-4 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
            />

            {isCancelled ? (
              <>
                <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Status
                </p>
                <p className="text-[15px] font-semibold text-red-700">This Gathering has been cancelled</p>
              </>
            ) : event.booking_access_type === 'paid_separately' ? (
              /* Stage 4: standalone paid Gathering — own state machine. */
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
                isAuthenticated={isAuthenticated}
                loginHref={loginHref}
              />
            ) : (
              <>
                <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                  Access
                </p>
                <p className="mb-4 text-[15px] font-semibold text-navy-900">
                  {isPast
                    ? 'This Gathering has ended'
                    : isFull
                      ? 'All places taken'
                      : 'Open to everyone in this collective'}
                </p>
              </>
            )}

            {(state === 'upcoming' || state === 'live') && (
              <div className="mt-3 flex flex-col gap-1.5 text-center text-[12px]">
                <a href={googleCalUrl} target="_blank" rel="noopener noreferrer"
                  className="text-black transition-colors hover:text-teal-600">
                  Google Calendar
                </a>
                <a href={outlookCalUrl} target="_blank" rel="noopener noreferrer"
                  className="text-black transition-colors hover:text-teal-600">
                  Outlook
                </a>
                <a href={icsUrl} download
                  className="text-black transition-colors hover:text-teal-600">
                  Download .ics
                </a>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
