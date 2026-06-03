import { getSpace, getSpaceResources, getSpaceMembers } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type { CollectiveResource, MemberProfile, SpaceResponse } from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  link:     'Link',
  file:     'File',
  replay:   'Replay',
  guide:    'Guide',
  template: 'Template',
  audio:    'Audio',
  video:    'Video',
  other:    'Resource',
}

const RESOURCE_TYPE_ICONS: Record<string, string> = {
  link:     '🔗',
  file:     '📄',
  replay:   '▶',
  guide:    '📖',
  template: '📋',
  audio:    '🎧',
  video:    '🎬',
  other:    '◫',
}

const RESOURCE_ACTION_LABELS: Record<string, string> = {
  link:     'Open →',
  file:     'Download →',
  replay:   'Watch replay →',
  guide:    'View guide →',
  template: 'Open template →',
  audio:    'Listen →',
  video:    'Watch →',
  other:    'Open →',
}

function ResourceCard({ resource }: { resource: CollectiveResource }) {
  const typeLabel  = RESOURCE_TYPE_LABELS[resource.resource_type]  ?? 'Resource'
  const typeIcon   = RESOURCE_TYPE_ICONS[resource.resource_type]   ?? '◫'
  const actionLabel = RESOURCE_ACTION_LABELS[resource.resource_type] ?? 'Open →'

  const resolvedUrl = resource.url
    ? (resource.url.startsWith('/api/uploads/')
        ? resolveMediaUrl(resource.url)
        : resource.url)
    : null

  const sourceMeta = resource.file_name
    ? resource.file_name
    : resolvedUrl
      ? (() => { try { return new URL(resolvedUrl).hostname } catch { return resolvedUrl } })()
      : null

  return (
    <div
      className="overflow-hidden rounded-2xl bg-white transition-shadow hover:shadow-sm"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}
    >
      {/* Teal accent top stripe */}
      <div
        className="h-[3px] w-full"
        style={{ background: 'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.15) 100%)' }}
      />

      <div className="px-5 py-5">
        {/* Type pill */}
        <div className="mb-3 flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
            style={{ background: 'rgba(56,160,158,0.10)', color: '#1E6E6C' }}
          >
            <span>{typeIcon}</span>
            {typeLabel}
          </span>
        </div>

        <h3 className="mb-1.5 text-[15px] font-semibold leading-snug text-navy-900">
          {resource.title}
        </h3>

        {resource.description && (
          <p className="mb-3 line-clamp-2 text-[13px] leading-relaxed text-slate-500">
            {resource.description}
          </p>
        )}

        {sourceMeta && (
          <p className="mb-4 truncate text-[11.5px] text-slate-400">{sourceMeta}</p>
        )}

        {resolvedUrl ? (
          <a
            href={resolvedUrl}
            target={resource.file_name ? undefined : '_blank'}
            rel={resource.file_name ? undefined : 'noopener noreferrer'}
            download={resource.file_name ? resource.file_name : undefined}
            className="inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {actionLabel}
          </a>
        ) : (
          <span className="inline-flex items-center rounded-xl border border-slate-200 px-4 py-2 text-[13px] text-slate-400">
            No link available
          </span>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
      <p className="mb-1 text-[16px] font-semibold text-navy-900">No resources yet</p>
      <p className="text-[14px] leading-relaxed text-slate-500">
        Resources shared by the creator will appear here.
      </p>
    </div>
  )
}

export default async function SpaceResourcesPage({ params }: Props) {
  const { slug } = await params

  const [space, resources, members]: [SpaceResponse | null, CollectiveResource[], MemberProfile[]] =
    await Promise.all([getSpace(slug), getSpaceResources(slug), getSpaceMembers(slug)])

  const memberCount = members.filter((m) => m.space_role === 'learner').length
  const leaderCount = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">

      {/* ── Main column ── */}
      <div className="min-w-0">

        {/* Intro card */}
        <div
          className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
          style={{
            background: '#071824',
            border: '1px solid rgba(66,199,198,0.10)',
            boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
          }}
        >
          <div
            className="mb-3 h-[2px] w-8 rounded-full"
            style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
          />
          <h2 className="mb-2 leading-snug">
            <span
              className="inline-block text-2xl font-semibold"
              style={{
                background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}
            >
              Resources
            </span>
          </h2>
          <p className="text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.72)' }}>
            Guides, links, replays, and tools to support your journey.
          </p>
        </div>

        {/* Resource grid */}
        {resources.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2">
            {resources.map((resource) => (
              <ResourceCard key={resource.id} resource={resource} />
            ))}
          </div>
        ) : (
          <EmptyState />
        )}

      </div>

      {/* ── Right sidebar (desktop only) ── */}
      <aside className="hidden lg:block">
        <div className="sticky top-6">
          <CollectiveSidebarPanel
            space={space}
            memberCount={memberCount}
            leaderCount={leaderCount}
          />
        </div>
      </aside>

    </div>
  )
}
