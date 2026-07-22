'use client'

import { useMemo, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
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

interface Props {
  spaceSlug: string
  initialChannels: ChannelManageDetail[]
  members: MemberProfile[]
  pathways: CreatorPathway[]
  events: CreatorEvent[]
}

type ChannelType = 'open' | 'private' | 'pathway' | 'gathering'

interface CreateForm {
  name: string
  channel_type: ChannelType
  description: string
  pathway_id: string
  gathering_id: string
  member_posting_allowed: boolean
  polls_allowed: boolean
  initial_member_user_ids: string[]
}

const EMPTY_CREATE: CreateForm = {
  name: '',
  channel_type: 'open',
  description: '',
  pathway_id: '',
  gathering_id: '',
  member_posting_allowed: true,
  polls_allowed: true,
  initial_member_user_ids: [],
}

const GROUP_ORDER: string[] = ['PATHWAYS', 'GATHERINGS', 'PRIVATE', 'OPEN DISCUSSIONS']

export default function ManageChannelsClient({
  spaceSlug,
  initialChannels,
  members,
  pathways,
  events,
}: Props) {
  const router = useRouter()
  const [channels, setChannels] = useState<ChannelManageDetail[]>(initialChannels)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<CreateForm>(EMPTY_CREATE)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [, startTransition] = useTransition()

  const eligiblePathways = useMemo(
    () => pathways.filter((p) => p.status !== 'archived'),
    [pathways],
  )
  const eligibleEvents = useMemo(
    () => events.filter((e) => e.status !== 'archived' && e.status !== 'cancelled'),
    [events],
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
    if (createForm.channel_type === 'pathway' && !createForm.pathway_id) {
      setError('Choose which Pathway this Channel belongs to.')
      return
    }
    if (createForm.channel_type === 'gathering' && !createForm.gathering_id) {
      setError('Choose which Gathering this Channel belongs to.')
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
          channel_type: createForm.channel_type,
          pathway_id: createForm.channel_type === 'pathway' ? createForm.pathway_id : null,
          gathering_id: createForm.channel_type === 'gathering' ? createForm.gathering_id : null,
          member_posting_allowed: createForm.member_posting_allowed,
          polls_allowed: createForm.polls_allowed,
          initial_member_user_ids: createForm.channel_type === 'private'
            ? createForm.initial_member_user_ids : [],
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
        setError(typeof data.detail === 'string' ? data.detail : 'Could not update Channel.')
        return
      }
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

      {/* Add Channel — collapsed pill until opened */}
      {!createOpen ? (
        <button
          type="button"
          onClick={() => { setCreateOpen(true); setError('') }}
          className="mb-6 w-full rounded-xl border border-dashed border-border bg-surface px-5 py-4 text-left text-sm text-black transition-colors hover:border-teal-300 hover:text-teal-600"
        >
          + Add a Channel
        </button>
      ) : (
        <CreateChannelForm
          form={createForm}
          onChange={setCreateForm}
          eligiblePathways={eligiblePathways}
          eligibleEvents={eligibleEvents}
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
  editingId, setEditingId, updateChannel,
  archiveOrRestore, deleteChannel, refreshMembers, busy,
}: {
  heading: string | null
  channels: ChannelManageDetail[]
  spaceSlug: string
  members: MemberProfile[]
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
  isEditing: boolean
  onToggleEdit: () => void
  onSave: (patch: Record<string, unknown>) => Promise<void>
  onArchiveOrRestore: () => Promise<void>
  onDelete: () => Promise<void>
  onMembersChanged: () => void
  busy: boolean
}

function ChannelRow({
  spaceSlug, channel, members,
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
          <p className="mt-1 text-[11.5px] text-slate-500">
            {channel.post_count} conversation{channel.post_count === 1 ? '' : 's'}
            {channel.channel_type === 'private' && ` · ${channel.private_member_count} member${channel.private_member_count === 1 ? '' : 's'}`}
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
          {channel.channel_type === 'private' && !channel.is_archived && (
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

      {membersOpen && channel.channel_type === 'private' && (
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
    type
  const bg =
    type === 'private' ? 'rgba(126,66,145,0.14)' :
    type === 'pathway' ? 'rgba(212,176,72,0.16)' :
    type === 'gathering' ? 'rgba(56,160,158,0.14)' :
    'rgba(12,24,38,0.06)'
  const color =
    type === 'private' ? '#6B2C7A' :
    type === 'pathway' ? '#8A6A15' :
    type === 'gathering' ? 'var(--fc-accent, #0f766e)' :
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

function CreateChannelForm({
  form, onChange, eligiblePathways, eligibleEvents,
  memberOptions, busy, onCancel, onSubmit,
}: {
  form: CreateForm
  onChange: (f: CreateForm) => void
  eligiblePathways: CreatorPathway[]
  eligibleEvents: CreatorEvent[]
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
          <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Type</span>
          <select
            value={form.channel_type}
            onChange={(e) => onChange({ ...form, channel_type: e.target.value as ChannelType })}
            className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none"
          >
            <option value="open">💬 Open discussion — everyone in the collective</option>
            <option value="private">🔒 Private — chosen members only</option>
            <option value="pathway" disabled={eligiblePathways.length === 0}>
              🛤 Pathway — active enrollees only
            </option>
            <option value="gathering" disabled={eligibleEvents.length === 0}>
              📅 Gathering — registered attendees only
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

        {form.channel_type === 'pathway' && (
          <label className="text-[12px] text-black md:col-span-2">
            <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Pathway</span>
            <select
              value={form.pathway_id}
              onChange={(e) => onChange({ ...form, pathway_id: e.target.value })}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none"
            >
              <option value="">Choose a Pathway…</option>
              {eligiblePathways.map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          </label>
        )}

        {form.channel_type === 'gathering' && (
          <label className="text-[12px] text-black md:col-span-2">
            <span className="mb-1 block font-semibold uppercase tracking-[0.14em]">Gathering</span>
            <select
              value={form.gathering_id}
              onChange={(e) => onChange({ ...form, gathering_id: e.target.value })}
              className="w-full rounded-lg border border-border bg-white px-3 py-2 text-[13.5px] text-navy-900 focus:border-teal-400 focus:outline-none"
            >
              <option value="">Choose a Gathering…</option>
              {eligibleEvents.map((ev) => (
                <option key={ev.id} value={ev.id}>{ev.title}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {form.channel_type === 'private' && (
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
