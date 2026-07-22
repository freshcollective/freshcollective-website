import { resolveMediaUrl } from '@/lib/api'
import { getSpaceEvents } from '@/lib/serverApi'
import { ImportantPanelContent } from '@/components/spaces/ImportantPanel'
import UpcomingGatheringsList from '@/components/spaces/UpcomingGatheringsList'
import type { EventSummary, SpaceResponse } from '@/types/platform'

interface Props {
  space: SpaceResponse | null
  memberCount: number
  leaderCount: number
}

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000

/**
 * Filter events to the rolling 7-day upcoming window. Split out so the
 * server component itself doesn't call `Date.now()` during render — the
 * React purity rule (`react-hooks/purity`) treats that as impure even
 * though this is a server component that runs once per request.
 */
function filterUpcomingThisWeek(events: EventSummary[]): EventSummary[] {
  const now = Date.now()
  const cutoff = now + SEVEN_DAYS_MS
  return events
    .filter((e) => e.status === 'active')
    .filter((e) => {
      const ts = new Date(e.starts_at).getTime()
      return ts >= now && ts <= cutoff
    })
    .sort((a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime())
}

export default async function CollectiveSidebarPanel({ space, memberCount, leaderCount }: Props) {
  // Atlas v1.2 — banner artwork now leads with the collective's assigned
  // Location. Fallback chain: Location thumbnail → Location hero → legacy
  // space cover → subtle gradient. The Important / This week / Notes
  // sections below are intentionally unchanged.
  const artworkUrl = resolveMediaUrl(
    space?.location?.thumbnail_artwork_url
      ?? space?.location?.hero_artwork_url
      ?? space?.cover_image_url,
  )
  const locationName = space?.location?.name ?? null
  const logoUrl = resolveMediaUrl(space?.logo_url ?? undefined)

  // "This week" — auto-populated from Gatherings starting within the next 7
  // days. getSpaceEvents is React-cached, so pages already fetching events
  // (e.g. /spaces/[slug]/events) don't pay for a second round-trip.
  const upcomingThisWeek: EventSummary[] = space
    ? filterUpcomingThisWeek(await getSpaceEvents(space.slug))
    : []

  return (
    <div
      className="overflow-hidden rounded-2xl bg-white"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {/* Banner image — rounded top corners from parent overflow-hidden */}
      {artworkUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={artworkUrl}
          alt=""
          aria-hidden="true"
          className="h-32 w-full object-cover"
        />
      ) : (
        <div
          className="h-16 w-full"
          style={{
            background: 'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
          }}
        />
      )}

      <div className="px-5 pt-5 pb-1">
        {/* Identity row — optional logo, collective name, Location name */}
        {space?.name && (
          <div className="mb-4 flex items-center gap-2.5">
            {logoUrl && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={logoUrl}
                alt=""
                aria-hidden="true"
                className="h-7 w-7 shrink-0 rounded-md object-contain"
                style={{
                  background: 'rgba(12,24,38,0.04)',
                  border: '1px solid rgba(12,24,38,0.08)',
                  padding: 2,
                }}
              />
            )}
            <div className="min-w-0">
              <p className="truncate text-[14px] font-semibold" style={{ color: '#0C1826' }}>
                {space.name}
              </p>
              {locationName && (
                <p
                  className="text-[11px] italic"
                  style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
                >
                  {locationName}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Stats row */}
        <div className="flex gap-6">
          <div>
            <p className="font-serif text-[22px] leading-tight" style={{ color: '#0C1826' }}>
              {memberCount}
            </p>
            <p className="mt-0.5 text-[11px] text-black">
              {memberCount === 1 ? 'member' : 'members'}
            </p>
          </div>
          <div>
            <p className="font-serif text-[22px] leading-tight" style={{ color: '#0C1826' }}>
              {leaderCount}
            </p>
            <p className="mt-0.5 text-[11px] text-black">
              {leaderCount === 1 ? 'leader' : 'leaders'}
            </p>
          </div>
        </div>

        {/* Divider */}
        <div className="mt-4 h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
      </div>

      {/* Important panel content */}
      <ImportantPanelContent
        className="px-5 pt-4 pb-6"
        welcomeBody={space?.guidance_start_body}
        notesBody={space?.guidance_links_body}
        focusOverride={space ? (
          <UpcomingGatheringsList
            events={upcomingThisWeek}
            timezone={space.timezone}
            spaceSlug={space.slug}
          />
        ) : undefined}
      />
    </div>
  )
}
