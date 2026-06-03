import { getActiveCreatorSpace, getCreatorResources } from '@/lib/serverApi'
import type { CreatorResource } from '@/types/platform'
import ResourcesManager from './ResourcesManager'

export default async function ResourcesPage() {
  const space = await getActiveCreatorSpace()
  const resources: CreatorResource[] = space ? await getCreatorResources(space.slug) : []

  return (
    <div className="w-full max-w-[1180px] px-8 py-8 md:px-10 md:py-10">

      <div className="mb-8">
        <p
          className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: '#38A09E' }}
        >
          Creator Studio
        </p>
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">Resources</h1>
        <p className="mt-2 text-[15px] leading-relaxed" style={{ color: '#334155' }}>
          Add standalone links, files, guides, and tools for your members.
        </p>
      </div>

      {/* Pathway resources info */}
      <div
        className="mb-6 flex items-start gap-3 rounded-2xl border px-5 py-4"
        style={{ borderColor: 'rgba(56,160,158,0.25)', background: 'rgba(56,160,158,0.04)' }}
      >
        <span className="mt-0.5 text-[16px]">◫</span>
        <div>
          <p className="text-[13px] font-semibold text-navy-900">Pathway resources</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-slate-500">
            Resources attached inside pathway steps are managed within each pathway. They appear
            automatically on the member Resources page, grouped by pathway, for members who have
            access.
          </p>
        </div>
      </div>

      {!space ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-8 text-center">
          <p className="mb-2 text-[16px] font-semibold text-navy-900">No collective yet</p>
          <p className="text-[14px] leading-relaxed text-slate-500">
            Set up your collective first to start adding resources.
          </p>
        </div>
      ) : (
        <ResourcesManager spaceSlug={space.slug} initialResources={resources} />
      )}

    </div>
  )
}
