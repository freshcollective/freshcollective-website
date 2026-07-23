import Link from 'next/link'
import {
  getActiveCreatorSpace,
  getCreatorSpace,
} from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveSettingsForm from './CollectiveSettingsForm'
import GuidancePanelForm from './GuidancePanelForm'


export default async function SettingsPage() {
  const primarySpace = await getActiveCreatorSpace()

  let spaceDetail: CreatorSpaceDetail | null = null
  if (primarySpace) {
    try {
      spaceDetail = (await getCreatorSpace(primarySpace.slug)) as CreatorSpaceDetail | null
    } catch (err) {
      // Log a useful development error but do NOT blank the page.
      console.error(`[creator-studio/settings] getCreatorSpace failed for ${primarySpace.slug}:`, err)
    }
  }

  if (primarySpace && !spaceDetail) {
    // Backend returned null (usually a 500). Log a clear error but continue
    // rendering the page chrome so the writer isn't stuck on a blank screen.
    console.error(
      `[creator-studio/settings] Space detail could not be loaded for slug=${primarySpace.slug}. ` +
      `Check the backend logs; the panels that depend on it will show local error states.`,
    )
  }

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Settings</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#000000' }}>
          Manage your collective details, member experience, and visibility.
        </p>
      </div>

      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Set up your collective first to access its settings.
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
        <div className="space-y-5">
          {/* Existing settings form — identity, about, banner, visibility, pricing, creator profile.
              For auto-managed collectives (World Builders) the form itself hides the visibility
              and pricing sections; all other fields (identity, about, timezone, themes, Member Hub)
              stay editable. The backend refuses any change to protected fields as a safety net. */}
          <CollectiveSettingsForm space={spaceDetail} />

          {/* Migrated from Setup — Member experience "Important panel" */}
          <section
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(56,160,158,0.18)', borderTop: '3px solid rgba(191,152,48,0.55)' }}
          >
            <div className="px-6 pt-6 pb-1">
              <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Member Hub</h2>
              <p className="mb-5 text-[14px] text-black">
                Choose the information members see in the Member Hub displayed throughout your collective.
              </p>
            </div>
            <div className="px-6 pb-6">
              <div className="mb-5 flex items-center gap-2.5">
                <div
                  className="h-[2px] w-5 rounded-full"
                  style={{ background: 'linear-gradient(90deg, #BF9830 0%, transparent 100%)' }}
                />
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-black">
                  Important panel
                </p>
              </div>
              <GuidancePanelForm space={spaceDetail} />
            </div>
          </section>
        </div>
      )}

    </div>
  )
}
