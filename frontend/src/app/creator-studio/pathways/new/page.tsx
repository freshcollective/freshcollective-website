import Link from 'next/link'
import { redirect } from 'next/navigation'
import { getActiveCreatorSpace } from '@/lib/serverApi'
import NewPathwayClient from './NewPathwayClient'

export default async function NewPathwayPage() {
  const activeSpace = await getActiveCreatorSpace()

  if (!activeSpace) {
    redirect('/creator-studio/pathways')
  }

  return (
    <div className="max-w-2xl px-8 py-8 md:px-10 md:py-10">
      <div className="mb-8">
        <Link
          href="/creator-studio/pathways"
          className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-slate-500 transition-colors hover:text-teal-700"
        >
          ← Back to Pathways
        </Link>
        <p
          className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          {activeSpace.name}
        </p>
        <h1 className="mt-1.5 font-serif text-2xl text-navy-900 md:text-3xl">Create pathway</h1>
      </div>

      <NewPathwayClient spaceSlug={activeSpace.slug} />
    </div>
  )
}
