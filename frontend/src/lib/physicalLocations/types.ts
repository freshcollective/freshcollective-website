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
