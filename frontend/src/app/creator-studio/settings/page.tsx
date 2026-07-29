import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorSpace,
  getBuildYourCollectiveOptions,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import type { BuildYourCollectiveOptions } from '@/lib/build-your-collective/types'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'
import SettingsTabbedShell from './SettingsTabbedShell'

async function _safe<T>(p: Promise<T>, slug: string, label: string, fallback: T): Promise<T> {
  try {
    return await p
  } catch (err) {
    console.error(`[creator-studio/settings] ${label} failed for ${slug}:`, err)
    return fallback
  }
}

export default async function SettingsPage() {
  const primarySpace = await getActiveCreatorSpace()

  let spaceDetail: CreatorSpaceDetail | null = null
  let buildOptions: BuildYourCollectiveOptions | null = null
  if (primarySpace) {
    ;[spaceDetail, buildOptions] = await Promise.all([
      _safe(
        getCreatorSpace(primarySpace.slug) as Promise<CreatorSpaceDetail | null>,
        primarySpace.slug, 'getCreatorSpace', null,
      ),
      _safe(getBuildYourCollectiveOptions(), primarySpace.slug, 'getBuildYourCollectiveOptions', null),
    ])
  }

  // Resolve atmosphere keys → display names using the build-your-collective
  // options catalog. Needed by the Collective Home panel on the Artwork tab.
  const atmosphereByKey = new Map(
    (buildOptions?.atmospheres ?? []).map((a) => [a.key, a.name]),
  )
  const atmosphereNames = spaceDetail
    ? (spaceDetail.atmosphere_keys ?? [])
        .map((k) => atmosphereByKey.get(k))
        .filter((n): n is string => !!n)
    : []

  if (primarySpace && !spaceDetail) {
    console.error(
      `[creator-studio/settings] Space detail could not be loaded for slug=${primarySpace.slug}. ` +
      `Check the backend logs; the panels that depend on it will show local error states.`,
    )
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      {primarySpace && (
        <CollectiveArtworkHeader
          collectiveName={primarySpace.name}
          sectionTitle="Collective Settings"
          meta="Shape how this Collective feels and how people experience it."
          location={spaceDetail?.location ?? null}
          coverImageUrl={spaceDetail?.cover_image_url ?? null}
        />
      )}

      {!primarySpace && (
        <div className="mb-8">
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Collective Settings</h1>
        </div>
      )}

      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first to access its identity.
          </p>
          <Link
            href="/build-your-collective"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Build your collective
          </Link>
        </div>
      )}

      {primarySpace && !spaceDetail && (
        <div className="mb-5 rounded-2xl bg-white p-6" style={{ border: '1px solid rgba(166, 69, 38, 0.24)' }}>
          <p className="text-[14.5px] font-semibold" style={{ color: '#A64526' }}>
            We couldn&apos;t load the details for this collective.
          </p>
          <p className="mt-2 text-[13px] leading-relaxed text-black">
            Please refresh the page in a moment, or check the backend logs for the actual exception.
          </p>
        </div>
      )}

      {spaceDetail && spaceDetail.auto_grant_role && (
        <div
          className="mb-5 rounded-2xl bg-white p-6"
          style={{ border: '1px solid rgba(56,160,158,0.24)', borderTop: '3px solid rgba(56,160,158,0.55)' }}
        >
          <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ color: '#38A09E' }}>
            Fresh Collective managed
          </p>
          <p className="text-[15px] font-semibold text-navy-900">
            {spaceDetail.name} is available to active Fresh Collective Creators.
          </p>
          <p className="mt-2 text-[14px] leading-relaxed text-black">
            Access is managed automatically by Fresh Collective and cannot be changed here.
          </p>
        </div>
      )}

      {spaceDetail && (
        <SettingsTabbedShell
          spaceDetail={spaceDetail}
          atmosphereNames={atmosphereNames}
          buildOptions={buildOptions}
        />
      )}

    </div>
  )
}
