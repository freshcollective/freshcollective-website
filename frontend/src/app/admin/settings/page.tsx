import Link from 'next/link'
import { resolveMediaUrl } from '@/lib/api'
import { getPublicPlatformArtwork } from '@/lib/serverApi'

export default async function AdminSettingsPage() {
  const artwork = await getPublicPlatformArtwork().catch(() => [])
  const artworkByKey = new Map(artwork.map((a) => [a.key, a]))
  const heroArt = artworkByKey.get('mother_world_hero')
    ?? artworkByKey.get('explore_collectives')
    ?? null
  const previewUrl = resolveMediaUrl(
    heroArt?.image_url ?? heroArt?.thumbnail_url ?? undefined,
  )

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">World Settings</h1>
        <p className="mt-1 text-[13px] text-[#000000]">
          Shared settings that shape the experience of the entire world.
        </p>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Link
          href="/admin/settings/artwork"
          className="group block overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5"
          style={{
            border: '1px solid rgba(12, 24, 38, 0.08)',
            boxShadow: '0 1px 3px rgba(12, 24, 38, 0.04)',
          }}
        >
          <div
            className="relative w-full overflow-hidden"
            style={{
              aspectRatio: '3 / 1',
              background:
                'linear-gradient(135deg, rgba(56, 160, 158, 0.14) 0%, rgba(247, 232, 200, 0.10) 55%, rgba(212, 176, 72, 0.16) 100%)',
            }}
          >
            {previewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt="World Artwork"
                className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
              />
            ) : (
              <svg
                viewBox="0 0 600 200"
                preserveAspectRatio="xMidYMid slice"
                className="absolute inset-0 h-full w-full"
                aria-hidden="true"
              >
                <defs>
                  <radialGradient id="ws-artwork-preview" cx="0.5" cy="0.55" r="0.7">
                    <stop offset="0%" stopColor="#E5F0EF" />
                    <stop offset="60%" stopColor="#F4F7F6" />
                    <stop offset="100%" stopColor="#FBFDFC" />
                  </radialGradient>
                </defs>
                <rect width="600" height="200" fill="url(#ws-artwork-preview)" />
                <g fill="none" stroke="rgba(56, 160, 158, 0.28)" strokeWidth="1">
                  <path d="M 0 140 Q 150 120 300 140 T 600 140" />
                  <path d="M 0 160 Q 150 148 300 160 T 600 160" opacity="0.6" />
                </g>
                <circle cx="470" cy="70" r="18" fill="#D4B048" opacity="0.55" />
                <path d="M 80 140 Q 110 110 145 140 Z" fill="#0C1826" opacity="0.55" />
                <path d="M 200 140 Q 240 100 285 140 Z" fill="#0C1826" opacity="0.45" />
              </svg>
            )}
          </div>
          <div className="px-6 py-5">
            <h2
              className="font-serif text-[20px] leading-tight"
              style={{ color: '#0C1826' }}
            >
              World Artwork
            </h2>
            <p
              className="mt-2 text-[13.5px] italic leading-relaxed"
              style={{
                color: 'rgba(12, 24, 38, 0.62)',
                fontFamily: 'Georgia, serif',
              }}
            >
              Manage the shared imagery that shapes Fresh Collective&rsquo;s public experience.
            </p>
            <span
              className="mt-4 inline-flex items-center gap-1.5 rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
              style={{
                background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                letterSpacing: '0.06em',
              }}
            >
              Manage artwork →
            </span>
          </div>
        </Link>
      </div>

      <div
        className="rounded-xl bg-white p-6"
        style={{ border: '1px solid #E2E8F0' }}
      >
        <h2 className="mb-2 text-[15px] font-semibold text-[#0F172A]">Not yet active</h2>
        <p className="mb-4 text-[13px] text-[#000000]">
          Platform configuration controls are not currently active. No global settings will take
          effect from this page.
        </p>
        <p className="mb-1 text-[12px] font-semibold uppercase tracking-wide text-[#000000]">Planned settings</p>
        <ul className="space-y-1 text-[13px] text-[#000000]">
          <li>· Platform name, branding, and domain</li>
          <li>· Default onboarding flow and welcome copy</li>
          <li>· Email notification and digest settings</li>
          <li>· Feature flags and access controls</li>
          <li>· Stripe and payment gateway configuration</li>
        </ul>
        <p className="mt-4 text-[12px] text-[#000000]">
          Configuration changes currently require a code deployment or database update.
        </p>
      </div>
    </div>
  )
}
