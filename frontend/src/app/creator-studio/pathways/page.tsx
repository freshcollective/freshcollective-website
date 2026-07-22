import Link from 'next/link'
import { getActiveCreatorSpace, getCreatorPathways } from '@/lib/serverApi'
import type { CreatorPathway } from '@/types/platform'
import PathwaysClient from './PathwaysClient'

export default async function PathwaysPage() {
  const activeSpace = await getActiveCreatorSpace()
  const pathways: CreatorPathway[] = activeSpace
    ? await getCreatorPathways(activeSpace.slug)
    : []

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          {activeSpace && (
            <p
              className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
              style={{ color: '#38A09E' }}
            >
              {activeSpace.name}
            </p>
          )}
          <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Pathways</h1>
          <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#000000' }}>
            Create guided journeys people can move through over time.
          </p>
        </div>
        {activeSpace && (
          <Link
            href="/creator-studio/pathways/new"
            className="mt-1 shrink-0 rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            Create pathway
          </Link>
        )}
      </div>

      <PathwaysClient initialPathways={pathways} activeSpace={activeSpace} />

    </div>
  )
}
