'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import type { BuildYourCollectiveOptions } from '@/lib/build-your-collective/types'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveHomePanelSafe from '../assets/CollectiveHomePanelSafe'
import CollectiveSettingsForm from './CollectiveSettingsForm'
import DangerZone from './DangerZone'
import GuidancePanelForm from './GuidancePanelForm'
import OperatingDetailsForm from './OperatingDetailsForm'

export type SettingsTab = 'place' | 'details' | 'visibility' | 'pricing' | 'about' | 'members'

const DEFAULT_TAB: SettingsTab = 'place'

const TAB_ORDER: { key: SettingsTab; label: string; helper?: string }[] = [
  { key: 'place',      label: 'Place & Feel', helper: 'How do you want your place to feel? Island, atmosphere and colour palette.' },
  { key: 'details',    label: 'Details',      helper: 'The name, tagline, description and operating details that define this collective.' },
  { key: 'visibility', label: 'Visibility',   helper: 'Who can find and join this collective.' },
  { key: 'pricing',    label: 'Pricing',      helper: 'What people will understand about the cost before joining.' },
  { key: 'about',      label: 'About Page',   helper: 'This is the public page people see before joining your collective. Use it to explain what the collective is, who it is for and what people can expect.' },
  { key: 'members',    label: 'Member Hub',   helper: 'Choose what members see when they enter this collective.' },
]

function isValidTab(v: string | null): v is SettingsTab {
  return v === 'place' || v === 'details' || v === 'visibility' || v === 'pricing'
    || v === 'about' || v === 'members'
}

/** Accept older bookmarks / focus links that used the previous key.
 *  ``?tab=artwork`` was the old name for what is now ``?tab=place``. */
function normalizeTabParam(v: string | null): SettingsTab {
  if (v === 'artwork') return 'place'
  return isValidTab(v) ? v : DEFAULT_TAB
}

interface Props {
  spaceDetail: CreatorSpaceDetail
  atmosphereNames: string[]
  buildOptions: BuildYourCollectiveOptions | null
}

/**
 * SettingsTabbedShell — client wrapper that owns tab state and
 * dispatches to the correct rendering path.
 *
 *  - Details / Visibility / Pricing / About: routed through the single
 *    ``CollectiveSettingsForm`` (kept mounted so in-flight state
 *    survives tab switches).
 *  - Member Hub: ``GuidancePanelForm`` renders here with its own save.
 *  - Artwork: ``CollectiveHomePanel`` (presentational — links out to
 *    the collective builder for actual editing).
 */
export default function SettingsTabbedShell({
  spaceDetail, atmosphereNames, buildOptions,
}: Props) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [tab, setTab] = useState<SettingsTab>(() => normalizeTabParam(searchParams.get('tab')))

  // Sync tab state to the URL when it changes elsewhere (e.g. Home
  // page focus links point to specific tabs). Keeps browser back /
  // forward + shareable bookmarks working.
  useEffect(() => {
    const fromUrl = normalizeTabParam(searchParams.get('tab'))
    if (fromUrl !== tab) setTab(fromUrl)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  function selectTab(next: SettingsTab) {
    setTab(next)
    const params = new URLSearchParams(searchParams.toString())
    if (next === DEFAULT_TAB) params.delete('tab')
    else params.set('tab', next)
    const qs = params.toString()
    router.replace(qs ? `?${qs}` : '?', { scroll: false })
  }

  void buildOptions

  const activeHelper = TAB_ORDER.find((t) => t.key === tab)?.helper

  return (
    <>
      {/* ── Tab bar ── */}
      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {TAB_ORDER.map(({ key, label }) => {
          const isActive = key === tab
          return (
            <button
              key={key}
              type="button"
              onClick={() => selectTab(key)}
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
              {label}
            </button>
          )
        })}
      </div>

      {/* Per-tab helper copy */}
      {activeHelper && (
        <p
          className="mb-6 max-w-2xl text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
        >
          {activeHelper}
        </p>
      )}

      {/* Place & Feel — the emotional / visual identity of the
          Collective. Island (internally the Atlas Location) +
          atmosphere + colour palette. Presentational: edits happen
          in the build-your-collective flow. */}
      {tab === 'place' && (
        <div className="mb-5">
          <CollectiveHomePanelSafe
            slug={spaceDetail.slug}
            location={spaceDetail.location ?? null}
            atmosphereNames={atmosphereNames}
            colourPalette={spaceDetail.colour_palette ?? null}
          />
        </div>
      )}

      {/* Details tab — main identity/settings form PLUS the
          "Where does this Collective operate?" section
          (OperatingDetailsForm). The operating details are the
          real-world / practical settings and are deliberately kept
          apart from the island / atmosphere / palette on Place & Feel. */}
      {tab === 'details' && (
        <div className="mb-5">
          <OperatingDetailsForm space={spaceDetail} />
        </div>
      )}

      {/* Member Hub tab — GuidancePanelForm with its own save flow. */}
      {tab === 'members' && (
        <GuidancePanelForm space={spaceDetail} />
      )}

      {/* Main settings form — kept mounted so in-flight field state
          survives tab switches. Internally conditional on `tab` prop. */}
      <div className={tab === 'members' || tab === 'place' ? 'hidden' : ''}>
        <CollectiveSettingsForm
          space={spaceDetail}
          tab={tab === 'members' || tab === 'place' ? 'details' : tab}
        />
      </div>

      {/* Danger zone — draft-Collective permanent delete. Renders only
          for drafts; the component self-hides for active/archived
          Collectives (archive lifecycle for those is a separate
          future feature). Always at the bottom, regardless of active
          tab, so a creator can find it without hunting. */}
      <DangerZone
        slug={spaceDetail.slug}
        name={spaceDetail.name}
        status={spaceDetail.status}
      />
    </>
  )
}
