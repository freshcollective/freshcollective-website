import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorMedia,
  getCreatorSpace,
  getBuildYourCollectiveOptions,
} from '@/lib/serverApi'
import type { CreatorMediaAsset, CreatorSpaceDetail } from '@/types/platform'
import type { BuildYourCollectiveOptions } from '@/lib/build-your-collective/types'
import AssetLibrarySection from './AssetLibrarySection'
import CollectiveHomePanelSafe from './CollectiveHomePanelSafe'

/**
 * Assets — the permanent home for both a collective's visual identity
 * (Collective Home: Atlas location, atmosphere, palette) and its
 * uploaded asset library (images, video, audio, files).
 *
 * All data is scoped to the currently active creator space via
 * ``getActiveCreatorSpace()`` — nothing here is hard-coded to any
 * specific collective, and switching spaces re-fetches everything on
 * this page's next render.
 */

async function _safe<T>(p: Promise<T>, slug: string, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/assets] ${label} failed for ${slug}:`, err)
    return fallback
  }
}

export default async function AssetsPage() {
  const space = await getActiveCreatorSpace()

  const [assets, spaceDetail, options]: [
    CreatorMediaAsset[],
    CreatorSpaceDetail | null,
    BuildYourCollectiveOptions | null,
  ] = space
    ? await Promise.all([
        _safe(getCreatorMedia(space.slug),           space.slug, 'getCreatorMedia',           []),
        _safe(
          getCreatorSpace(space.slug) as Promise<CreatorSpaceDetail | null>,
          space.slug, 'getCreatorSpace', null,
        ),
        _safe(getBuildYourCollectiveOptions(),       space.slug, 'getBuildYourCollectiveOptions', null),
      ])
    : [[], null, null]

  const atmosphereByKey = new Map(
    (options?.atmospheres ?? []).map((a) => [a.key, a.name]),
  )
  const atmosphereNames = spaceDetail
    ? (spaceDetail.atmosphere_keys ?? [])
        .map((k) => atmosphereByKey.get(k))
        .filter((n): n is string => !!n)
    : []

  if (!space) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="mb-8">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
            Creator Studio
          </p>
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Assets</h1>
        </div>
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first, then choose its home and upload assets here.
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
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Assets</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-black">
          Your collective&apos;s home in the Fresh Collective world, and the library of images, video, audio, and files it uses.
        </p>
      </div>

      <div className="space-y-8">
        {/* Collective Home — always first. Wrapped in a local boundary so
            a partial-data crash cannot blank the Asset Library below. */}
        {spaceDetail ? (
          <CollectiveHomePanelSafe
            slug={spaceDetail.slug}
            location={spaceDetail.location ?? null}
            atmosphereNames={atmosphereNames}
            colourPalette={spaceDetail.colour_palette ?? null}
          />
        ) : (
          <section
            className="overflow-hidden rounded-2xl bg-white p-6"
            style={{ border: '1px solid rgba(166, 69, 38, 0.24)' }}
          >
            <p className="text-[14.5px] font-semibold" style={{ color: '#A64526' }}>
              Collective Home couldn&apos;t be loaded.
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-black">
              The Asset Library below is still available. Please refresh in a moment, or check the backend logs for the actual exception.
            </p>
          </section>
        )}

        {/* Asset Library — the uploaded media the collective can reuse
            across pathways, About pages, resources, and gatherings. */}
        <AssetLibrarySection
          initialAssets={assets}
          spaceSlug={space.slug}
          spaceName={space.name}
        />
      </div>

    </div>
  )
}
