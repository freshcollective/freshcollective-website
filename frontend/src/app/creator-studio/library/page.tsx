import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorLibrary,
  getCreatorSpace,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail, LibraryListResponse } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import LibraryClient from './LibraryClient'

/**
 * Library — one creator surface over the file store and the link
 * store. The creator uploads files and adds links here; folders
 * organise both without exposing the split.
 *
 * Members never see this page. Anything a member needs to access
 * lands in a Pathway (Guided Experience or Knowledge Guide) via the
 * block editor's Library picker.
 */

async function _safe<T>(p: Promise<T>, slug: string, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/library] ${label} failed for ${slug}:`, err)
    return fallback
  }
}

export default async function LibraryPage() {
  const space = await getActiveCreatorSpace()

  if (!space) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Library</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then upload files and add links you want to
            reuse across Pathways here.
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

  const [initial, spaceDetail]: [LibraryListResponse, CreatorSpaceDetail | null] = await Promise.all([
    _safe(
      getCreatorLibrary(space.slug) as Promise<LibraryListResponse>,
      space.slug, 'getCreatorLibrary',
      { items: [], total: 0, limit: 50, offset: 0, folders: [] },
    ),
    _safe(
      getCreatorSpace(space.slug) as Promise<CreatorSpaceDetail | null>,
      space.slug, 'getCreatorSpace', null,
    ),
  ])

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
      <CollectiveArtworkHeader
        collectiveName={space.name}
        sectionTitle="Library"
        meta="Files and links you can drop into any Pathway."
        location={spaceDetail?.location ?? null}
        coverImageUrl={spaceDetail?.cover_image_url ?? null}
      />

      <LibraryClient
        spaceSlug={space.slug}
        initial={initial}
      />
    </div>
  )
}
