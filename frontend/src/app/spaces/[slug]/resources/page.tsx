import { getSpace, getSpaceResources, getSpaceMembers } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import CollectiveSidebarPanel from '@/components/spaces/CollectiveSidebarPanel'
import type {
  CollectiveResource,
  PathwayResourceItem,
  PathwayResourceGroup,
  SpaceResponse,
  MemberProfile,
} from '@/types/platform'

interface Props {
  params: Promise<{ slug: string }>
}

// ---------------------------------------------------------------------------
// Two-accent system: teal for shared resources, gold for pathway resources
// ---------------------------------------------------------------------------

const TEAL_ACCENT = {
  stripe:      'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.15) 100%)',
  pillBg:      'rgba(56,160,158,0.10)',
  pillText:    '#1E6E6C',
  labelBg:     'rgba(56,160,158,0.10)',
  labelText:   '#1E6E6C',
  headingLine: '#38A09E',
  btnBg:       'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
}

const GOLD_ACCENT = {
  stripe:      'linear-gradient(90deg, #D6B13F 0%, rgba(214,177,63,0.15) 100%)',
  pillBg:      'rgba(226,193,79,0.14)',
  pillText:    '#7A5A00',
  labelBg:     'rgba(226,193,79,0.14)',
  labelText:   '#7A5A00',
  headingLine: '#D6B13F',
  btnBg:       '#0F3050',
}

type Accent = typeof TEAL_ACCENT

// ---------------------------------------------------------------------------
// Resource type maps
// ---------------------------------------------------------------------------

const RESOURCE_TYPE_LABELS: Record<string, string> = {
  link:     'Link',
  file:     'File',
  replay:   'Replay',
  guide:    'Guide',
  template: 'Template',
  audio:    'Audio',
  video:    'Video',
  pdf:      'PDF',
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
  pdf:      '📄',
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
  pdf:      'Download →',
  other:    'Open →',
}

function resolveResourceUrl(url: string | null): string | null {
  if (!url) return null
  return url.startsWith('/api/uploads/') ? resolveMediaUrl(url) : url
}

function sourceMeta(url: string | null, fileName: string | null): string | null {
  if (fileName) return fileName
  if (!url) return null
  try { return new URL(url).hostname } catch { return url }
}

// ---------------------------------------------------------------------------
// ResourceCard — accepts an accent object so shared vs pathway cards differ
// ---------------------------------------------------------------------------

