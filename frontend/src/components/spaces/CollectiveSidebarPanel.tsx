import { resolveMediaUrl } from '@/lib/api'
import { ImportantPanelContent } from '@/components/spaces/ImportantPanel'
import type { SpaceResponse } from '@/types/platform'

interface Props {
  space: SpaceResponse | null
}

export default function CollectiveSidebarPanel({ space }: Props) {
  const coverUrl = resolveMediaUrl(space?.cover_image_url)

  return (
    <div
      className="overflow-hidden rounded-2xl bg-white"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {/* Banner image — rounded top corners come from parent overflow-hidden */}
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

      {/* Important panel content — no separate card wrapper */}
      <ImportantPanelContent
        className="px-5 py-6"
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
