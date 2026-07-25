import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorMedia } from '@/lib/serverApi'
import type { CreatorMediaAsset } from '@/types/platform'
import AssetLibrarySection from './AssetLibrarySection'

/**
 * Media Library — the collective's uploaded source media.
 *
 * Formerly "Assets"; the previous page also carried the Collective
 * Home panel (Location, atmosphere, palette). That has moved to
 * Identity → Artwork so this destination has a single, explicit
 * purpose: upload and manage the images, video, audio and files
 * used across this collective.
 *
 * Resources (member-facing materials) remain a separate destination.
 */

async function _safe<T>(p: Promise<T>, slug: string, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/assets] ${label} failed for ${slug}:`, err)
    return fallback
  }
}

export default async function MediaLibraryPage() {
  const space = await getActiveCreatorSpace()

  const assets: CreatorMediaAsset[] = space
    ? await _safe(getCreatorMedia(space.slug), space.slug, 'getCreatorMedia', [])
    : []

  if (!space) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Media Library</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then upload images, video, audio, and files for it here.
          </p>
          <Link
            href="/build-your-collective"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Build your collective
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {/* Page header */}
      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500"
        >
          {space.name}
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Media Library</h1>
        <p
          className="mt-2 max-w-xl text-[14.5px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          Upload and manage the images, video, audio and files used across this collective.
        </p>
      </div>

      <AssetLibrarySection
        initialAssets={assets}
        spaceSlug={space.slug}
        spaceName={space.name}
      />

    </div>
  )
}
