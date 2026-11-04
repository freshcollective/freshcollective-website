/**
 * Which image welcomes people into a Collective. One rule, one place.
 *
 * A Collective has two visual identities and they are not rivals: the
 * creator's own brand — name, logo, banner, description — and the
 * Collective's home in the Fresh Collective world, its Atlas Location.
 * The creator chooses which of the two leads.
 *
 * Why this is a module
 * --------------------
 * The question was answered independently in nine components, each
 * with its own slightly different fallback chain — thumbnail then hero
 * here, hero then thumbnail there — all of them putting the uploaded
 * banner last. A creator's banner therefore appeared nowhere. Every
 * surface that shows the *primary Collective image* now asks this.
 *
 * The server resolves the same rule in
 * `backend/app/services/collective_header_image.py` and sends the
 * answer as `header_image_url`. Prefer that field where a payload
 * carries it; this exists for the components that hold the parts
 * rather than the answer, and as the single description of the rule.
 *
 * Surfaces that are about the *Location* rather than the Collective —
 * the island card on the About page, Discover Places, the Atlas admin
 * — deliberately do not use this. They show Location artwork because
 * that is their subject.
 */

export const PREFER_LOCATION = 'location'
export const PREFER_BANNER = 'banner'

export type HeaderImagePreference =
  typeof PREFER_LOCATION | typeof PREFER_BANNER

/**
 * What a Collective that has never chosen gets, and what an
 * unrecognised value reads as. Unknown falls to the default rather
 * than to the banner, so a bad value can never change how a
 * Collective looks.
 */
export const DEFAULT_PREFERENCE: HeaderImagePreference = PREFER_LOCATION

export function normalisePreference(
  value: string | null | undefined,
): HeaderImagePreference {
  return value === PREFER_BANNER ? PREFER_BANNER : DEFAULT_PREFERENCE
}

export interface HeaderImageSources {
  preference?: string | null
  /** The creator's uploaded banner — `cover_image_url`. */
  bannerUrl?: string | null
  /** Atlas Location artwork. Read only; never written from here. */
  locationHeroUrl?: string | null
  locationThumbnailUrl?: string | null
}

function clean(value: string | null | undefined): string | null {
  const text = (value ?? '').trim()
  return text || null
}

/**
 * The image a primary Collective surface should show, or `null`.
 *
 *     preference is 'banner' AND a banner exists  →  the banner
 *     otherwise                                   →  Location hero,
 *                                                    then thumbnail,
 *                                                    then the banner
 *
 * The second line is exactly what every surface did before this rule
 * existed, so a Collective that has not chosen looks unchanged.
 *
 * The fallback is safe in one direction only. A creator who chose
 * their banner and whose banner has gone sees their Location artwork
 * rather than a broken image — and their *stored choice is not
 * changed by that*. The display falls back; the preference does not.
 * When the image returns, so does their banner.
 */
export function selectCollectiveHeaderImage(
  sources: HeaderImageSources,
): string | null {
  const banner = clean(sources.bannerUrl)
  const hero = clean(sources.locationHeroUrl)
  const thumbnail = clean(sources.locationThumbnailUrl)

  if (normalisePreference(sources.preference) === PREFER_BANNER && banner) {
    return banner
  }
  return hero ?? thumbnail ?? banner
}

/** Whether the creator's own banner is the image actually in use. */
export function bannerIsActive(sources: HeaderImageSources): boolean {
  const banner = clean(sources.bannerUrl)
  return Boolean(
    banner && normalisePreference(sources.preference) === PREFER_BANNER,
  )
}

/**
 * Whether the chosen banner could not be shown.
 *
 * True only when the creator selected their banner and there is no
 * banner to show — the case the fallback covers. Lets a surface
 * explain itself rather than silently showing something else.
 */
export function bannerSelectionUnavailable(
  sources: HeaderImageSources,
): boolean {
  return normalisePreference(sources.preference) === PREFER_BANNER
    && !clean(sources.bannerUrl)
}

/** The shape the API sends on a Collective payload. */
export interface HasHeaderImage {
  header_image_url?: string | null
  header_image_preference?: string | null
  cover_image_url?: string | null
  location_hero_artwork_url?: string | null
  location_thumbnail_artwork_url?: string | null
}

/**
 * The header image for a payload, preferring the server's answer.
 *
 * `header_image_url` is the same rule resolved server-side. Falling
 * back to computing it here keeps an older payload — one fetched
 * before this shipped, or from an endpoint not yet carrying the field
 * — rendering the way it always did instead of blank.
 */
export function headerImageFor(payload: HasHeaderImage): string | null {
  if (payload.header_image_url) return payload.header_image_url
  return selectCollectiveHeaderImage({
    preference: payload.header_image_preference,
    bannerUrl: payload.cover_image_url,
    locationHeroUrl: payload.location_hero_artwork_url,
    locationThumbnailUrl: payload.location_thumbnail_artwork_url,
  })
}
