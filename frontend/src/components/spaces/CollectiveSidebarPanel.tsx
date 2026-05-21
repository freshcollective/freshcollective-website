import { resolveMediaUrl } from '@/lib/api'
import ImportantPanel from '@/components/spaces/ImportantPanel'
import type { SpaceResponse } from '@/types/platform'

interface Props {
  space: SpaceResponse | null
}

export default function CollectiveSidebarPanel({ space }: Props) {
  const coverUrl = resolveMediaUrl(space?.cover_image_url)

  return (
    <div className="flex flex-col gap-4">
      {/* Banner image or navy gradient fallback */}
      <div className="overflow-hidden rounded-2xl" style={{ border: '1px solid rgba(0,0,0,0.07)' }}>
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
      </div>

      {/* Important panel */}
      <ImportantPanel
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
