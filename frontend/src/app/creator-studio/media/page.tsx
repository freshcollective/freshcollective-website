import { getActiveCreatorSpace, getCreatorMedia } from '@/lib/serverApi'
import type { CreatorMediaAsset } from '@/types/platform'
import MediaLibraryClient from './MediaLibraryClient'

export default async function MediaLibraryPage() {
  const space = await getActiveCreatorSpace()
  const assets: CreatorMediaAsset[] = space ? await getCreatorMedia(space.slug) : []

  if (!space) {
    return (
      <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
            Creator Studio
          </p>
          <h1 className="text-2xl text-navy-900 md:text-3xl">Brand Library</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="text-[14px] leading-relaxed text-slate-500">
            Set up your collective first, then upload brand assets here.
          </p>
        </div>
      </div>
    )
  }

  return (
    <MediaLibraryClient
      initialAssets={assets}
      spaceSlug={space.slug}
      spaceName={space.name}
    />
  )
}
