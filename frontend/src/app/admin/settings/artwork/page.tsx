import { getAdminPlatformArtwork } from '@/lib/serverApi'
import PlatformArtworkClient from './PlatformArtworkClient'

/**
 * Platform Artwork — admin surface for the small, named collection of
 * shared interface images owned by the platform itself.
 *
 * This is not a media library. It exists to let admins upload artwork
 * for known-in-advance keys: the Explore Collectives dashboard tile,
 * the Creator Studio tile, and so on.
 */
export default async function PlatformArtworkPage() {
  const items = await getAdminPlatformArtwork()
  return <PlatformArtworkClient initialItems={items} />
}
