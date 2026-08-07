/**
 * AuthPageBackground — the full-bleed Atlas artwork behind /login and
 * /signup, plus the overlay + vignette that keeps the auth card
 * readable on top.
 *
 * The artwork is normally uploaded via the admin platform-artwork
 * manager (slot: ``auth_background``). When nothing is uploaded the
 * bundled ``HERO_IMAGE_SRC`` renders instead, so a fresh install still
 * has a proper background.
 *
 * The overlay layers deliberately live here — they should evolve with
 * the artwork, since a lighter image may need heavier overlay to keep
 * the auth card readable, and vice versa.
 */

const HERO_IMAGE_SRC = '/world/login-hero.png'
const HERO_OBJECT_POSITION = 'center 40%'

// Deep navy → teal gradient overlay. Heavier on the right so the auth
// card sits on the darker area for maximum contrast; lighter on the
// left so a hint of the world imagery breathes through under the
// welcome copy.
const OVERLAY_GRADIENT =
  'linear-gradient(115deg, rgba(5,11,20,0.62) 0%, rgba(7,24,36,0.78) 45%, rgba(7,24,36,0.90) 100%)'

// Subtle top+bottom vignette keeps the header + footer readable
// regardless of image content in those regions.
const VIGNETTE_GRADIENT =
  'linear-gradient(180deg, rgba(5,11,20,0.35) 0%, transparent 25%, transparent 75%, rgba(5,11,20,0.45) 100%)'

export default function AuthPageBackground({ imageUrl }: { imageUrl?: string | null }) {
  const src = imageUrl ?? HERO_IMAGE_SRC
  return (
    <div className="absolute inset-0" aria-hidden="true">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt=""
        className="absolute inset-0 h-full w-full object-cover"
        style={{ objectPosition: HERO_OBJECT_POSITION }}
      />
      <div className="absolute inset-0" style={{ background: OVERLAY_GRADIENT }} />
      <div className="absolute inset-0" style={{ background: VIGNETTE_GRADIENT }} />
    </div>
  )
}
