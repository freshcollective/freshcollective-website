import { resolveMediaUrl } from '@/lib/api'
import { ImportantPanelContent } from '@/components/spaces/ImportantPanel'
import type { SpaceResponse } from '@/types/platform'

interface Props {
  space: SpaceResponse | null
  memberCount: number
  leaderCount: number
}

function plural(n: number, singular: string, plural: string) {
  return `${n} ${n === 1 ? singular : plural}`
}

export default function CollectiveSidebarPanel({ space, memberCount, leaderCount }: Props) {
  const coverUrl = resolveMediaUrl(space?.cover_image_url)

  return (
    <div
      className="overflow-hidden rounded-2xl bg-white"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {/* Banner image — rounded top corners from parent overflow-hidden */}
      {coverUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={coverUrl}
          alt=""
          aria-hidden="true"
          className="h-32 w-full object-cover"
        />
      ) : (
        <div
          className="h-16 w-full"
          style={{
            background: 'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
          }}
        />
      )}

      <div className="px-5 pt-5 pb-1">
        {/* Stats row */}
        <div className="flex gap-6">
          <div>
            <p className="font-serif text-[22px] leading-tight" style={{ color: '#0C1826' }}>
              {memberCount}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {memberCount === 1 ? 'member' : 'members'}
            </p>
          </div>
          <div>
            <p className="font-serif text-[22px] leading-tight" style={{ color: '#0C1826' }}>
              {leaderCount}
            </p>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {leaderCount === 1 ? 'leader' : 'leaders'}
            </p>
          </div>
        </div>

        {/* Divider */}
        <div className="mt-4 h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />
      </div>

      {/* Important panel content */}
      <ImportantPanelContent
        className="px-5 pt-4 pb-6"
        startTitle={space?.guidance_start_title}
        startBody={space?.guidance_start_body}
        focusTitle={space?.guidance_focus_title}
        focusBody={space?.guidance_focus_body}
        linksTitle={space?.guidance_links_title}
        linksBody={space?.guidance_links_body}
      />
    </div>
  )
}
