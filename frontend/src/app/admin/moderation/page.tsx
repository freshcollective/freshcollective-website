'use client'

/**
 * Community Care — the wellbeing surface of World Management.
 *
 * Stage 2A wires the page to the real backend. When the
 * community_care_enabled flag is off, /api/admin/community-care/*
 * returns 503; the page falls back to the same optimistic Stage 1
 * presentation. When the flag is on, real overview + case data
 * populates the page and a review drawer opens for case detail.
 *
 * A restrained sage accent is scoped to this page only — care,
 * wellbeing, stewardship — never displacing the shared WM palette.
 */

import { useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'

// ---------------------------------------------------------------------------
// Design tokens — WM shared surface
// ---------------------------------------------------------------------------
const PAGE_BG      = '#FBFDFC'
const CARD_BG      = '#FFFFFF'
const CARD_BORDER  = '1px solid #E7EEF0'
const CARD_SHADOW  = '0 2px 10px rgba(16, 24, 40, 0.04), 0 1px 2px rgba(16, 24, 40, 0.03)'
const INK          = '#0C1826'
const INK_MUTED    = 'rgba(12, 24, 38, 0.60)'
const INK_SOFTER   = 'rgba(12, 24, 38, 0.42)'
const HAIRLINE     = '1px solid rgba(12, 24, 38, 0.06)'

const SERIF_ITALIC: React.CSSProperties = {
  color: INK_MUTED,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}

// ---------------------------------------------------------------------------
// Sage — a very restrained care accent scoped to this page only. Deliberately
// distinct from the WM teal (which reads as commercial/positive/active); sage
// carries the emotional register of stewardship, wellbeing, and healthy
// communities. Do not export or reuse elsewhere without an explicit product
// decision — the WM palette is the primary language.
// ---------------------------------------------------------------------------
const SAGE_DOT    = '#7ea87a'
const SAGE_BG     = 'rgba(126, 168, 122, 0.10)'
const SAGE_BORDER = 'rgba(126, 168, 122, 0.30)'
const SAGE_TEXT   = '#3d6b3b'

// Priority pill hues — locked from the WM palette.
const PRIORITY_HUE: Record<string, { bg: string; border: string; text: string }> = {
  low:       { bg: 'rgba(12, 24, 38, 0.05)',       border: 'rgba(12, 24, 38, 0.15)',  text: INK_MUTED },
  moderate:  { bg: 'rgba(212, 176, 72, 0.10)',     border: 'rgba(212, 176, 72, 0.30)', text: '#8A6A15' },
  high:      { bg: 'rgba(214, 96, 87, 0.08)',      border: 'rgba(214, 96, 87, 0.28)',  text: '#a63c30' },
  immediate: { bg: 'rgba(214, 96, 87, 0.14)',      border: 'rgba(214, 96, 87, 0.42)',  text: '#8a2a20' },
}
const STATUS_LABEL: Record<string, string> = {
  new:             'New',
  reviewing:       'Reviewing',
  waiting_info:    'Waiting for information',
  action_required: 'Action required',
  resolved:        'Resolved',
  closed_no_action:'Closed — no action',
}
const PRIORITY_LABEL: Record<string, string> = {
  low: 'Low', moderate: 'Moderate', high: 'High', immediate: 'Immediate',
}

// ---------------------------------------------------------------------------
// Types — match backend Pydantic schemas
// ---------------------------------------------------------------------------

interface OutcomeCounts {
  guidance: number
  reminders: number
  warnings: number
  protective_measures: number
  no_further_action: number
  account_cancellations: number
  creator_cancellations: number
  collective_closures: number
}

interface Overview {
  communities_needing_care: number
  conversations_awaiting_review: number
  creator_support_requests: number
  overall_wellbeing: 'healthy' | 'needs_attention' | 'needs_care'
  overall_wellbeing_label: string
  outcomes: OutcomeCounts
}

interface CaseListRow {
  id: string
  case_number: string
  content_type: string
  subject_space_id: string | null
  subject_space_name: string | null
  subject_member_user_id: string | null
  subject_member_name: string | null
  category: string | null
  creator_request_scope: string | null
  status: string
  priority: string
  report_count: number
  assigned_reviewer_user_id: string | null
  assigned_reviewer_name: string | null
  opened_at: string
  resolved_at: string | null
}

interface Signals {
  reports_on_case: number
  prior_cases_for_member: number
  prior_cases_for_creator: number
}

interface Report {
  id: string
  reporter_user_id: string | null
  reporter_name: string | null
  reporter_kind: string
  content_type: string
  category: string
  reporter_note: string | null
  created_at: string
}

interface CaseNote {
  id: string
  author_user_id: string | null
  author_name: string | null
  body: string
  is_internal: boolean
  created_at: string
}

interface CaseEvent {
  id: string
  kind: string
  actor_user_id: string | null
  actor_name: string | null
  occurred_at: string
  previous_value: Record<string, unknown> | null
  new_value: Record<string, unknown> | null
  reason: string | null
  internal_note: string | null
  subject_content_ref: Record<string, unknown> | null
}

interface CaseAction {
  id: string
  layer: string
  kind: string
  issued_by_admin_user_id: string | null
  issued_by_admin_name: string | null
  reason: string | null
  internal_note: string | null
  explanation_to_recipient: string | null
  affected_user_id: string | null
  affected_space_id: string | null
  affected_post_id: string | null
  affected_comment_id: string | null
  starts_at: string
  ends_at: string | null
  reversed_at: string | null
  reversed_by_admin_user_id: string | null
  reversal_reason: string | null
  created_at: string
}

interface CaseDetail {
  id: string
  case_number: string
  case_summary: string | null
  content_type: string
  subject_post_id: string | null
  subject_comment_id: string | null
  subject_member_user_id: string | null
  subject_member_name: string | null
  subject_creator_user_id: string | null
  subject_creator_name: string | null
  subject_space_id: string | null
  subject_space_name: string | null
  content_snapshot: Record<string, unknown> | null
  category: string | null
  creator_request_scope: string | null
  status: string
  priority: string
  report_count: number
  assigned_reviewer_user_id: string | null
  assigned_reviewer_name: string | null
  opened_at: string
  first_reviewed_at: string | null
  resolved_at: string | null
  resolution_summary: string | null
  signals: Signals
  reports: Report[]
  notes: CaseNote[]
  events: CaseEvent[]
  actions: CaseAction[]
}

// ---------------------------------------------------------------------------

export default function CommunityCarePage() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [cases, setCases] = useState<CaseListRow[]>([])
  const [flagOff, setFlagOff] = useState<boolean | null>(null)   // null = still probing
  const [error, setError] = useState<string | null>(null)
  const [openCaseId, setOpenCaseId] = useState<string | null>(null)

  function reload() {
    let cancelled = false
    Promise.all([
      fetch(apiUrl('/api/admin/community-care/overview'), { credentials: 'include' }),
      fetch(apiUrl('/api/admin/community-care/cases'),    { credentials: 'include' }),
    ])
      .then(async ([oRes, cRes]) => {
        if (cancelled) return
        if (oRes.status === 503) {
          setFlagOff(true)
          return
        }
        if (!oRes.ok) throw new Error(`Overview: ${oRes.status}`)
        if (!cRes.ok) throw new Error(`Cases: ${cRes.status}`)
        setFlagOff(false)
        setOverview(await oRes.json() as Overview)
        setCases(await cRes.json() as CaseListRow[])
      })
      .catch((e: Error) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }

  useEffect(() => reload(), [])   // eslint-disable-line react-hooks/exhaustive-deps

  // Stage-1 fallback values used whenever the backend isn't reachable
  // yet (flag off) or is still probing.
  const wellbeing = overview ?? {
    communities_needing_care: 0,
    conversations_awaiting_review: 0,
    creator_support_requests: 0,
    overall_wellbeing: 'healthy' as const,
    overall_wellbeing_label: 'Healthy',
    outcomes: {
      guidance: 0, reminders: 0, warnings: 0,
      protective_measures: 0, no_further_action: 0,
      account_cancellations: 0, creator_cancellations: 0, collective_closures: 0,
    } as OutcomeCounts,
  }

  return (
    <div style={{ background: PAGE_BG, minHeight: '100%' }}>
      {openCaseId && (
        <ReviewDrawer
          caseId={openCaseId}
          onClose={() => setOpenCaseId(null)}
          onChange={() => reload()}
        />
      )}

      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">
        {/* Hero */}
        <header className="mb-10">
          <h1 className="font-serif text-[32px] leading-tight md:text-[40px]" style={{ color: INK }}>
            Community Care
          </h1>
          <p className="mt-3 max-w-[640px] text-[15px] leading-relaxed" style={SERIF_ITALIC}>
            Helping every collective remain welcoming, respectful and safe.
          </p>
        </header>

        {error && (
          <div
            className="mb-6 rounded-2xl px-4 py-3 text-[13px]"
            style={{ background: 'rgba(214, 96, 87, 0.08)', border: '1px solid rgba(214, 96, 87, 0.28)', color: '#a63c30' }}
          >
            {error}
          </div>
        )}

        {/* Section 1 — Community wellbeing */}
        <section className="mb-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <WellbeingCard
            emoji="🌿"
            label="Communities needing care"
            value={String(wellbeing.communities_needing_care)}
            subtitle={
              wellbeing.communities_needing_care === 0
                ? 'No collectives currently need support.'
                : 'Collectives with open cases.'
            }
          />
          <WellbeingCard
            emoji="💬"
            label="Conversations awaiting review"
            value={String(wellbeing.conversations_awaiting_review)}
            subtitle={
              wellbeing.conversations_awaiting_review === 0
                ? 'Nothing is waiting to be reviewed.'
                : 'New cases waiting for a caretaker.'
            }
          />
          <WellbeingCard
            emoji="🤝"
            label="Creator support requests"
            value={String(wellbeing.creator_support_requests)}
            subtitle={
              wellbeing.creator_support_requests === 0
                ? 'No creators currently need assistance.'
                : 'Creators awaiting a response.'
            }
          />
          <WellbeingCard
            emoji="❤️"
            label="Overall wellbeing"
            value={wellbeing.overall_wellbeing_label}
            subtitle={
              wellbeing.overall_wellbeing === 'healthy'
                ? 'The world is thriving.'
                : wellbeing.overall_wellbeing === 'needs_attention'
                ? 'One or more open High cases.'
                : 'One or more open Immediate cases.'
            }
            sage
          />
        </section>

        {/* Section 1b — Outcome breakdown (Stage 2D reporting) */}
        <OutcomeBreakdownSection counts={wellbeing.outcomes} />

        {/* Section 2 — Recent community activity */}
        <section className="mb-10">
          <div className="mb-3">
            <h2 className="font-serif text-[22px] leading-tight" style={{ color: INK }}>
              Recent community activity
            </h2>
          </div>
          <div
            className="rounded-2xl px-10 py-16 text-center"
            style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
          >
            <p className="mx-auto max-w-[520px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
              Community activity will begin appearing here as collectives grow and members connect across the world.
            </p>
          </div>
        </section>

        {/* Section 3 — Conversations needing care */}
        <section className="mb-10">
          <div className="mb-3">
            <h2 className="font-serif text-[22px] leading-tight" style={{ color: INK }}>
              Conversations needing care
            </h2>
          </div>
          <div
            className="overflow-hidden rounded-2xl"
            style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
          >
            <table className="w-full text-left">
              <thead>
                <tr>
                  {['Collective', 'Content', 'Reason', 'Reports', 'Priority', 'Status', ''].map((h) => (
                    <th
                      key={h}
                      className="px-5 py-3.5 text-[10.5px] font-semibold uppercase tracking-[0.14em]"
                      style={{ color: INK_SOFTER, borderBottom: HAIRLINE }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cases.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-6 py-16 text-center">
                      <p className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
                        🌿 Wonderful.
                      </p>
                      <p className="mt-2 text-[14px]" style={SERIF_ITALIC}>
                        There are currently no conversations needing care.
                      </p>
                    </td>
                  </tr>
                ) : (
                  cases.map((c, i) => (
                    <CaseRow key={c.id} row={c} first={i === 0} onOpen={() => setOpenCaseId(c.id)} />
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Section 4 — Community Care principles */}
        <section>
          <div className="mb-5">
            <h2 className="font-serif text-[22px] leading-tight" style={{ color: INK }}>
              Community Care principles
            </h2>
            <p className="mt-1 text-[13px]" style={SERIF_ITALIC}>
              The values that guide every act of stewardship in the world.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <PrincipleCard
              title="Respect comes first"
              body="Every person deserves to be treated with kindness and dignity."
            />
            <PrincipleCard
              title="Healthy communities matter"
              body="We work to help every collective remain welcoming, constructive and safe."
            />
            <PrincipleCard
              title="Thoughtful decisions"
              body="Every report is reviewed intentionally, with care and context, before any action is taken."
            />
          </div>
        </section>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Case row + review drawer
// ---------------------------------------------------------------------------

function CaseRow({ row, first, onOpen }: { row: CaseListRow; first: boolean; onOpen: () => void }) {
  const hue = PRIORITY_HUE[row.priority] ?? PRIORITY_HUE.low
  return (
    <tr
      className="transition-colors hover:bg-slate-50/60"
      style={first ? undefined : { borderTop: HAIRLINE }}
    >
      <td className="px-5 py-3.5 align-top text-[13px]" style={{ color: INK }}>
        {row.subject_space_name ?? '—'}
      </td>
      <td className="px-5 py-3.5 align-top text-[13px]" style={{ color: INK_MUTED }}>
        {contentLabel(row.content_type)}
        {row.subject_member_name && <div className="mt-0.5 text-[11.5px]" style={{ color: INK_SOFTER }}>by {row.subject_member_name}</div>}
      </td>
      <td className="px-5 py-3.5 align-top text-[13px]" style={{ color: INK_MUTED }}>
        {row.category ? prettify(row.category) : '—'}
      </td>
      <td className="px-5 py-3.5 align-top text-[13px] tabular-nums" style={{ color: INK }}>
        {row.report_count}
      </td>
      <td className="px-5 py-3.5 align-top">
        <span
          className="inline-flex w-fit items-center whitespace-nowrap rounded-full px-2 py-[1px] text-[9.5px] font-semibold uppercase tracking-[0.06em]"
          style={{ background: hue.bg, border: `1px solid ${hue.border}`, color: hue.text }}
        >
          {PRIORITY_LABEL[row.priority] ?? row.priority}
        </span>
      </td>
      <td className="px-5 py-3.5 align-top text-[12.5px]" style={{ color: INK_MUTED }}>
        {STATUS_LABEL[row.status] ?? row.status}
      </td>
      <td className="px-5 py-3.5 align-top">
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center rounded-lg px-3 py-1 text-[11.5px] font-medium transition-colors hover:opacity-90"
          style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }}
        >
          Review
        </button>
      </td>
    </tr>
  )
}

function ReviewDrawer({
  caseId, onClose, onChange,
}: {
  caseId: string
  onClose: () => void
  onChange: () => void
}) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [noteBody, setNoteBody] = useState('')

  function reload() {
    fetch(apiUrl(`/api/admin/community-care/cases/${caseId}`), { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`Detail: ${r.status}`); return r.json() as Promise<CaseDetail> })
      .then(setDetail)
      .catch((e: Error) => setError(e.message))
  }
  useEffect(() => reload(), [caseId])   // eslint-disable-line react-hooks/exhaustive-deps

  async function setStatus(status: string) {
    setBusy(true)
    try {
      const res = await fetch(apiUrl(`/api/admin/community-care/cases/${caseId}/status`), {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      if (!res.ok) throw new Error(`Status: ${res.status}`)
      reload(); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function setPriority(priority: string) {
    setBusy(true)
    try {
      const res = await fetch(apiUrl(`/api/admin/community-care/cases/${caseId}/priority`), {
        method: 'PATCH', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority }),
      })
      if (!res.ok) throw new Error(`Priority: ${res.status}`)
      reload(); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function addNote() {
    if (!noteBody.trim()) return
    setBusy(true)
    try {
      const res = await fetch(apiUrl(`/api/admin/community-care/cases/${caseId}/notes`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: noteBody.trim() }),
      })
      if (!res.ok) throw new Error(`Note: ${res.status}`)
      setNoteBody('')
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function closeWithNoAction() {
    setBusy(true)
    try {
      const res = await fetch(apiUrl(`/api/admin/community-care/cases/${caseId}/close`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolution_actions: [] }),
      })
      if (!res.ok) throw new Error(`Close: ${res.status}`)
      onChange()
      onClose()
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  async function issueSupportive(payload: {
    kind: string
    affected_user_id: string
    explanation_to_recipient: string
    internal_note: string | null
  }) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/community-care/cases/${caseId}/actions/supportive`),
        {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Issue: ${res.status}`)
      }
      reload(); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function issueProtective(payload: Record<string, unknown>) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/community-care/cases/${caseId}/actions/protective`),
        {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Issue: ${res.status}`)
      }
      reload(); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function saveSummary(summary: string) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/community-care/cases/${caseId}/summary`),
        {
          method: 'PATCH', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ case_summary: summary }),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Save summary: ${res.status}`)
      }
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function resolveCase(payload: Record<string, unknown>) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/community-care/cases/${caseId}/close`),
        {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Resolve: ${res.status}`)
      }
      onChange()
      onClose()
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  async function reverseAction(actionId: string, reason: string) {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/community-care/actions/${actionId}/reverse`),
        {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reversal_reason: reason }),
        },
      )
      if (!res.ok) {
        const b = await res.json().catch(() => ({}))
        throw new Error(typeof b.detail === 'string' ? b.detail : `Reverse: ${res.status}`)
      }
      reload(); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end bg-black/40 p-0"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="h-full w-full max-w-[640px] overflow-y-auto"
        style={{ background: CARD_BG, boxShadow: CARD_SHADOW }}
      >
        <div className="flex items-start justify-between px-6 py-4" style={{ borderBottom: HAIRLINE }}>
          <div>
            <h2 className="font-serif text-[20px] leading-tight" style={{ color: INK }}>
              {detail?.case_number ?? 'Loading…'}
            </h2>
            {detail && (
              <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
                {contentLabel(detail.content_type)} · Opened {fmtDate(detail.opened_at)}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-[16px] leading-none transition-opacity hover:opacity-70"
            style={{ color: INK_MUTED }}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {error && (
          <div className="mx-6 mt-4 rounded-lg px-3 py-2 text-[12.5px]" style={{ background: 'rgba(214,96,87,0.08)', border: '1px solid rgba(214,96,87,0.28)', color: '#a63c30' }}>
            {error}
          </div>
        )}

        {!detail ? (
          <div className="px-6 py-10 text-[13px]" style={{ color: INK_MUTED }}>Loading…</div>
        ) : (
          <div className="space-y-6 px-6 py-5">
            {/* Status + priority controls */}
            <div className="grid grid-cols-2 gap-3">
              <FieldSelect
                label="Status"
                value={detail.status}
                disabled={busy || detail.status === 'resolved' || detail.status === 'closed_no_action'}
                onChange={setStatus}
                options={[
                  ['new', 'New'],
                  ['reviewing', 'Reviewing'],
                  ['waiting_info', 'Waiting for information'],
                  ['action_required', 'Action required'],
                ]}
              />
              <FieldSelect
                label="Priority"
                value={detail.priority}
                disabled={busy}
                onChange={setPriority}
                options={[
                  ['low', 'Low'],
                  ['moderate', 'Moderate'],
                  ['high', 'High'],
                  ['immediate', 'Immediate'],
                ]}
              />
            </div>

            {/* Case summary — Stage 2D operational record. Editable while
                the case is open; required before any final resolution. */}
            <CaseSummaryPanel
              detail={detail}
              busy={busy}
              onSave={saveSummary}
            />

            {/* Subject */}
            <Panel title="Subject">
              <KeyVal k="Collective" v={detail.subject_space_name ?? '—'} />
              {detail.subject_member_name && <KeyVal k="Member" v={detail.subject_member_name} />}
              {detail.subject_creator_name && <KeyVal k="Creator" v={detail.subject_creator_name} />}
              {detail.category && <KeyVal k="Category" v={prettify(detail.category)} />}
              {detail.creator_request_scope && <KeyVal k="Support scope" v={prettify(detail.creator_request_scope)} />}
            </Panel>

            {/* Signals — facts only, never recommendations */}
            <Panel title="Signals">
              <KeyVal k="Reports on this case" v={String(detail.signals.reports_on_case)} />
              <KeyVal k="Prior cases involving this member" v={String(detail.signals.prior_cases_for_member)} />
              <KeyVal k="Prior cases involving this creator" v={String(detail.signals.prior_cases_for_creator)} />
            </Panel>

            {/* Content snapshot */}
            {detail.content_snapshot && (
              <Panel title="Content snapshot">
                <pre className="whitespace-pre-wrap text-[12.5px]" style={{ color: INK, fontFamily: 'inherit' }}>
                  {String((detail.content_snapshot as Record<string, unknown>).body ?? '')}
                </pre>
              </Panel>
            )}

            {/* Reports */}
            <Panel title={`Reports (${detail.reports.length})`}>
              {detail.reports.length === 0 ? (
                <p className="text-[12.5px]" style={SERIF_ITALIC}>No reports on this case yet.</p>
              ) : (
                <ul className="space-y-2.5">
                  {detail.reports.map((r) => (
                    <li key={r.id}>
                      <div className="text-[13px]" style={{ color: INK }}>
                        {r.reporter_name ?? 'Unknown'} <span style={{ color: INK_MUTED }}>· {prettify(r.category)}</span>
                      </div>
                      {r.reporter_note && (
                        <div className="mt-1 text-[12.5px]" style={{ color: INK_MUTED }}>{r.reporter_note}</div>
                      )}
                      <div className="mt-0.5 text-[11.5px]" style={{ color: INK_SOFTER }}>{fmtDate(r.created_at)}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            {/* Timeline */}
            <Panel title="Timeline">
              <ul className="space-y-2">
                {detail.events.map((e) => (
                  <li key={e.id} className="text-[12.5px]" style={{ color: INK_MUTED }}>
                    <span style={{ color: INK }}>{prettify(e.kind)}</span>
                    {e.actor_name && <span> · {e.actor_name}</span>}
                    {e.reason && <span> · {e.reason}</span>}
                    <span> · {fmtDate(e.occurred_at)}</span>
                  </li>
                ))}
              </ul>
            </Panel>

            {/* Notes */}
            <Panel title={`Internal notes (${detail.notes.length})`}>
              {detail.notes.length === 0 ? (
                <p className="text-[12.5px]" style={SERIF_ITALIC}>No notes yet.</p>
              ) : (
                <ul className="mb-3 space-y-2.5">
                  {detail.notes.map((n) => (
                    <li key={n.id}>
                      <div className="text-[13px]" style={{ color: INK }}>{n.body}</div>
                      <div className="mt-0.5 text-[11.5px]" style={{ color: INK_SOFTER }}>
                        {n.author_name ?? 'Caretaker'} · {fmtDate(n.created_at)}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <textarea
                className="w-full rounded-lg px-3 py-2 text-[13px] outline-none focus:border-teal-300"
                style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
                rows={2}
                placeholder="Add an internal note"
                value={noteBody}
                onChange={(e) => setNoteBody(e.target.value)}
              />
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  disabled={busy || !noteBody.trim()}
                  onClick={addNote}
                  className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }}
                >
                  Add note
                </button>
              </div>
            </Panel>

            {/* Active protective measures — only rows that are still in effect */}
            <ActiveMeasuresPanel
              actions={detail.actions}
              onReverse={reverseAction}
              busy={busy}
            />

            {/* Issue action — supportive + protective pickers */}
            {detail.status !== 'resolved' && detail.status !== 'closed_no_action' && (
              <IssueActionPanel
                detail={detail}
                busy={busy}
                onIssueSupportive={issueSupportive}
                onIssueProtective={issueProtective}
              />
            )}

            {/* Resolve case — Stage 2D. Hosts both the no-action close
                path and the full resolution outcomes (restore /
                cancellation / closure). */}
            {detail.status !== 'resolved' && detail.status !== 'closed_no_action' && (
              <ResolveCasePanel
                detail={detail}
                busy={busy}
                onCloseNoAction={closeWithNoAction}
                onResolve={resolveCase}
              />
            )}

            {(detail.status === 'resolved' || detail.status === 'closed_no_action') && (
              <div className="rounded-lg p-4" style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }}>
                <div className="text-[13px] font-semibold">
                  {detail.status === 'resolved' ? 'This case has been resolved.' : 'This case is closed with no action.'}
                </div>
                {detail.resolution_summary && (
                  <div className="mt-2 text-[12.5px]" style={{ color: INK }}>
                    {detail.resolution_summary}
                  </div>
                )}
                <div className="mt-1 text-[12px]" style={{ color: INK_MUTED }}>
                  Notes may still be added for the record; no further actions can be issued.
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function FieldSelect({
  label, value, options, onChange, disabled,
}: {
  label: string
  value: string
  options: [string, string][]
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
        {label}
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full cursor-pointer appearance-none rounded-lg px-3 py-2 text-[13px] outline-none disabled:cursor-not-allowed disabled:opacity-70"
        style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
      >
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
        {title}
      </h3>
      <div className="rounded-xl p-4" style={{ background: PAGE_BG, border: HAIRLINE }}>
        {children}
      </div>
    </div>
  )
}

function KeyVal({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 text-[13px]">
      <span style={{ color: INK_MUTED }}>{k}</span>
      <span style={{ color: INK, textAlign: 'right' }}>{v}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Wellbeing + Principle cards (from Stage 1)
// ---------------------------------------------------------------------------

function WellbeingCard({
  emoji, label, value, subtitle, sage,
}: {
  emoji: string
  label: string
  value: string
  subtitle: string
  sage?: boolean
}) {
  return (
    <div
      className="relative overflow-hidden rounded-2xl px-5 py-5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      {sage && (
        <span aria-hidden className="absolute inset-x-0 top-0" style={{ height: 3, background: SAGE_DOT }} />
      )}
      <p
        className="flex items-center gap-2 text-[11.5px] font-semibold uppercase tracking-[0.10em]"
        style={{ color: INK_SOFTER }}
      >
        <span aria-hidden className="text-[14px] leading-none">{emoji}</span>
        <span>{label}</span>
      </p>
      <p className="mt-3 font-serif text-[28px] leading-none md:text-[32px]" style={{ color: sage ? SAGE_TEXT : INK }}>
        {value}
      </p>
      <p className="mt-2 text-[13px] leading-relaxed" style={SERIF_ITALIC}>{subtitle}</p>
    </div>
  )
}

function PrincipleCard({ title, body }: { title: string; body: string }) {
  return (
    <div
      className="rounded-2xl px-6 py-6"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <div
        className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-full"
        style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}` }}
      >
        <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: SAGE_DOT }} />
      </div>
      <h3 className="font-serif text-[17px] leading-tight" style={{ color: INK }}>{title}</h3>
      <p className="mt-2 text-[13.5px] leading-relaxed" style={{ color: 'rgba(12, 24, 38, 0.72)' }}>{body}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function prettify(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function contentLabel(t: string): string {
  const map: Record<string, string> = {
    post: 'Post',
    comment: 'Comment',
    member_behaviour: 'Member behaviour',
    creator_request: 'Creator support request',
    other: 'Other',
  }
  return map[t] ?? prettify(t)
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ---------------------------------------------------------------------------
// Community Care Stage 2C — action panels
// ---------------------------------------------------------------------------

const KIND_LABEL: Record<string, string> = {
  guidance: 'Guidance',
  reminder: 'Reminder',
  warning: 'Warning',
  content_hidden: 'Hide content',
  posting_restriction: 'Posting restriction',
  creator_restriction: 'Creator restriction',
  collective_freeze: 'Collective freeze',
  suspension_pending_review: 'Suspension pending review',
}

function isActive(a: CaseAction): boolean {
  if (a.layer !== 'protective') return false
  if (a.reversed_at) return false
  if (a.ends_at && new Date(a.ends_at).getTime() <= Date.now()) return false
  return true
}

function ActiveMeasuresPanel({
  actions, onReverse, busy,
}: {
  actions: CaseAction[]
  onReverse: (actionId: string, reason: string) => void
  busy: boolean
}) {
  const active = actions.filter(isActive)
  if (active.length === 0) return null
  return (
    <Panel title={`Active protective measures (${active.length})`}>
      <ul className="space-y-3">
        {active.map((a) => (
          <ActiveMeasureRow key={a.id} action={a} onReverse={onReverse} busy={busy} />
        ))}
      </ul>
    </Panel>
  )
}

function ActiveMeasureRow({
  action, onReverse, busy,
}: {
  action: CaseAction
  onReverse: (actionId: string, reason: string) => void
  busy: boolean
}) {
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  return (
    <li className="rounded-lg p-3" style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}` }}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold" style={{ color: SAGE_TEXT }}>
            {KIND_LABEL[action.kind] ?? prettify(action.kind)}
          </div>
          <div className="mt-0.5 text-[12px]" style={{ color: INK_MUTED }}>
            Issued {fmtDate(action.starts_at)}
            {action.issued_by_admin_name ? ` · ${action.issued_by_admin_name}` : ''}
          </div>
          {action.reason && (
            <div className="mt-1 text-[12.5px]" style={{ color: INK }}>{action.reason}</div>
          )}
        </div>
        {!confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy}
            className="shrink-0 rounded-full px-3 py-1 text-[12px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
          >
            Reverse
          </button>
        )}
      </div>
      {confirming && (
        <div className="mt-3">
          <label className="mb-1 block text-[11.5px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
            Reversal reason
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => { setConfirming(false); setReason('') }}
              className="rounded-full px-3 py-1 text-[12px]" style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || !reason.trim()}
              onClick={() => onReverse(action.id, reason.trim())}
              className="rounded-full px-3 py-1 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: '#a63c30' }}
            >
              Confirm reversal
            </button>
          </div>
        </div>
      )}
    </li>
  )
}

type SupportiveKind = 'guidance' | 'reminder' | 'warning'
type ProtectiveKind =
  | 'content_hidden'
  | 'posting_restriction'
  | 'creator_restriction'
  | 'collective_freeze'
  | 'suspension_pending_review'

function IssueActionPanel({
  detail, busy, onIssueSupportive, onIssueProtective,
}: {
  detail: CaseDetail
  busy: boolean
  onIssueSupportive: (payload: {
    kind: string
    affected_user_id: string
    explanation_to_recipient: string
    internal_note: string | null
  }) => void
  onIssueProtective: (payload: Record<string, unknown>) => void
}) {
  const [tab, setTab] = useState<'supportive' | 'protective'>('supportive')
  const [supportiveKind, setSupportiveKind] = useState<SupportiveKind>('guidance')
  const [protectiveKind, setProtectiveKind] = useState<ProtectiveKind>('content_hidden')
  const [explanation, setExplanation] = useState('')
  const [reason, setReason] = useState('')
  const [internalNote, setInternalNote] = useState('')
  const [confirming, setConfirming] = useState(false)

  const memberId = detail.subject_member_user_id
  const creatorId = detail.subject_creator_user_id
  const spaceId = detail.subject_space_id
  const postId = detail.subject_post_id
  const commentId = detail.subject_comment_id

  function protectiveTargetLabel(): string {
    if (protectiveKind === 'content_hidden') {
      if (postId) return `Post subject of this case`
      if (commentId) return `Comment subject of this case`
      return 'This case has no content subject to hide.'
    }
    if (protectiveKind === 'collective_freeze') {
      return spaceId ? `Collective: ${detail.subject_space_name ?? spaceId}` : 'No collective on this case'
    }
    if (protectiveKind === 'creator_restriction') {
      return creatorId ? `Creator: ${detail.subject_creator_name ?? creatorId}` : 'No creator on this case'
    }
    return memberId ? `Member: ${detail.subject_member_name ?? memberId}` : 'No member on this case'
  }

  function canSubmitSupportive(): boolean {
    return !!memberId && explanation.trim().length > 0 && !busy
  }
  function canSubmitProtective(): boolean {
    if (busy) return false
    if (!reason.trim()) return false
    if (protectiveKind === 'content_hidden') {
      return !!postId || !!commentId
    }
    if (protectiveKind === 'collective_freeze') {
      return !!spaceId && explanation.trim().length > 0
    }
    if (protectiveKind === 'creator_restriction') {
      return !!creatorId && explanation.trim().length > 0
    }
    // posting_restriction, suspension_pending_review
    return !!memberId && explanation.trim().length > 0
  }

  function submitSupportive() {
    if (!memberId) return
    onIssueSupportive({
      kind: supportiveKind,
      affected_user_id: memberId,
      explanation_to_recipient: explanation.trim(),
      internal_note: internalNote.trim() || null,
    })
    setExplanation('')
    setInternalNote('')
  }
  function submitProtective() {
    const payload: Record<string, unknown> = {
      kind: protectiveKind,
      reason: reason.trim(),
      internal_note: internalNote.trim() || null,
      explanation_to_recipient: explanation.trim() || null,
    }
    if (protectiveKind === 'content_hidden') {
      if (postId) payload.affected_post_id = postId
      else if (commentId) payload.affected_comment_id = commentId
    } else if (protectiveKind === 'collective_freeze') {
      payload.affected_space_id = spaceId
    } else if (protectiveKind === 'creator_restriction') {
      payload.affected_user_id = creatorId
    } else {
      payload.affected_user_id = memberId
      if (protectiveKind === 'posting_restriction' && spaceId) {
        payload.affected_space_id = spaceId
      }
    }
    onIssueProtective(payload)
    setReason(''); setExplanation(''); setInternalNote(''); setConfirming(false)
  }

  return (
    <Panel title="Issue an action">
      <div className="mb-3 flex gap-2">
        <button
          type="button"
          onClick={() => { setTab('supportive'); setConfirming(false) }}
          className="rounded-full px-3 py-1 text-[12.5px] font-medium"
          style={tab === 'supportive'
            ? { background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }
            : { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}
        >
          Supportive Response
        </button>
        <button
          type="button"
          onClick={() => { setTab('protective'); setConfirming(false) }}
          className="rounded-full px-3 py-1 text-[12.5px] font-medium"
          style={tab === 'protective'
            ? { background: 'rgba(214,96,87,0.10)', border: '1px solid rgba(214,96,87,0.30)', color: '#a63c30' }
            : { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}
        >
          Protective Measure
        </button>
      </div>

      {tab === 'supportive' ? (
        <div>
          <p className="mb-3 text-[12.5px]" style={SERIF_ITALIC}>
            Supportive Responses are educational. They notify the recipient but do not restrict access.
          </p>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>Kind</span>
            <select
              value={supportiveKind}
              onChange={(e) => setSupportiveKind(e.target.value as SupportiveKind)}
              className="w-full cursor-pointer rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              <option value="guidance">Guidance</option>
              <option value="reminder">Reminder</option>
              <option value="warning">Warning</option>
            </select>
          </label>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Recipient
            </span>
            <div className="rounded-lg px-3 py-2 text-[13px]" style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: memberId ? INK : INK_MUTED }}>
              {detail.subject_member_name ?? memberId ?? 'This case has no member subject; supportive responses require one.'}
            </div>
          </label>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Message to recipient
            </span>
            <textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              rows={3}
              placeholder="Explain in the recipient's own frame what happened and what to do next."
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Internal note (optional)
            </span>
            <textarea
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
              rows={2}
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!canSubmitSupportive()}
              onClick={submitSupportive}
              className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }}
            >
              Issue supportive response
            </button>
          </div>
        </div>
      ) : (
        <div>
          <p className="mb-3 text-[12.5px]" style={SERIF_ITALIC}>
            Protective Measures are temporary safeguards, not findings or punishments. Suspension pending review is the highest-impact measure and blocks all sign-in.
          </p>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>Kind</span>
            <select
              value={protectiveKind}
              onChange={(e) => { setProtectiveKind(e.target.value as ProtectiveKind); setConfirming(false) }}
              className="w-full cursor-pointer rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              <option value="content_hidden">Hide content</option>
              <option value="posting_restriction">Posting restriction</option>
              <option value="creator_restriction">Creator restriction</option>
              <option value="collective_freeze">Collective freeze</option>
              <option value="suspension_pending_review">Suspension pending review</option>
            </select>
          </label>
          <div className="mb-2 rounded-lg px-3 py-2 text-[12.5px]" style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}>
            Target: <span style={{ color: INK }}>{protectiveTargetLabel()}</span>
          </div>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Internal reason
            </span>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="Kept in the audit trail, not shown to the recipient."
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>
          {protectiveKind !== 'content_hidden' && (
            <label className="mb-2 block">
              <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
                Message to recipient
              </span>
              <textarea
                value={explanation}
                onChange={(e) => setExplanation(e.target.value)}
                rows={3}
                placeholder="Explain what applies now and how they can reach us."
                className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
                style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
              />
            </label>
          )}
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Internal note (optional)
            </span>
            <textarea
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
              rows={2}
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>

          {!confirming ? (
            <div className="flex justify-end">
              <button
                type="button"
                disabled={!canSubmitProtective()}
                onClick={() => setConfirming(true)}
                className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: 'rgba(214,96,87,0.10)', border: '1px solid rgba(214,96,87,0.30)', color: '#a63c30' }}
              >
                Issue protective measure
              </button>
            </div>
          ) : (
            <div className="rounded-lg p-3" style={{ background: 'rgba(214,96,87,0.06)', border: '1px solid rgba(214,96,87,0.28)' }}>
              <p className="mb-3 text-[12.5px]" style={{ color: '#a63c30' }}>
                {protectiveKind === 'suspension_pending_review'
                  ? 'Suspension pending review will immediately revoke sign-in for this person. Confirm to proceed.'
                  : 'This will apply the protective measure immediately. Confirm to proceed.'}
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="rounded-full px-3 py-1 text-[12px]" style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={submitProtective}
                  className="rounded-full px-3 py-1 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: '#a63c30' }}
                >
                  Confirm and issue
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

// ---------------------------------------------------------------------------
// Community Care Stage 2D — Case Summary + Resolve panels + Outcomes report
// ---------------------------------------------------------------------------


function CaseSummaryPanel({
  detail, busy, onSave,
}: {
  detail: CaseDetail
  busy: boolean
  onSave: (summary: string) => void
}) {
  const closed = detail.status === 'resolved' || detail.status === 'closed_no_action'
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(detail.case_summary ?? '')

  useEffect(() => {
    setText(detail.case_summary ?? '')
  }, [detail.case_summary])

  return (
    <Panel title="Case summary">
      {closed ? (
        <div className="text-[13px]" style={{ color: INK }}>
          {detail.case_summary?.trim() || <span style={SERIF_ITALIC}>No summary was recorded.</span>}
        </div>
      ) : editing ? (
        <div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={4}
            placeholder="A concise operational record explaining the outcome or state of this case."
            className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
            style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => { setEditing(false); setText(detail.case_summary ?? '') }}
              className="rounded-full px-3 py-1 text-[12px]"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => { onSave(text.trim()); setEditing(false) }}
              className="rounded-full px-3 py-1 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: SAGE_TEXT }}
            >
              Save summary
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="text-[13px]" style={{ color: INK }}>
            {detail.case_summary?.trim() ? (
              detail.case_summary
            ) : (
              <span style={SERIF_ITALIC}>
                No summary yet. A concise operational record is required before a final resolution.
              </span>
            )}
          </div>
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-full px-3 py-1 text-[12px]"
              style={{ background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }}
            >
              {detail.case_summary?.trim() ? 'Edit summary' : 'Write summary'}
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}


type ResolutionKind =
  | 'restore_content'
  | 'restore_account'
  | 'restore_collective'
  | 'account_cancellation'
  | 'creator_account_cancellation'
  | 'collective_closure_removal'


const RESOLUTION_KIND_LABEL: Record<ResolutionKind, string> = {
  restore_content: 'Restore content',
  restore_account: 'Restore account',
  restore_collective: 'Restore collective',
  account_cancellation: 'Account cancellation',
  creator_account_cancellation: 'Creator account cancellation',
  collective_closure_removal: 'Collective closure',
}


const CANCELLATION_KINDS: ReadonlySet<ResolutionKind> = new Set<ResolutionKind>([
  'account_cancellation',
  'creator_account_cancellation',
  'collective_closure_removal',
])


function ResolveCasePanel({
  detail, busy, onCloseNoAction, onResolve,
}: {
  detail: CaseDetail
  busy: boolean
  onCloseNoAction: () => void
  onResolve: (payload: Record<string, unknown>) => void
}) {
  const [tab, setTab] = useState<'no_action' | 'outcome'>('no_action')
  const [kind, setKind] = useState<ResolutionKind>('restore_content')
  const [explanation, setExplanation] = useState('')
  const [internalNote, setInternalNote] = useState('')
  const [confirming, setConfirming] = useState(false)

  const summaryReady = !!(detail.case_summary && detail.case_summary.trim())

  const memberId = detail.subject_member_user_id
  const creatorId = detail.subject_creator_user_id
  const spaceId = detail.subject_space_id
  const postId = detail.subject_post_id
  const commentId = detail.subject_comment_id

  function targetLabel(): string {
    switch (kind) {
      case 'restore_content':
        if (postId) return 'Restore the post subject of this case'
        if (commentId) return 'Restore the comment subject of this case'
        return 'This case has no content subject to restore.'
      case 'restore_account':
      case 'account_cancellation':
        return memberId ? `Member: ${detail.subject_member_name ?? memberId}` : 'No member on this case'
      case 'restore_collective':
      case 'collective_closure_removal':
        return spaceId ? `Collective: ${detail.subject_space_name ?? spaceId}` : 'No collective on this case'
      case 'creator_account_cancellation':
        return creatorId ? `Creator: ${detail.subject_creator_name ?? creatorId}` : 'No creator on this case'
    }
  }

  function canSubmit(): boolean {
    if (busy) return false
    if (!summaryReady) return false
    if (!explanation.trim()) return false
    if (kind === 'restore_content') return !!postId || !!commentId
    if (kind === 'restore_collective' || kind === 'collective_closure_removal') return !!spaceId
    if (kind === 'creator_account_cancellation') return !!creatorId
    return !!memberId
  }

  function submit() {
    const payload: Record<string, unknown> = {
      resolution_actions: [
        (() => {
          const action: Record<string, unknown> = {
            kind,
            explanation_to_recipient: explanation.trim(),
            internal_note: internalNote.trim() || null,
          }
          if (kind === 'restore_content') {
            if (postId) action.affected_post_id = postId
            else if (commentId) action.affected_comment_id = commentId
          } else if (kind === 'restore_collective' || kind === 'collective_closure_removal') {
            action.affected_space_id = spaceId
          } else if (kind === 'creator_account_cancellation') {
            action.affected_user_id = creatorId
          } else {
            action.affected_user_id = memberId
          }
          return action
        })(),
      ],
    }
    onResolve(payload)
    setConfirming(false)
  }

  const isCancellation = CANCELLATION_KINDS.has(kind)

  return (
    <Panel title="Resolve case">
      <div className="mb-3 flex gap-2">
        <button
          type="button"
          onClick={() => { setTab('no_action'); setConfirming(false) }}
          className="rounded-full px-3 py-1 text-[12.5px] font-medium"
          style={tab === 'no_action'
            ? { background: SAGE_BG, border: `1px solid ${SAGE_BORDER}`, color: SAGE_TEXT }
            : { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}
        >
          No Further Action
        </button>
        <button
          type="button"
          onClick={() => { setTab('outcome'); setConfirming(false) }}
          className="rounded-full px-3 py-1 text-[12.5px] font-medium"
          style={tab === 'outcome'
            ? { background: 'rgba(214,96,87,0.10)', border: '1px solid rgba(214,96,87,0.30)', color: '#a63c30' }
            : { background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}
        >
          Resolution Outcome
        </button>
      </div>

      {tab === 'no_action' ? (
        <div>
          <p className="mb-3 text-[12.5px]" style={SERIF_ITALIC}>
            Close the case as reviewed with no further action. Notes may still be added afterwards.
          </p>
          <div className="flex justify-end">
            <button
              type="button"
              disabled={busy}
              onClick={onCloseNoAction}
              className="rounded-full px-5 py-2 text-[13px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              Close with no action
            </button>
          </div>
        </div>
      ) : (
        <div>
          <p className="mb-3 text-[12.5px]" style={SERIF_ITALIC}>
            Resolution Outcomes are the final decisions from a completed investigation. They are recorded permanently in the case history.
          </p>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>Outcome</span>
            <select
              value={kind}
              onChange={(e) => { setKind(e.target.value as ResolutionKind); setConfirming(false) }}
              className="w-full cursor-pointer rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
            >
              {(Object.keys(RESOLUTION_KIND_LABEL) as ResolutionKind[]).map((k) => (
                <option key={k} value={k}>{RESOLUTION_KIND_LABEL[k]}</option>
              ))}
            </select>
          </label>
          <div className="mb-2 rounded-lg px-3 py-2 text-[12.5px]" style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK_MUTED }}>
            Target: <span style={{ color: INK }}>{targetLabel()}</span>
          </div>
          <label className="mb-2 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Message to recipient
            </span>
            <textarea
              value={explanation}
              onChange={(e) => setExplanation(e.target.value)}
              rows={3}
              placeholder="Explain the outcome and what has changed."
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              Internal note (optional)
            </span>
            <textarea
              value={internalNote}
              onChange={(e) => setInternalNote(e.target.value)}
              rows={2}
              className="w-full rounded-lg px-3 py-2 text-[13px] outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK, resize: 'none' }}
            />
          </label>
          {!summaryReady && (
            <div className="mb-3 rounded-lg px-3 py-2 text-[12px]" style={{ background: 'rgba(212,176,72,0.10)', border: '1px solid rgba(212,176,72,0.30)', color: '#8A6A15' }}>
              Write a Case summary above before you can record a resolution outcome.
            </div>
          )}

          {!confirming ? (
            <div className="flex justify-end">
              <button
                type="button"
                disabled={!canSubmit()}
                onClick={() => setConfirming(true)}
                className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: isCancellation ? '#a63c30' : SAGE_TEXT }}
              >
                Record resolution
              </button>
            </div>
          ) : (
            <div className="rounded-lg p-3" style={{ background: 'rgba(214,96,87,0.06)', border: '1px solid rgba(214,96,87,0.28)' }}>
              <p className="mb-2 text-[13px] font-semibold" style={{ color: '#a63c30' }}>
                {kind === 'account_cancellation' && 'Are you sure you want to cancel this account?'}
                {kind === 'creator_account_cancellation' && 'Are you sure you want to cancel this creator role?'}
                {kind === 'collective_closure_removal' && 'Are you sure you want to close this collective?'}
                {(kind === 'restore_content' || kind === 'restore_account' || kind === 'restore_collective') && 'Confirm this resolution outcome.'}
              </p>
              <p className="mb-3 text-[12.5px]" style={{ color: INK_MUTED }}>
                {kind === 'account_cancellation' &&
                  'This is a permanent resolution outcome. The member will no longer be able to access Fresh Collective. This action will be recorded in the Community Care history.'}
                {kind === 'creator_account_cancellation' &&
                  'This is a permanent resolution outcome. The person will retain member access but will no longer be a creator on Fresh Collective. Existing collectives are unaffected until you decide otherwise on a separate case.'}
                {kind === 'collective_closure_removal' &&
                  'This is a permanent resolution outcome. The collective will accept no new members, purchases, renewals, bookings, or creator changes. Existing content remains in Fresh Collective\u2019s records.'}
                {(kind === 'restore_content' || kind === 'restore_account' || kind === 'restore_collective') &&
                  'The temporary protective measure will be lifted as a final resolution outcome. The previous action remains in the case history.'}
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="rounded-full px-3 py-1 text-[12px]"
                  style={{ background: '#FFFFFF', border: '1px solid #E7EEF0', color: INK }}
                >
                  Go back
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={submit}
                  className="rounded-full px-3 py-1 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ background: isCancellation ? '#a63c30' : SAGE_TEXT }}
                >
                  {isCancellation
                    ? (kind === 'collective_closure_removal' ? 'Close collective' :
                       kind === 'creator_account_cancellation' ? 'Cancel creator role' : 'Cancel account')
                    : 'Confirm and record'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}


function OutcomeBreakdownSection({ counts }: { counts: OutcomeCounts }) {
  const rows: [label: string, value: number][] = [
    ['Guidance issued',       counts.guidance],
    ['Reminders issued',      counts.reminders],
    ['Warnings issued',       counts.warnings],
    ['Protective Measures',   counts.protective_measures],
    ['No Further Action',     counts.no_further_action],
    ['Account Cancellations', counts.account_cancellations],
    ['Creator Cancellations', counts.creator_cancellations],
    ['Collective Closures',   counts.collective_closures],
  ]
  const total = rows.reduce((s, [, v]) => s + v, 0)
  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="font-serif text-[22px] leading-tight" style={{ color: INK }}>
          Outcomes recorded
        </h2>
        <p className="mt-1 text-[12.5px]" style={SERIF_ITALIC}>
          Lifetime totals across every Community Care case. {total === 0 && 'Nothing has been recorded yet.'}
        </p>
      </div>
      <div
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
      >
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="rounded-2xl px-5 py-4"
            style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
          >
            <div className="text-[11.5px] font-semibold uppercase tracking-wide" style={{ color: INK_SOFTER }}>
              {label}
            </div>
            <div className="mt-1 font-serif text-[28px] leading-none" style={{ color: INK }}>
              {value}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
