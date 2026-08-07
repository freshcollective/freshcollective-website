import { redirect } from 'next/navigation'
import {
  getBuildYourCollectiveOptions,
  getBuildYourCollectiveDraft,
  getCreatorSpace,
  getPublicPlatformArtwork,
  buildPlatformArtLookup,
} from '@/lib/serverApi'
import type { BuildYourCollectiveOptions, DraftData, BuildMode } from '@/lib/build-your-collective/types'
import BuildYourCollectiveClient from './BuildYourCollectiveClient'

interface PageProps {
  searchParams: Promise<{ mode?: string; slug?: string }>
}

/**
 * Build Your Collective — the guided creator ritual (Atlas v1.2).
 *
 * Supports three modes via query params:
 *   - default            : create a new collective (uses draft autosave)
 *   - mode=change-location&slug=X : edit an existing collective, start at Location
 *   - mode=edit-identity&slug=X   : edit an existing collective, start at Atmosphere
 */
export default async function BuildYourCollectivePage({ searchParams }: PageProps) {
  const { mode: rawMode, slug } = await searchParams
  const mode: BuildMode =
    rawMode === 'change-location' ? 'change-location'
    : rawMode === 'edit-identity' ? 'edit-identity'
    : 'create'

  const [options, draftResponse, artwork] = await Promise.all([
    getBuildYourCollectiveOptions(),
    mode === 'create' ? getBuildYourCollectiveDraft() : Promise.resolve(null),
    getPublicPlatformArtwork(),
  ]) as [
    BuildYourCollectiveOptions | null,
    { data: DraftData } | null,
    Awaited<ReturnType<typeof getPublicPlatformArtwork>>,
  ]

  if (!options) redirect('/creator-studio')

  const artFor = buildPlatformArtLookup(artwork)
  const heroArt = {
    atmosphere:     artFor('creator_ritual_atmosphere'),
    identity:       artFor('creator_ritual_identity'),
    welcomeMessage: artFor('creator_ritual_welcome_message'),
    practical:      artFor('creator_ritual_practical'),
  }

  // Edit modes prime the client from the existing collective, not a draft.
  let seededDraft: DraftData = {}
  let seededSlug: string | null = null
  if (mode !== 'create' && slug) {
    const space = await getCreatorSpace(slug) as {
      name: string
      description: string | null
      location_id: string | null
      atmosphere_keys: string[] | null
      colour_palette_key: string | null
      identity_statement: string | null
      welcome_message: string | null
    } | null
    if (space) {
      seededDraft = {
        name: space.name,
        description: space.description,
        location_id: space.location_id,
        atmosphere_keys: space.atmosphere_keys ?? [],
        colour_palette_key: space.colour_palette_key,
        identity_statement: space.identity_statement,
        welcome_message: space.welcome_message,
      }
      seededSlug = slug
    }
  }

  return (
    <BuildYourCollectiveClient
      options={options}
      initialDraft={mode === 'create' ? (draftResponse?.data ?? {}) : seededDraft}
      mode={mode}
      slug={seededSlug}
      heroArt={heroArt}
    />
  )
}
