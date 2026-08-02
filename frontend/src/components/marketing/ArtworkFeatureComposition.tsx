import { atmosphereBackground, atmosphereForSlug } from '@/lib/placeAtmosphere'

/**
 * Shared editorial artwork frame used by the homepage's "Life inside a
 * Collective" rows and by the /for-creators plan rows.
 *
 * Fixed 3:2 aspect, edge-to-edge photograph with a graceful atmospheric
 * gradient fallback when no image is uploaded. Rounded corners and a
 * soft base shadow so the frame reads as a considered artefact against
 * the white page background. No overlay layer — the artwork is the
 * whole visual.
 */
export const INSIDE_ASPECT = '3 / 2'

interface Props {
  artworkUrl: string | null
  atmosphereSlug: string
  artworkAlt: string
  /** Override the default 3:2 frame. `/for-creators` uses 4:3 so the
   *  four editorial rows sit a little squarer than the homepage rows. */
  aspectRatio?: string
}

export default function ArtworkFeatureComposition({
  artworkUrl, atmosphereSlug, artworkAlt, aspectRatio,
}: Props) {
  return (
    <div
      className="relative w-full overflow-hidden rounded-3xl"
      style={{
        aspectRatio: aspectRatio ?? INSIDE_ASPECT,
        boxShadow:
          '0 24px 60px rgba(12, 24, 38, 0.14),' +
          '0 6px 20px rgba(12, 24, 38, 0.08)',
      }}
    >
      {artworkUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={artworkUrl}
          alt={artworkAlt}
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
      ) : (
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{ background: atmosphereBackground(atmosphereForSlug(atmosphereSlug, false)) }}
        />
      )}
    </div>
  )
}
