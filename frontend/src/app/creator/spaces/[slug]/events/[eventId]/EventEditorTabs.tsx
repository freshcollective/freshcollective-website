'use client'

import { useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { useToast } from '@/components/platform'
import type {
  CreatorEvent,
  CreatorGatheringSeriesSummary,
  CreatorMediaAsset,
  CreatorOfferPageSummary,
  CreatorPathway,
  CreatorResource,
  EventBooking,
  PathwayAboutBlock,
} from '@/types/platform'
import EventForm from '../EventForm'
import EventManagePanel from './EventManagePanel'
import OfferPagesShortcut from '@/app/creator-studio/offers/OfferPagesShortcut'
import SeriesChildOfferHint from '@/app/creator-studio/offers/SeriesChildOfferHint'
import AboutPageEditor from '@/app/creator-studio/pathways/[pathwaySlug]/AboutPageEditor'

/**
 * Creator Gathering editor with Settings | About tabs (MF7).
 *
 *   Settings — existing form + Offer Page shortcut + attendees/roster
 *              panel (unchanged; every existing knob preserved).
 *   About    — rich block editor writing to the polymorphic
 *              ``pathway_about_blocks`` rows with ``owner_kind='event'``,
 *              added in migration 113 + wired up in MF2.
 *
 * Structure mirrors ``SeriesEditorClient`` — tabs are client-only
 * state; the About tab lazy-loads its own blocks + media + resources
 * so the Settings-tab render path stays fast.
 */

interface SpaceMember {
  id: string
  display_name: string
}

interface Props {
  spaceSlug: string
  event: CreatorEvent
  bookings: EventBooking[]
  members: SpaceMember[]
  pathways: CreatorPathway[]
  series: CreatorGatheringSeriesSummary[]
  offers: CreatorOfferPageSummary[]
  paidOffersEnabled: boolean
}

type EventTab = 'settings' | 'about'

export default function EventEditorTabs({
  spaceSlug, event, bookings, members, pathways, series, offers, paidOffersEnabled,
}: Props) {
  const [tab, setTab] = useState<EventTab>('settings')

  return (
    <>
      <EventTabsBar tab={tab} onChange={setTab} />

      {tab === 'settings' && (
        <SettingsTab
          spaceSlug={spaceSlug}
          event={event}
          bookings={bookings}
          members={members}
          pathways={pathways}
          series={series}
          offers={offers}
          paidOffersEnabled={paidOffersEnabled}
        />
      )}

      {tab === 'about' && (
        <EventAboutTab spaceSlug={spaceSlug} event={event} />
      )}
    </>
  )
}

function EventTabsBar({
  tab, onChange,
}: {
  tab: EventTab
  onChange: (t: EventTab) => void
}) {
  const items: { key: EventTab; label: string }[] = [
    { key: 'settings', label: 'Settings' },
    { key: 'about',    label: 'About' },
  ]
  return (
    <div className="mb-6 flex gap-1 border-b border-slate-200">
      {items.map((it) => {
        const active = it.key === tab
        return (
          <button
            key={it.key}
            type="button"
            onClick={() => onChange(it.key)}
            className={`-mb-px inline-flex items-center border-b-2 px-4 py-2.5 text-[13px] font-semibold transition-colors ${
              active
                ? 'border-teal-500 text-teal-700'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
            aria-current={active ? 'page' : undefined}
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )
}

function SettingsTab({
  spaceSlug, event, bookings, members, pathways, series, offers, paidOffersEnabled,
}: Props) {
  const parentSeries = event.series_id
    ? series.find((s) => s.id === event.series_id) ?? null
    : null

  return (
    <>
      <EventForm spaceSlug={spaceSlug} event={event} pathways={pathways} series={series} />

      <div className="mt-6">
        {parentSeries ? (
          <SeriesChildOfferHint
            seriesId={parentSeries.id}
            seriesTitle={parentSeries.title}
            seriesSlug={parentSeries.slug}
            offers={offers}
            paidOffersEnabled={paidOffersEnabled}
          />
        ) : (
          <OfferPagesShortcut
            targetKind="gathering"
            targetId={event.id}
            targetTitle={event.title}
            offers={offers}
            paidOffersEnabled={paidOffersEnabled}
            variant="compact"
          />
        )}
      </div>

      <EventManagePanel
        event={event}
        spaceSlug={spaceSlug}
        initialBookings={bookings}
        members={members}
      />
    </>
  )
}

function EventAboutTab({
  spaceSlug, event,
}: {
  spaceSlug: string
  event: CreatorEvent
}) {
  const { show } = useToast()
  const [blocks, setBlocks] = useState<PathwayAboutBlock[] | null>(null)
  const [mediaAssets, setMediaAssets] = useState<CreatorMediaAsset[]>([])
  const [resources, setResources] = useState<CreatorResource[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/events/${event.id}/about-blocks`),
        { credentials: 'include' },
      ).then((r) => r.ok ? r.json() as Promise<PathwayAboutBlock[]> : []),
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/media`), { credentials: 'include' })
        .then((r) => r.ok ? r.json() as Promise<CreatorMediaAsset[]> : []),
      fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/resources`), { credentials: 'include' })
        .then((r) => r.ok ? r.json() as Promise<CreatorResource[]> : []),
    ])
      .then(([b, m, r]) => {
        if (cancelled) return
        setBlocks(b)
        setMediaAssets(m)
        setResources(r)
      })
      .catch((e) => {
        if (cancelled) return
        setError(String(e?.message ?? e))
        show('Couldn\u2019t load the About content.', { tone: 'error' })
      })
    return () => { cancelled = true }
  }, [spaceSlug, event.id, show])

  if (error && blocks === null) {
    return (
      <section className="mb-6 rounded-2xl border border-red-100 bg-red-50 p-6 text-[13px] text-red-800">
        Couldn&apos;t load the About content: {error}
      </section>
    )
  }
  if (blocks === null) {
    return (
      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 text-[13px] text-slate-500">
        Loading…
      </section>
    )
  }

  return (
    <section className="mb-6">
      <AboutPageEditor
        spaceSlug={spaceSlug}
        initialBlocks={blocks}
        mediaAssets={mediaAssets}
        resources={resources}
        blocksApiUrl={apiUrl(
          `/api/creator/spaces/${spaceSlug}/events/${event.id}/about-blocks`,
        )}
        previewHref={`/spaces/${spaceSlug}/events/${event.id}`}
        headingTitle="About this Gathering"
        headingBody="Build the page members see for this Gathering. Same block types as Pathway About — text, images, callouts, links, buttons, columns."
        emptyStateHeading="No about content yet"
        emptyStateBody="Add your first block to explain what this Gathering is, who it&rsquo;s for, and what to expect."
      />
    </section>
  )
}
