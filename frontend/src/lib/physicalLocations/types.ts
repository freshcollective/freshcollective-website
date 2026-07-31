/**
 * Types for the World Management → Physical Locations admin area.
 * These mirror the API responses from
 * ``/api/admin/physical-locations/*`` — the real-world Place model
 * as it is authored by Fresh Collective administrators.
 *
 * Distinct from Atlas Locations (mythic worldview for Collectives).
 * Physical Locations live in ``app.models.place.Place`` and back the
 * Discover Places surface.
 */

export type PhysicalLocationStatus = 'draft' | 'active' | 'hidden' | 'archived'

export interface PhysicalLocationSummary {
  id: string
  slug: string
  name: string
  region: string | null
  country_code: string
  status: PhysicalLocationStatus
  hero_artwork_url: string | null
  artwork_alt_text: string | null
  artwork_focal_x: number
  artwork_focal_y: number
  collective_count: number
  updated_at: string
}

export interface CollectiveInPhysicalLocation {
  id: string
  slug: string
  name: string
  status: string
}

/** Public shape from ``/api/places`` — the member-facing Discover
 *  Places surface. A superset of the admin summary card fields plus
 *  the editorial blurb + a small aggregate summary of what's
 *  happening in this location. */
export interface PublicPlaceSummary {
  id: string
  slug: string
  name: string
  country_code: string
  region: string | null
  hero_artwork_url: string | null
  artwork_alt_text: string | null
  artwork_focal_x: number
  artwork_focal_y: number
  blurb: string | null
  themes: string[]
  collective_count: number
  upcoming_gathering_count: number
}

/** One upcoming Gathering on a location detail page. Member-safe
 *  projection — never carries the venue address or private access
 *  instructions (those live on the Gathering's own detail page,
 *  gated by enrolment). */
export interface PublicPlaceGathering {
  id: string
  title: string
  space_slug: string
  space_name: string
  starts_at: string
  ends_at: string | null
  gathering_type: string
  attendance_format: 'online' | 'in_person' | 'hybrid'
  venue_name: string | null
  booking_access_type: string
  capacity: number | null
  ticket_price_cents: number | null
  ticket_currency: string | null
  thumbnail_url: string | null
}

/** Full public detail for a single active Physical Location — the
 *  payload behind ``/discover-places/[slug]``. Bundles the location's
 *  own fields, the Collectives that live here (in the same
 *  ``PublicSpaceCard`` shape as Explore Collectives so the same card
 *  component renders), and upcoming member-eligible Gatherings. */
export interface PublicPlaceDetail extends PublicPlaceSummary {
  collectives: import('@/types/platform').PublicSpaceCard[]
  upcoming_gatherings: PublicPlaceGathering[]
}

export interface PhysicalLocationDetail {
  id: string
  slug: string
  name: string
  region: string | null
  country_code: string
  blurb: string | null
  admin_note: string | null
  status: PhysicalLocationStatus
  hero_artwork_url: string | null
  artwork_alt_text: string | null
  artwork_focal_x: number
  artwork_focal_y: number
  latitude: number | null
  longitude: number | null
  timezone: string | null
  provider_place_id: string | null
  collectives: CollectiveInPhysicalLocation[]
  collective_count: number
  created_at: string
  updated_at: string
}
