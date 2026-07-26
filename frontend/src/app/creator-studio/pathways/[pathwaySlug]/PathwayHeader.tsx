import Link from 'next/link'
import type { CreatorPathway, CreatorSection, CreatorStep } from '@/types/platform'
import CollectiveArtworkHeader from '@/components/creator/CollectiveArtworkHeader'

type Tab = 'content' | 'settings' | 'manual-releases' | 'about'

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft',
  active: 'Published',
  coming_soon: 'Coming soon',
  archived: 'Archived',
}

interface Location {
  name: string
  hero_artwork_url?: string | null
  thumbnail_artwork_url?: string | null
}

interface Props {
  active: Tab
  spaceName: string
  pathway: CreatorPathway
  /** When true, the "Manual releases" tab is surfaced. */
  showManualReleases: boolean
  /** Optional collective identity feed — used by the artwork header
   *  so every pathway sub-page opens with the collective's own place
   *  around it. Missing fields degrade to sensible fallbacks. */
  location?: Location | null
  coverImageUrl?: string | null
  /** Optional counts feeding the header's meta line
   *  ("22 steps · 6 sections · Draft"). */
  steps?: CreatorStep[]
  sections?: CreatorSection[]
}

/**
 * Shared header for every pathway sub-page in Creator Studio.
 * Renders the artwork header (collective identity + pathway title +
 * meta) and a compact tab bar below (Content / Settings / About /
 * [Manual releases] + Preview action). Every sub-page opens with the
 * same anchor so the creator always knows "which collective am I in,
 * which pathway am I editing, and where in it am I now."
 */
export default function PathwayHeader({
  active, spaceName, pathway, showManualReleases,
  location = null, coverImageUrl = null, steps, sections,
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

  const previewHref = `/creator-studio/pathways/${pathway.slug}/preview`

  const statusLabel = STATUS_LABEL[pathway.status] ?? pathway.status
  const metaParts: string[] = []
  if (steps && steps.length > 0) {
    metaParts.push(`${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`)
  }
  if (sections && sections.length > 0) {
    metaParts.push(`${sections.length} ${sections.length === 1 ? 'section' : 'sections'}`)
  }
  metaParts.push(statusLabel)

  return (
    <div className="mb-6">
      <CollectiveArtworkHeader
        collectiveName={spaceName}
        sectionTitle={pathway.title}
        meta={metaParts.join(' · ')}
        location={location}
        coverImageUrl={coverImageUrl}
        backLink={{ href: '/creator-studio/pathways', label: 'Back to Pathways' }}
      />

      {/* Tab bar + Preview action */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
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
