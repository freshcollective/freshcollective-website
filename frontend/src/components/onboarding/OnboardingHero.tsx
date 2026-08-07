/**
 * OnboardingHero — a wide banner shown at the top of each onboarding
 * step. Falls back to a small SVG scene (the same understated artwork
 * the flows used before) when the admin hasn't uploaded imagery for
 * the slot, so a fresh install still reads intentional.
 *
 * Consumers pass:
 *   - imageUrl  — resolved artwork URL (or null)
 *   - alt       — accessibility caption (empty string for purely
 *                 decorative images)
 *   - fallback  — the SVG scene node used when imageUrl is null
 *
 * The wrapper renders a rounded, 16:9 landscape band that reads as a
 * framed hero image rather than a background decoration. The scrim +
 * subtle vignette keep it grounded even when the source image is
 * bright or busy at the top.
 */

interface Props {
  imageUrl: string | null
  alt?: string
  fallback: React.ReactNode
}

export default function OnboardingHero({ imageUrl, alt = '', fallback }: Props) {
  return (
    <div
      className="mx-auto mb-10 w-full overflow-hidden rounded-2xl"
      style={{
        aspectRatio: '16 / 9',
        maxWidth: 720,
        background: '#F4F7F6',
        border: '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: '0 8px 24px rgba(12, 24, 38, 0.06)',
      }}
    >
      {imageUrl ? (
        <div className="relative h-full w-full">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt={alt}
            className="h-full w-full object-cover"
          />
          {/* Feather the bottom edge slightly so the eyebrow beneath
              breathes rather than pressing straight against the image. */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0"
            style={{
              height: '32%',
              background: 'linear-gradient(180deg, transparent 0%, rgba(251, 246, 234, 0.55) 100%)',
            }}
          />
        </div>
      ) : (
        <div
          className="flex h-full w-full items-center justify-center"
          style={{
            background:
              'radial-gradient(70% 50% at 50% 40%, rgba(56, 160, 158, 0.10), transparent 70%),' +
              'linear-gradient(180deg, #FBFDFC 0%, #F4F7F6 100%)',
          }}
        >
          <div style={{ width: 140, height: 140 }}>{fallback}</div>
        </div>
      )}
    </div>
  )
}
