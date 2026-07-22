import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPasses } from '@/lib/serverApi'
import type { AccessPassAdminSummary } from '@/types/platform'
import PassesClient from './PassesClient'

export default async function CreatorPassesPage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-black">
            Choose a collective from the sidebar to see member passes.
          </p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Dashboard
          </Link>
        </div>
      </div>
    )
  }

  const passes: AccessPassAdminSummary[] = await getCreatorPasses(activeSpace.slug)

  return (
    <PassesClient
      passes={passes}
      spaceName={activeSpace.name}
      spaceSlug={activeSpace.slug}
    />
  )
}