function ResourceCard({
  resource,
  accent = TEAL_ACCENT,
}: {
  resource: CollectiveResource | PathwayResourceItem
  accent?: Accent
}) {
  const typeLabel   = RESOURCE_TYPE_LABELS[resource.resource_type] ?? 'Resource'
  const typeIcon    = RESOURCE_TYPE_ICONS[resource.resource_type]  ?? '◫'
  const actionLabel = RESOURCE_ACTION_LABELS[resource.resource_type] ?? 'Open →'

  const resolvedUrl = resolveResourceUrl(resource.url)
  const meta = sourceMeta(resolvedUrl, resource.file_name ?? null)
  const isFile = !!resource.file_name
  const stepTitle = 'step_title' in resource ? resource.step_title : null

  return (
    <div
      className="overflow-hidden rounded-2xl bg-white transition-shadow hover:shadow-sm"
      style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}
    >
      {/* Accent top stripe */}
      <div className="h-[3px] w-full" style={{ background: accent.stripe }} />

      <div className="px-5 py-5">
        {/* Type pill */}
        <div className="mb-3">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
            style={{ background: accent.pillBg, color: accent.pillText }}
          >
            <span>{typeIcon}</span>
            {typeLabel}
          </span>
        </div>

        <h3 className="mb-1.5 text-[15px] font-semibold leading-snug text-navy-900">
          {resource.title}
        </h3>

        {resource.description && (
          <p className="mb-2 line-clamp-2 text-[13px] leading-relaxed text-slate-500">
            {resource.description}
          </p>
        )}

        {stepTitle && (
          <p className="mb-1 text-[11.5px] text-slate-400">From: {stepTitle}</p>
        )}

        {meta && (
          <p className="mb-4 truncate text-[11.5px] text-slate-400">{meta}</p>
        )}

        {resolvedUrl ? (
          <a
            href={resolvedUrl}
            target={isFile ? undefined : '_blank'}
            rel={isFile ? undefined : 'noopener noreferrer'}
            download={isFile ? (resource.file_name ?? undefined) : undefined}
            className="inline-flex items-center rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-80"
            style={{ background: accent.btnBg }}
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

// ---------------------------------------------------------------------------
// Section heading — teal or pathway accent
// ---------------------------------------------------------------------------

function SectionHeading({
  children,
  accent = TEAL_ACCENT,
}: {
  children: React.ReactNode
  accent?: Accent
}) {
  return (
    <div className="mb-5 flex items-center gap-3">
      <div
        className="h-4 w-[3px] rounded-full shrink-0"
        style={{ background: accent.headingLine }}
      />
      <h2 className="text-[16px] font-semibold text-navy-900">{children}</h2>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pathway group — picks its accent from pathway_id hash
// ---------------------------------------------------------------------------

function PathwayGroup({ group }: { group: PathwayResourceGroup }) {
  return (
    <div
      className="mb-6 rounded-2xl px-5 py-5"
      style={{
        background: 'rgba(226,193,79,0.07)',
        border: '1px solid rgba(214,177,63,0.30)',
      }}
    >
      {/* Pathway heading row */}
      <div className="mb-4 flex items-center gap-2.5">
        <div
          className="h-[14px] w-[3px] shrink-0 rounded-full"
          style={{ background: GOLD_ACCENT.headingLine }}
        />
        <h3 className="text-[14px] font-semibold text-navy-900">{group.pathway_title}</h3>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
          style={{ background: GOLD_ACCENT.labelBg, color: GOLD_ACCENT.labelText }}
        >
          {group.access_label}
        </span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {group.resources.map((r) => (
          <ResourceCard key={r.id} resource={r} accent={GOLD_ACCENT} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white py-16 text-center">
      <p className="mb-1 text-[16px] font-semibold text-navy-900">No resources yet</p>
      <p className="text-[14px] leading-relaxed text-slate-500">
        Resources shared by the creator or attached to your pathways will appear here.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function SpaceResourcesPage({ params }: Props) {
  const { slug } = await params

  const [space, aggregated, members]: [SpaceResponse | null, Awaited<ReturnType<typeof getSpaceResources>>, MemberProfile[]] =
    await Promise.all([getSpace(slug), getSpaceResources(slug), getSpaceMembers(slug)])

  const { standalone_resources, pathway_resource_groups } = aggregated

  const memberCount = members.filter((m) => m.space_role === 'learner').length
  const leaderCount = members.filter((m) => m.space_role === 'creator' || m.space_role === 'moderator').length

  const hasAny = standalone_resources.length > 0 || pathway_resource_groups.length > 0

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

        {!hasAny ? (
          <EmptyState />
        ) : (
          <div>
            {/* ── Shared resources (teal) ── */}
            {standalone_resources.length > 0 && (
              <section className="mb-10">
                <SectionHeading accent={TEAL_ACCENT}>Shared resources</SectionHeading>
                <p className="mb-5 text-[13px] text-slate-500">
                  Resources shared by the creator for this collective.
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                  {standalone_resources.map((r) => (
                    <ResourceCard key={r.id} resource={r} accent={TEAL_ACCENT} />
                  ))}
                </div>
              </section>
            )}

            {/* ── Pathway resources (gold accent) ── */}
            {pathway_resource_groups.length > 0 && (
              <section>
                <SectionHeading accent={GOLD_ACCENT}>From your pathways</SectionHeading>
                {pathway_resource_groups.map((group) => (
                  <PathwayGroup key={group.pathway_id} group={group} />
                ))}
              </section>
            )}
          </div>
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
