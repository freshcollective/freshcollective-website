import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorSpace } from '@/lib/serverApi'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveSettingsForm from './CollectiveSettingsForm'

export default async function SettingsPage() {
  const primarySpace = await getActiveCreatorSpace()
  const spaceDetail: CreatorSpaceDetail | null = primarySpace
    ? await getCreatorSpace(primarySpace.slug)
    : null

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
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Manage your collective details, visibility, and creator profile.
        </p>
      </div>

      {!primarySpace && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Set up your collective first to access its settings.
          </p>
          <Link
            href="/creator-studio/create"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create collective
          </Link>
        </div>
      )}

      {spaceDetail && <CollectiveSettingsForm space={spaceDetail} />}

    </div>
  )
}
