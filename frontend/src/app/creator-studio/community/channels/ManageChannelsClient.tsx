'use client'

import { useMemo, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import { Button } from '@/components/platform'
import { PlusIcon } from '@/components/creator/PrimaryActionLink'
import type { ChannelManageDetail } from '@/lib/serverApi'
import type { CreatorEvent, CreatorPathway, MemberProfile } from '@/types/platform'

/**
 * ManageChannelsClient — caretaker home for Channel setup.
 *
 * Layout:
 *   ▸ System row (unheaded)     — Start Here, Common Room
 *   ▸ PATHWAYS group            — 🛤 channels
 *   ▸ GATHERINGS group          — 📅 channels
 *   ▸ PRIVATE group             — 🔒 channels
 *   ▸ OPEN DISCUSSIONS group    — 💬 channels
 *   ▸ Archived group (footer)   — visually muted, restorable
 *
 * Rules
 *   - No icon picker — icons are strictly type-driven server-side.
 *   - System channels show a SYSTEM badge instead of delete/archive.
 *     Start Here is fully locked; Common Room may be renamed + re-described.
 *   - Groups with no channels collapse.
 */

/** Minimal shape the Add-a-Channel picker needs — matches the
 *  ``GatheringSeriesResponse`` fields we consult. */
export interface CreatorGatheringSeries {
  id: string
  slug: string
  title: string
  status: string  // 'draft' | 'published' | 'archived'
}

interface Props {
  spaceSlug: string
  initialChannels: ChannelManageDetail[]
  members: MemberProfile[]
  pathways: CreatorPathway[]
  events: CreatorEvent[]
  series: CreatorGatheringSeries[]
}

type ChannelType = 'open' | 'private' | 'pathway' | 'gathering' | 'series'

/** What the creator picks. Three arrangements, not five types: the
 *  old list made "which experience" part of the channel's identity,
 *  which is why a channel could only ever name one. */
type Arrangement = 'open' | 'private' | 'linked'

export interface ExperienceRef {
  type: 'pathway' | 'gathering' | 'series'
  id: string
}

interface CreateForm {
  name: string
  arrangement: Arrangement
  description: string
  linked_experiences: ExperienceRef[]
  member_posting_allowed: boolean
  polls_allowed: boolean
  initial_member_user_ids: string[]
}

const EMPTY_CREATE: CreateForm = {
  name: '',
  arrangement: 'open',
  description: '',
  linked_experiences: [],
  member_posting_allowed: true,
  polls_allowed: true,
  initial_member_user_ids: [],
}

/** The stored ``channel_type`` for a linked channel. The backend keeps
 *  the pathway/gathering/series vocabulary for icons and grouping, so
 *  a mixed channel takes the kind of its first experience — the
 *  arrangement above is what the creator actually reasons about. */
function storedType(form: CreateForm): ChannelType {
  if (form.arrangement !== 'linked') return form.arrangement
  return form.linked_experiences[0]?.type ?? 'gathering'
}

const GROUP_ORDER: string[] = ['SERIES', 'PATHWAYS', 'GATHERINGS', 'PRIVATE', 'OPEN DISCUSSIONS']

export default function ManageChannelsClient({
  spaceSlug,
  initialChannels,
  members,
  pathways,
  events,
  series,
}: Props) {
  const router = useRouter()
  const [channels, setChannels] = useState<ChannelManageDetail[]>(initialChannels)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<CreateForm>(EMPTY_CREATE)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [broadenPrompt, setBroadenPrompt] = useState<{
    channelId: string
    patch: Record<string, unknown>
    message: string
  } | null>(null)
  const [, startTransition] = useTransition()

  const eligiblePathways = useMemo(
    () => pathways.filter((p) => p.status !== 'archived'),
    [pathways],
  )
  const eligibleEvents = useMemo(
    () => events.filter((e) => e.status !== 'archived' && e.status !== 'cancelled'),
    [events],
  )
  const eligibleSeries = useMemo(
    () => series.filter((s) => s.status !== 'archived'),
    [series],
  )
  const memberOptions = useMemo(
    () => members.slice().sort((a, b) => a.display_name.localeCompare(b.display_name)),
    [members],
  )

  // Partition channels — system first (unheaded), then grouped, then archived.
  const system = channels.filter((c) => c.is_system && !c.is_archived)
  const active = channels.filter((c) => !c.is_system && !c.is_archived)
  const archived = channels.filter((c) => c.is_archived)

  const grouped = new Map<string, ChannelManageDetail[]>()
  for (const c of active) {
    const key = c.group_label ?? 'OPEN DISCUSSIONS'
    const arr = grouped.get(key) ?? []
    arr.push(c)
    grouped.set(key, arr)
  }
  const orderedGroupKeys = [
    ...GROUP_ORDER.filter((k) => grouped.has(k)),
    ...Array.from(grouped.keys()).filter((k) => !GROUP_ORDER.includes(k)).sort(),
  ]

  async function refresh() {
    const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/channels`), {
      credentials: 'include',
    })
    if (res.ok) setChannels(await res.json())
    startTransition(() => router.refresh())
  }

  async function submitCreate() {
    setError('')
    if (!createForm.name.trim()) {
      setError('Please give the Channel a name.')
      return
    }
    if (createForm.arrangement === 'linked' && createForm.linked_experiences.length === 0) {
      setError('Choose at least one Pathway, Gathering or Series to link.')
      return
    }
    setBusy(true)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${spaceSlug}/channels`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: createForm.name.trim(),
          description: createForm.description.trim() || null,
          channel_type: storedType(createForm),
          linked_experiences: createForm.arrangement === 'linked'
            ? createForm.linked_experiences : [],
          member_posting_allowed: createForm.member_posting_allowed,
          polls_allowed: createForm.polls_allowed,
          // Seeding members is useful on a linked channel too, not
          // only a private one.
          initial_member_user_ids: createForm.arrangement === 'open'
            ? [] : createForm.initial_member_user_ids,
        }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not create Channel.')
        return
      }
      setCreateForm(EMPTY_CREATE)
      setCreateOpen(false)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function updateChannel(channelId: string, patch: Record<string, unknown>) {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channelId}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        const detail = data.detail
        if (detail && typeof detail === 'object' && detail.code === 'would_broaden_access') {
          // Not a failure — a consequence the creator has not yet
          // acknowledged. Offer the same save again, confirmed, rather
          // than making them reconstruct it.
          setBroadenPrompt({
            channelId,
            patch,
            message: String(detail.message ?? 'This would widen who can read this channel.'),
          })
          return
        }
        setError(typeof detail === 'string' ? detail : 'Could not update Channel.')
        return
      }
      setBroadenPrompt(null)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function archiveOrRestore(channel: ChannelManageDetail) {
    setBusy(true)
    setError('')
    try {
      const action = channel.is_archived ? 'restore' : 'archive'
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channel.id}/${action}`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not update Channel.')
        return
      }
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  async function deleteChannel(channel: ChannelManageDetail) {
    if (channel.post_count > 0) {
      setError('This Channel still contains conversations. Archive it instead.')
      return
    }
    if (!confirm(`Permanently delete "${channel.name}"? This cannot be undone.`)) return
    setBusy(true)
    setError('')
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channel.id}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (!res.ok && res.status !== 204) {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not delete Channel.')
        return
      }
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>

      {error && (
        <div
          className="mb-4 rounded-lg px-4 py-3 text-[13px]"
          style={{ background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.25)', color: '#B91C1C' }}
        >
          {error}
        </div>
      )}

      {broadenPrompt && (
        <div
          className="mb-4 rounded-lg px-4 py-3 text-[13px]"
          style={{ background: 'rgba(180,83,9,0.06)', border: '1px solid rgba(180,83,9,0.30)', color: '#92400E' }}
          role="alert"
        >
          <p className="font-semibold">Before you widen this channel</p>
          <p className="mt-0.5 leading-relaxed">{broadenPrompt.message}</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void updateChannel(
                broadenPrompt.channelId,
                { ...broadenPrompt.patch, confirm_broadening: true },
              )}
              className="rounded-full bg-amber-700 px-4 py-1.5 text-[12.5px] font-medium text-white hover:opacity-90"
            >
              Yes, widen it
            </button>
            <button
              type="button"
              onClick={() => setBroadenPrompt(null)}
              className="rounded-full px-4 py-1.5 text-[12.5px] font-medium text-amber-900 underline underline-offset-2"
            >
              Keep it as it is
            </button>
          </div>
        </div>
      )}

      {/* Add Channel — primary action, matches other Creator Studio CTAs.
          Opens the inline create form below when clicked. */}
      {!createOpen ? (
        <div className="mb-6">
          <Button
            variant="primary"
            size="md"
            iconStart={<PlusIcon />}
            onClick={() => { setCreateOpen(true); setError('') }}
          >
            Add a Channel
          </Button>
        </div>
      ) : (
        <CreateChannelForm
          form={createForm}
          onChange={setCreateForm}
          eligiblePathways={eligiblePathways}
          eligibleEvents={eligibleEvents}
          eligibleSeries={eligibleSeries}
          memberOptions={memberOptions}
          busy={busy}
          onCancel={() => { setCreateOpen(false); setCreateForm(EMPTY_CREATE); setError('') }}
          onSubmit={submitCreate}
        />
      )}

      <div className="flex flex-col gap-6">

        {system.length > 0 && (
          <ChannelGroup
            heading={null}
            channels={system}
            spaceSlug={spaceSlug}
            members={memberOptions}
            pathways={pathways}
            events={events}
            series={series}
            editingId={editingId}
            setEditingId={setEditingId}
            updateChannel={updateChannel}
            archiveOrRestore={archiveOrRestore}
            deleteChannel={deleteChannel}
            refreshMembers={() => { void refresh() }}
            busy={busy}
          />
        )}

        {orderedGroupKeys.map((key) => {
          const list = grouped.get(key) ?? []
          if (list.length === 0) return null
          return (
            <ChannelGroup
              key={key}
              heading={key}
              channels={list}
              spaceSlug={spaceSlug}
              members={memberOptions}
              pathways={pathways}
              events={events}
              series={series}
              editingId={editingId}
              setEditingId={setEditingId}
              updateChannel={updateChannel}
              archiveOrRestore={archiveOrRestore}
              deleteChannel={deleteChannel}
              refreshMembers={() => { void refresh() }}
              busy={busy}
            />
          )
        })}

        {archived.length > 0 && (
          <ChannelGroup
            heading="ARCHIVED"
            channels={archived}
            spaceSlug={spaceSlug}
            members={memberOptions}
            pathways={pathways}
            events={events}
            series={series}
            editingId={editingId}
            setEditingId={setEditingId}
            updateChannel={updateChannel}
            archiveOrRestore={archiveOrRestore}
            deleteChannel={deleteChannel}
            refreshMembers={() => { void refresh() }}
            busy={busy}
          />
        )}

        {channels.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white p-6 text-center text-[13.5px] text-slate-500">
            You&rsquo;ll see your Channels here once you&rsquo;ve added one.
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Grouped rendering
// ---------------------------------------------------------------------------

function ChannelGroup({
  heading, channels, spaceSlug, members,
  pathways, events, series,
  editingId, setEditingId, updateChannel,
  archiveOrRestore, deleteChannel, refreshMembers, busy,
}: {
  heading: string | null
  channels: ChannelManageDetail[]
  spaceSlug: string
  members: MemberProfile[]
  pathways: CreatorPathway[]
  events: CreatorEvent[]
  series: CreatorGatheringSeries[]
  editingId: string | null
  setEditingId: (id: string | null) => void
  updateChannel: (id: string, patch: Record<string, unknown>) => Promise<void>
  archiveOrRestore: (c: ChannelManageDetail) => Promise<void>
  deleteChannel: (c: ChannelManageDetail) => Promise<void>
  refreshMembers: () => void
  busy: boolean
}) {
  return (
    <div>
      {heading && (
        <p
          className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.16em]"
          style={{ color: 'rgba(12,24,38,0.48)' }}
        >
          {heading}
        </p>
      )}
      <div className="flex flex-col gap-3">
        {channels.map((c) => (
          <ChannelRow
            key={c.id}
            spaceSlug={spaceSlug}
            channel={c}
            members={members}
            pathways={pathways}
            events={events}
            series={series}
            isEditing={editingId === c.id}
            onToggleEdit={() => setEditingId(editingId === c.id ? null : c.id)}
            onSave={(patch) => updateChannel(c.id, patch)}
            onArchiveOrRestore={() => archiveOrRestore(c)}
            onDelete={() => deleteChannel(c)}
            onMembersChanged={refreshMembers}
            busy={busy}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

interface RowProps {
  spaceSlug: string
  channel: ChannelManageDetail
  members: MemberProfile[]
  pathways: CreatorPathway[]
  events: CreatorEvent[]
  series: CreatorGatheringSeries[]
  isEditing: boolean
  onToggleEdit: () => void
  onSave: (patch: Record<string, unknown>) => Promise<void>
  onArchiveOrRestore: () => Promise<void>
  onDelete: () => Promise<void>
  onMembersChanged: () => void
  busy: boolean
}

function ChannelRow({
  spaceSlug, channel, members, pathways, events, series,
  isEditing, onToggleEdit, onSave,
  onArchiveOrRestore, onDelete, onMembersChanged, busy,
}: RowProps) {
  const [name, setName] = useState(channel.name)
  const [description, setDescription] = useState(channel.description ?? '')
  const [memberPosting, setMemberPosting] = useState(channel.member_posting_allowed)
  const [pollsAllowed, setPollsAllowed] = useState(channel.polls_allowed)
  const [membersOpen, setMembersOpen] = useState(false)

  const systemStartHere = channel.is_system && channel.channel_type === 'start_here'
  const systemGeneral = channel.is_system && channel.channel_type === 'general'
  const isLinked = ['pathway', 'gathering', 'series'].includes(channel.channel_type)
  const [links, setLinks] = useState<ExperienceRef[]>(
    () => (channel.linked_experiences ?? []).map((l) => ({ type: l.type, id: l.id })),
  )

  async function save() {
    if (systemGeneral) {
      // Only name + description are editable on Common Room.
      await onSave({
        name: name.trim(),
        description: description.trim() || null,
      })
      return
    }
    await onSave({
      name: name.trim(),
      description: description.trim() || null,
      member_posting_allowed: memberPosting,
      polls_allowed: pollsAllowed,
      // Only sent for linked channels. Omitting the key is what tells
      // the backend to leave the links alone, so an edit to an open
      // channel's name cannot unlink anything.
      ...(isLinked ? { linked_experiences: links } : {}),
    })
  }

  return (
    <div
      className="rounded-2xl bg-white px-5 py-4"
      style={{
        border: channel.is_archived
          ? '1px dashed rgba(12,24,38,0.16)'
          : '1px solid rgba(12,24,38,0.08)',
        opacity: channel.is_archived ? 0.85 : 1,
      }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {channel.icon_emoji && <span aria-hidden="true">{channel.icon_emoji}</span>}
            <p className="text-[15px] font-semibold text-navy-900">{channel.name}</p>
            {channel.is_system ? (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ background: 'rgba(56,160,158,0.16)', color: 'var(--fc-accent, #0f766e)' }}
              >
                System
              </span>
            ) : (
              <TypeChip type={channel.channel_type} />
            )}
            {channel.is_archived && (
              <span
                className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                style={{ background: 'rgba(212,176,72,0.14)', color: '#8A6A15' }}
              >
                Archived
              </span>
            )}
          </div>
          {channel.description && (
            <p className="mt-1 text-[13px] italic" style={{ color: 'rgba(12,24,38,0.62)', fontFamily: 'Georgia, serif' }}>
              {channel.description}
            </p>
          )}
          <LinkedExperienceSummary channel={channel} />
          <p className="mt-1 text-[11.5px] text-slate-500">
            {channel.post_count} conversation{channel.post_count === 1 ? '' : 's'}
            {(channel.channel_type === 'private' || isLinked) && ` · ${channel.private_member_count} member${channel.private_member_count === 1 ? '' : 's'}`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {!systemStartHere && (
            <button
              type="button"
              onClick={onToggleEdit}
              className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
              style={{
                background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                color: 'var(--fc-accent, #0f766e)',
              }}
            >
              {isEditing ? 'Close' : 'Edit'}
            </button>
          )}
          {(channel.channel_type === 'private' || isLinked) && !channel.is_archived && (
            <button
              type="button"
              onClick={() => setMembersOpen((v) => !v)}
              className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
              style={{
                background: 'var(--fc-accent-soft, rgba(56,160,158,0.10))',
                color: 'var(--fc-accent, #0f766e)',
              }}
            >
              {membersOpen ? 'Hide members' : 'Members'}
            </button>
          )}
          {!channel.is_system && (
            <button
              type="button"
              onClick={onArchiveOrRestore}
              disabled={busy}
              className="rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
              style={{
                background: channel.is_archived ? 'rgba(56,160,158,0.10)' : 'rgba(212,176,72,0.14)',
                color: channel.is_archived ? 'var(--fc-accent, #0f766e)' : '#8A6A15',
              }}
            >
              {channel.is_archived ? 'Restore' : 'Archive'}
            </button>
          )}
          {!channel.is_system && channel.post_count === 0 && (
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              className="rounded-full px-3 py-1 text-[12px] font-medium text-slate-500 transition-colors hover:text-red-600"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {isEditing && !systemStartHere && (
        <div className="mt-4 border-t pt-4" style={{ borderColor: 'rgba(12,24,38,0.08)' }}>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-[12px] text-black md:col-span-2">
              <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </label>
            <label className="text-[12px] text-black md:col-span-2">
              <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Description</span>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
              />
            </label>
          </div>

          {!systemGeneral && (
            <div className="mt-3 flex flex-wrap gap-4 text-[12.5px] text-navy-900">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={memberPosting}
                  onChange={(e) => setMemberPosting(e.target.checked)}
                  className="h-4 w-4 accent-teal-500"
                />
                Members can start conversations
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={pollsAllowed}
                  onChange={(e) => setPollsAllowed(e.target.checked)}
                  className="h-4 w-4 accent-teal-500"
                />
                Allow polls
              </label>
            </div>
          )}

          {isLinked && !systemGeneral && (
            <div className="mt-4 border-t pt-4" style={{ borderColor: 'rgba(12,24,38,0.06)' }}>
              <ExperienceMultiSelect
                selected={links}
                onChange={setLinks}
                pathways={pathways}
                events={events}
                series={series}
              />
              <p className="mt-2 text-[11.5px] leading-relaxed text-slate-500">
                Unlinking an experience does not remove anyone from the
                channel — people who joined through it stay, and you can
                remove them yourself if you want to.
              </p>
            </div>
          )}

          {systemGeneral && (
            <p className="mt-3 text-[12px] italic" style={{ color: 'rgba(12,24,38,0.55)' }}>
              Common Room is a system Channel. Only its name and description can be changed.
            </p>
          )}

          <div className="mt-4 flex justify-end">
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy}
              className="rounded-full px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: 'var(--fc-accent, #14b8a6)' }}
            >
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      )}

      {membersOpen && (channel.channel_type === 'private' || isLinked) && (
        <PrivateMembersPanel
          spaceSlug={spaceSlug}
          channelId={channel.id}
          allMembers={members}
          onChanged={onMembersChanged}
        />
      )}
    </div>
  )
}

function TypeChip({ type }: { type: string }) {
  const label =
    type === 'open' ? 'Open' :
    type === 'private' ? 'Private' :
    type === 'pathway' ? 'Pathway' :
    type === 'gathering' ? 'Gathering' :
    type === 'series' ? 'Series' :
    type
  const bg =
    type === 'private' ? 'rgba(126,66,145,0.14)' :
    type === 'pathway' ? 'rgba(212,176,72,0.16)' :
    type === 'gathering' ? 'rgba(56,160,158,0.14)' :
    type === 'series' ? 'rgba(66,199,198,0.14)' :
    'rgba(12,24,38,0.06)'
  const color =
    type === 'private' ? '#6B2C7A' :
    type === 'pathway' ? '#8A6A15' :
    type === 'gathering' ? 'var(--fc-accent, #0f766e)' :
    type === 'series' ? '#07545C' :
    'rgba(12,24,38,0.62)'
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: bg, color }}
    >
      {label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Create form (extracted so the main file stays readable)
// ---------------------------------------------------------------------------

/** Grouped, searchable multi-select over the three experience kinds.
 *
 *  Grouped rather than one flat list because the kinds are not
 *  interchangeable in a creator's head — "which Gatherings" and
 *  "which Pathways" are separate questions — and searchable because a
 *  Collective running monthly circles accumulates a lot of
 *  near-identically named Gatherings. */
function ExperienceMultiSelect({
  selected, onChange, pathways, events, series,
}: {
  selected: ExperienceRef[]
  onChange: (next: ExperienceRef[]) => void
  pathways: CreatorPathway[]
  events: CreatorEvent[]
  series: CreatorGatheringSeries[]
}) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()

  const groups: { label: string; kind: ExperienceRef['type']; items: { id: string; title: string }[] }[] = [
    { label: 'Pathways', kind: 'pathway', items: pathways.map((p) => ({ id: p.id, title: p.title })) },
    { label: 'Gatherings', kind: 'gathering', items: events.map((e) => ({ id: e.id, title: e.title })) },
    { label: 'Gathering Series', kind: 'series', items: series.map((x) => ({ id: x.id, title: x.title })) },
  ]

  const isSelected = (kind: ExperienceRef['type'], id: string) =>
    selected.some((r) => r.type === kind && r.id === id)

  function toggle(kind: ExperienceRef['type'], id: string) {
    if (isSelected(kind, id)) {
      onChange(selected.filter((r) => !(r.type === kind && r.id === id)))
    } else {
      onChange([...selected, { type: kind, id }])
    }
  }

  const titleFor = (ref: ExperienceRef) => {
    const group = groups.find((g) => g.kind === ref.type)
    return group?.items.find((i) => i.id === ref.id)?.title ?? ref.id
  }

  return (
    <div>
      <p className="mb-1 text-[12px] font-semibold uppercase tracking-[0.14em] text-black">
        Linked experiences
      </p>
      <p className="mb-2 text-[12px] leading-relaxed text-black">
        Anyone who joins <strong>any one</strong> of these is added to the
        channel, and stays in it afterwards. Link as many as you like — three
        monthly circles can share one ongoing conversation.
      </p>

      {selected.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1.5">
          {selected.map((ref) => (
            <span
              key={`${ref.type}:${ref.id}`}
              className="inline-flex items-center gap-1 rounded-full bg-teal-50 px-2.5 py-1 text-[12px] text-teal-900"
              style={{ border: '1px solid rgba(56,160,158,0.25)' }}
            >
              {titleFor(ref)}
              <button
                type="button"
                onClick={() => toggle(ref.type, ref.id)}
                aria-label={`Remove ${titleFor(ref)}`}
                className="ml-0.5 rounded-full px-1 text-teal-700 hover:bg-teal-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-500"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search Pathways, Gatherings and Series…"
        aria-label="Search experiences"
        className="mb-2 w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 placeholder-slate-400 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
      />

      <div
        className="max-h-60 overflow-y-auto rounded-lg px-3 py-2"
        style={{ border: '1px solid rgba(12,24,38,0.10)' }}
      >
        {groups.every((g) => g.items.length === 0) && (
          <p className="py-2 text-[12.5px] italic text-slate-500">
            No Pathways, Gatherings or Series yet — create one first, then
            link it here.
          </p>
        )}
        {groups.map((group) => {
          const visible = needle
            ? group.items.filter((i) => i.title.toLowerCase().includes(needle))
            : group.items
          if (visible.length === 0) return null
          return (
            <div key={group.kind} className="mb-2 last:mb-0">
              <p className="py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                {group.label}
              </p>
              {visible.map((item) => (
                <label
                  key={item.id}
                  className="flex cursor-pointer items-center gap-2 py-1 text-[13px] text-navy-900"
                >
                  <input
                    type="checkbox"
                    checked={isSelected(group.kind, item.id)}
                    onChange={() => toggle(group.kind, item.id)}
                    className="h-4 w-4 accent-teal-500"
                  />
                  <span className="truncate">{item.title}</span>
                </label>
              ))}
            </div>
          )
        })}
        {needle && groups.every((g) => (
          g.items.filter((i) => i.title.toLowerCase().includes(needle)).length === 0
        )) && (
          <p className="py-2 text-[12.5px] italic text-slate-500">
            Nothing matches “{query}”.
          </p>
        )}
      </div>
    </div>
  )
}


/** A readable summary of what a channel is linked to.
 *
 *  Names up to two and counts the rest rather than listing twelve
 *  Gatherings on a card — a creator scanning the page needs to
 *  recognise the channel, not audit it. The full list is one click
 *  away. */
function LinkedExperienceSummary({ channel }: { channel: ChannelManageDetail }) {
  const [expanded, setExpanded] = useState(false)
  const links = channel.linked_experiences ?? []
  if (links.length === 0) return null

  const shown = expanded ? links : links.slice(0, 2)
  const hidden = links.length - shown.length

  return (
    <div className="mt-1 text-[11.5px] text-slate-500">
      Linked to ·{' '}
      {shown.map((ref, i) => (
        <span key={`${ref.type}:${ref.id}`}>
          {i > 0 && ', '}
          <span className="text-navy-800">{ref.title ?? 'Untitled'}</span>
          {ref.is_archived && <span className="italic text-slate-400"> (archived)</span>}
        </span>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="ml-1 underline decoration-slate-300 underline-offset-2 hover:text-navy-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-500"
        >
          and {hidden} more
        </button>
      )}
      {expanded && links.length > 2 && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="ml-1 underline decoration-slate-300 underline-offset-2 hover:text-navy-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-teal-500"
        >
          show fewer
        </button>
      )}
    </div>
  )
}


function CreateChannelForm({
  form, onChange, eligiblePathways, eligibleEvents, eligibleSeries,
  memberOptions, busy, onCancel, onSubmit,
}: {
  form: CreateForm
  onChange: (f: CreateForm) => void
  eligiblePathways: CreatorPathway[]
  eligibleEvents: CreatorEvent[]
  eligibleSeries: CreatorGatheringSeries[]
  memberOptions: MemberProfile[]
  busy: boolean
  onCancel: () => void
  onSubmit: () => Promise<void>
}) {
  return (
    <form
      className="mb-6 rounded-2xl bg-white px-6 py-5"
      style={{ border: '1px solid rgba(56,160,158,0.28)' }}
      onSubmit={(e) => { e.preventDefault(); void onSubmit() }}
    >
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[13px] font-semibold text-navy-900">New Channel</p>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-black hover:text-slate-600"
        >
          Cancel
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-[12px] text-black">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Name</span>
          <input
            type="text"
            value={form.name}
            onChange={(e) => onChange({ ...form, name: e.target.value })}
            placeholder="e.g. Sunday reflections"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
        </label>

        <label className="text-[12px] text-black">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Who can take part</span>
          <select
            value={form.arrangement}
            onChange={(e) => onChange({ ...form, arrangement: e.target.value as Arrangement })}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none"
          >
            <option value="open">💬 Open to Collective members</option>
            <option value="private">🔒 Private — selected members</option>
            <option
              value="linked"
              disabled={
                eligiblePathways.length === 0
                && eligibleEvents.length === 0
                && eligibleSeries.length === 0
              }
            >
              🔗 Linked experiences — people who join any of them
            </option>
          </select>
        </label>

        <label className="text-[12px] text-black md:col-span-2">
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Description (optional)</span>
          <input
            type="text"
            value={form.description}
            onChange={(e) => onChange({ ...form, description: e.target.value })}
            placeholder="A calm invitation for what happens here"
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
          />
        </label>

        {form.arrangement === 'linked' && (
          <div className="md:col-span-2">
            <ExperienceMultiSelect
              selected={form.linked_experiences}
              onChange={(next) => onChange({ ...form, linked_experiences: next })}
              pathways={eligiblePathways}
              events={eligibleEvents}
              series={eligibleSeries}
            />
          </div>
        )}
      </div>

      {form.arrangement !== 'open' && (
        <div className="mt-4">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
            Initial members
          </p>
          <div
            className="max-h-52 overflow-y-auto rounded-lg px-3 py-2"
            style={{ border: '1px solid rgba(12,24,38,0.10)' }}
          >
            {memberOptions.length === 0 && (
              <p className="py-2 text-[12.5px] italic text-slate-500">
                No members yet — add them here once people join.
              </p>
            )}
            {memberOptions.map((m) => {
              const checked = form.initial_member_user_ids.includes(m.id)
              return (
                <label key={m.id} className="flex cursor-pointer items-center gap-2 py-1 text-[13px] text-navy-900">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      const next = new Set(form.initial_member_user_ids)
                      if (e.target.checked) next.add(m.id); else next.delete(m.id)
                      onChange({ ...form, initial_member_user_ids: Array.from(next) })
                    }}
                    className="h-4 w-4 accent-teal-500"
                  />
                  {m.display_name}
                </label>
              )
            })}
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-4 text-[12.5px] text-navy-900">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={form.member_posting_allowed}
            onChange={(e) => onChange({ ...form, member_posting_allowed: e.target.checked })}
            className="h-4 w-4 accent-teal-500"
          />
          Members can start conversations
        </label>
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            checked={form.polls_allowed}
            onChange={(e) => onChange({ ...form, polls_allowed: e.target.checked })}
            className="h-4 w-4 accent-teal-500"
          />
          Allow polls
        </label>
      </div>

      <div className="mt-5 flex justify-end">
        <button
          type="submit"
          disabled={busy}
          className="rounded-full px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          style={{ background: 'var(--fc-accent, #14b8a6)' }}
        >
          {busy ? 'Creating…' : 'Create Channel'}
        </button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------

interface MemberRow {
  user_id: string
  display_name: string
  email: string | null
  role: string
  source: string
}

function PrivateMembersPanel({
  spaceSlug, channelId, allMembers, onChanged,
}: {
  spaceSlug: string
  channelId: string
  allMembers: MemberProfile[]
  onChanged: () => void
}) {
  const [current, setCurrent] = useState<MemberRow[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [picking, setPicking] = useState(false)
  const [selected, setSelected] = useState<string[]>([])

  const loaded = current !== null
  const currentIds = new Set((current ?? []).map((r) => r.user_id))
  const eligible = allMembers.filter((m) => !currentIds.has(m.id))

  async function load() {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channelId}/members`),
        { credentials: 'include' },
      )
      if (res.ok) setCurrent(await res.json())
      else setError('Could not load members.')
    } finally {
      setBusy(false)
    }
  }

  async function addMembers() {
    if (selected.length === 0) { setPicking(false); return }
    setBusy(true)
    setError('')
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channelId}/members`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user_ids: selected }),
        },
      )
      if (res.ok) {
        setCurrent(await res.json())
        setSelected([])
        setPicking(false)
        onChanged()
      } else {
        const data = await res.json().catch(() => ({}))
        setError(typeof data.detail === 'string' ? data.detail : 'Could not add members.')
      }
    } finally {
      setBusy(false)
    }
  }

  async function removeMember(userId: string) {
    setBusy(true)
    setError('')
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${spaceSlug}/channels/${channelId}/members/${userId}`),
        { method: 'DELETE', credentials: 'include' },
      )
      if (res.ok || res.status === 204) {
        setCurrent((c) => (c ?? []).filter((r) => r.user_id !== userId))
        onChanged()
      } else {
        setError('Could not remove member.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!loaded) {
    return (
      <div className="mt-4 border-t pt-4" style={{ borderColor: 'rgba(12,24,38,0.08)' }}>
        <button
          type="button"
          onClick={() => void load()}
          disabled={busy}
          className="text-[12.5px] font-medium text-teal-700 hover:underline"
        >
          {busy ? 'Loading…' : 'Load members'}
        </button>
      </div>
    )
  }

  return (
    <div className="mt-4 border-t pt-4" style={{ borderColor: 'rgba(12,24,38,0.08)' }}>
      {error && (
        <p className="mb-2 text-[12px] text-red-600">{error}</p>
      )}

      {(current ?? []).length === 0 ? (
        <p className="text-[13px] italic text-slate-500">No members yet — this Channel is hidden from everyone until someone is added.</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {(current ?? []).map((r) => (
            <li
              key={r.user_id}
              className="flex items-center gap-1 rounded-full px-2.5 py-1 text-[12.5px]"
              style={{ background: 'rgba(56,160,158,0.10)', color: 'var(--fc-accent, #0f766e)' }}
            >
              {r.display_name}
              <button
                type="button"
                onClick={() => void removeMember(r.user_id)}
                title="Remove"
                className="ml-1 text-[11px] opacity-60 hover:opacity-100"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      {!picking ? (
        <button
          type="button"
          onClick={() => { setPicking(true); setSelected([]) }}
          className="mt-3 text-[12.5px] font-medium text-teal-700 hover:underline"
          disabled={eligible.length === 0}
        >
          {eligible.length === 0 ? 'Everyone is already in this Channel' : '+ Add members'}
        </button>
      ) : (
        <div className="mt-3">
          <div
            className="max-h-52 overflow-y-auto rounded-lg px-3 py-2"
            style={{ border: '1px solid rgba(12,24,38,0.10)' }}
          >
            {eligible.map((m) => {
              const checked = selected.includes(m.id)
              return (
                <label key={m.id} className="flex cursor-pointer items-center gap-2 py-1 text-[13px] text-navy-900">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => {
                      const next = new Set(selected)
                      if (e.target.checked) next.add(m.id); else next.delete(m.id)
                      setSelected(Array.from(next))
                    }}
                    className="h-4 w-4 accent-teal-500"
                  />
                  {m.display_name}
                </label>
              )
            })}
          </div>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => void addMembers()}
              disabled={busy || selected.length === 0}
              className="rounded-full px-4 py-1.5 text-[12.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              style={{ background: 'var(--fc-accent, #14b8a6)' }}
            >
              {busy ? 'Adding…' : `Add ${selected.length || ''}`.trim()}
            </button>
            <button
              type="button"
              onClick={() => { setPicking(false); setSelected([]) }}
              className="text-[12.5px] text-slate-500 hover:text-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
