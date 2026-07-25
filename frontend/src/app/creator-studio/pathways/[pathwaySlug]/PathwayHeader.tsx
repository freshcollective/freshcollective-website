import Link from 'next/link'
import type { CreatorPathway } from '@/types/platform'

type Tab = 'content' | 'settings' | 'manual-releases' | 'about'

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  active: 'Published',
  coming_soon: 'Coming soon',
  archived: 'Archived',
}

interface Props {
  active: Tab
  spaceSlug: string
  spaceName: string
  pathway: CreatorPathway
  /** When true, the "Manual releases" tab is surfaced. Otherwise it's
   *  hidden because there are no manual-release steps on the pathway. */
  showManualReleases: boolean
}

/**
 * Shared header for every pathway sub-page in Creator Studio.
 * Renders the back link, collective label, pathway title, status pill,
 * and a compact tab bar (Content / Settings / [Manual releases] +
 * Preview action) so Creators always know where they are.
 */
export default function PathwayHeader({
  active, spaceSlug, spaceName, pathway, showManualReleases,
}: Props) {
  const tabs: { key: Tab; label: string; href: string }[] = [
    { key: 'content',  label: 'Content',  href: `/creator-studio/pathways/${pathway.slug}` },
    { key: 'settings', label: 'Settings', href: `/creator-studio/pathways/${pathway.slug}/settings` },
    { key: 'about',    label: 'About',    href: `/creator-studio/pathways/${pathway.slug}/about` },
  ]
  if (showManualReleases) {
    tabs.push({
      key: 'manual-releases',
      label: 'Manual releases',
      href: `/creator-studio/pathways/${pathway.slug}/manual-releases`,
    })
  }

  const previewHref = `/spaces/${spaceSlug}/pathways/${pathway.slug}`

  return (
    <div className="mb-6">
      <Link
        href="/creator-studio/pathways"
        className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-black transition-colors hover:text-teal-700"
      >
        ← Back to Pathways
      </Link>
      <p
        className="mt-4 text-[11px] font-semibold uppercase tracking-[0.16em]"
        style={{ color: '#38A09E' }}
      >
        {spaceName}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        <h1 className="font-serif text-2xl text-navy-900 md:text-3xl">
          {pathway.title}
        </h1>
        <span
          className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
          style={{
            background: 'rgba(56,160,158,0.10)',
            color: '#0f766e',
            border: '1px solid rgba(56,160,158,0.20)',
          }}
        >
          {STATUS_LABEL[pathway.status] ?? pathway.status}
        </span>
      </div>

      {/* Tab bar + Preview action */}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {tabs.map((tab) => {
            const isActive = tab.key === active
            return (
              <Link
                key={tab.key}
                href={tab.href}
                aria-current={isActive ? 'page' : undefined}
                className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
                style={
                  isActive
                    ? {
                        background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                        color: '#ffffff',
                        border: '1px solid rgba(56,160,158,0.35)',
                      }
                    : {
                        background: 'white',
                        color: '#0f766e',
                        border: '1px solid rgba(56,160,158,0.20)',
                      }
                }
              >
                {tab.label}
              </Link>
            )
          })}
        </div>
        <a
          href={previewHref}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-border bg-white px-4 py-1.5 text-[13px] font-medium text-black transition-colors hover:border-teal-200 hover:text-teal-700"
        >
          Preview <span aria-hidden="true">↗</span>
        </a>
      </div>
    </div>
  )
}
