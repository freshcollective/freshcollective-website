/**
 * Types for the Build Your Collective creator ritual (Atlas v1.2).
 *
 * A creator does not design an island. They choose which curated Location
 * their collective lives inside, then personalise the atmosphere, colour
 * palette, identity statement and welcome message. Landscape and Natural
 * Elements are retired.
 */

export interface LocationOption {
  id: string
  key: string
  name: string
  description: string | null
  hero_artwork_url: string | null
  thumbnail_artwork_url: string | null
  /** 'CORNERSTONE' Locations are only offered to Platform Administrators.
   *  'ATLAS' is offered to Creator and Pro plans; 'COMMUNITY' is offered
   *  to Community (Free) plans. Used by the picker to group by type. */
  location_type: 'ATLAS' | 'CORNERSTONE' | 'COMMUNITY'
}

export interface AtmosphereOption {
  key: string
  name: string
}

export interface Palette {
  primary: string
  secondary: string
  accent: string
  background: string
}

export interface ColourPaletteOption {
  key: string
  name: string
  palette: Palette
}

export interface BuildYourCollectiveOptions {
  locations: LocationOption[]
  atmospheres: AtmosphereOption[]
  colour_palettes: ColourPaletteOption[]
}

export type Visibility = 'public' | 'link' | 'private'
export type PricingType = 'free' | 'contribution'
export type BuildMode = 'create' | 'change-location' | 'edit-identity'

/**
 * The evolving state the creator can hold while walking the ritual.
 * Every field optional so drafts can be saved mid-step; strict validation
 * happens at the final open() / patch call.
 */
export interface DraftData {
  step?: number
  location_id?: string | null
  atmosphere_keys?: string[]
  colour_palette_key?: string | null
  identity_statement?: string | null
  welcome_message?: string | null
  name?: string | null
  description?: string | null
  visibility?: Visibility | null
  pricing_type?: PricingType | null
  pricing_amount_cents?: number | null
  pricing_note?: string | null
}

/** Steps in the ritual, in order. Atmosphere precedes Location — the
 *  feeling of a collective is chosen first, and the island is chosen
 *  as the visual home for that feeling. */
export const STEPS = [
  'welcome',
  'atmosphere',
  'location',
  'colour_palette',
  'identity',
  'welcome_message',
  'practical',
  'confirmation',
] as const

export type StepKey = typeof STEPS[number]
export const STEP_COUNT = STEPS.length
