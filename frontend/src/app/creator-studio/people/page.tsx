import Link from 'next/link'
import { getActiveCreatorSpace, getSpaceMembers } from '@/lib/serverApi'
import type { MemberProfile } from '@/types/platform'
import PeopleClient from './PeopleClient'

export default async function CreatorPeoplePage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    return (
      <div className="max-w-3xl px-8 py-8 md:px-10 md:py-10">
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-10 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">Select a collective first.</p>
          <p className="mb-6 text-[14px] leading-relaxed text-slate-500">
            Choose a collective from the sidebar to see the people connected to it.
          </p>
          <Link
            href="/creator-studio"
            className="inline-flex items-center rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Back to Studio Home
          </Link>
        </div>
      </div>
    )
  }

  // TODO: Replace with a creator-specific members endpoint once built.
  // The public /api/spaces/{slug}/members endpoint only returns active members
  // and does not include email addresses. A creator endpoint should expose all
  // membership statuses (invited, paused, removed) and member emails.
  const members: MemberProfile[] = await getSpaceMembers(activeSpace.slug)

  return <PeopleClient members={members} spaceName={activeSpace.name} />
}
