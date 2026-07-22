/**
 * Types for the Admin Portal Atlas area. These mirror the API responses
 * from `/api/admin/atlas/*` — the Location model as it is authored by
 * Fresh Collective administrators.
 */

export type LocationType = 'ATLAS' | 'CORNERSTONE' | 'COMMUNITY'

export interface LocationSummary {
  id: string
  key: string
  name: string
  description: string | null
  status: 'active' | 'hidden'
  location_type: LocationType
  hero_artwork_url: string | null
  thumbnail_artwork_url: string | null
  biome: string | null
  archipelago: string | null
  collective_count: number
  position: number
}

export interface CollectiveInLocation {
  id: string
  slug: string
  name: string
  status: string
}

export interface LocationDetail {
  id: string
  key: string
  name: string
  /** Short description — the concise summary. */
  description: string | null
  /** The long-form atlas entry — multi-paragraph story of the Location. */
  atlas_entry: string | null
  status: 'active' | 'hidden'
  location_type: LocationType
  /** Master artwork URL. `thumbnail_artwork_url` is legacy — kept in the
   *  payload for compatibility but no longer edited via the Admin UI. */
  hero_artwork_url: string | null
  thumbnail_artwork_url: string | null
  // Legacy classification fields — kept in payload; no longer edited here.
  biome: string | null
  archipelago: string | null
  preferred_atmospheres: string[]
  preferred_colour_stories: string[]
  preferred_themes: string[]
  position: number
  created_at: string
  updated_at: string
  collectives: CollectiveInLocation[]
}
