'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import type { BuildYourCollectiveOptions } from '@/lib/build-your-collective/types'
import type { CreatorSpaceDetail } from '@/types/platform'
import CollectiveHomePanelSafe from '../assets/CollectiveHomePanelSafe'
import CollectiveSettingsForm from './CollectiveSettingsForm'
import GuidancePanelForm from './GuidancePanelForm'

export type SettingsTab = 'details' | 'visibility' | 'pricing' | 'about' | 'members' | 'artwork'

const TAB_ORDER: { key: SettingsTab; label: string; helper?: string }[] = [
  { key: 'details',    label: 'Details',    helper: 'The name, tagline, description and identity assets that define this collective.' },
  { key: 'visibility', label: 'Visibility', helper: 'Who can find and join this collective.' },
  { key: 'pricing',    label: 'Pricing',    helper: 'What people will understand about the cost before joining.' },
  { key: 'about',      label: 'About Page', helper: 'This is the public page people see before joining your collective. Use it to explain what the collective is, who it is for and what people can expect.' },
  { key: 'members',    label: 'Member Hub', helper: 'Choose what members see when they enter this collective.' },
  { key: 'artwork',    label: 'Artwork',    helper: 'Where this collective lives, and what that place feels like.' },
]

function isValidTab(v: string | null): v is SettingsTab {
  return v === 'details' || v === 'visibility' || v === 'pricing'
    || v === 'about' || v === 'members' || v === 'artwork'
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
  const initialTab = isValidTab(searchParams.get('tab')) ? (searchParams.get('tab') as SettingsTab) : 'details'
  const [tab, setTab] = useState<SettingsTab>(initialTab)

  // Sync tab state to the URL when it changes elsewhere (e.g. Home
  // page focus links point to specific tabs). Keeps browser back /
  // forward + shareable bookmarks working.
  useEffect(() => {
    const fromUrl = isValidTab(searchParams.get('tab'))
      ? (searchParams.get('tab') as SettingsTab)
      : 'details'
    if (fromUrl !== tab) setTab(fromUrl)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  function selectTab(next: SettingsTab) {
    setTab(next)
    const params = new URLSearchParams(searchParams.toString())
    if (next === 'details') params.delete('tab')
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

      {/* Artwork tab — Collective Home lives here (Location, atmosphere,
          palette, relocate). Presentational: edits happen in the
          build-your-collective flow. No banner/logo here — those live
          on the Details tab as direct identity assets. */}
      {tab === 'artwork' && (
        <div className="mb-5">
          <CollectiveHomePanelSafe
            slug={spaceDetail.slug}
            location={spaceDetail.location ?? null}
            atmosphereNames={atmosphereNames}
            colourPalette={spaceDetail.colour_palette ?? null}
          />
        </div>
      )}

      {/* Member Hub tab — GuidancePanelForm with its own save flow. */}
      {tab === 'members' && (
        <GuidancePanelForm space={spaceDetail} />
      )}

      {/* Main settings form — kept mounted so in-flight field state
          survives tab switches. Internally conditional on `tab` prop. */}
      <div className={tab === 'members' || tab === 'artwork' ? 'hidden' : ''}>
        <CollectiveSettingsForm
          space={spaceDetail}
          tab={tab === 'members' || tab === 'artwork' ? 'details' : tab}
        />
      </div>
    </>
  )
}
