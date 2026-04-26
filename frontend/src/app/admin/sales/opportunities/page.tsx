'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  salesApi,
  type Lead,
  type Opportunity,
  type OpportunityCreate,
  type OpportunityUpdate,
  type StageUpdate,
  PIPELINE_STAGES,
  formatCents,
  fmtDate,
  leadLabel,
} from '@/lib/adminSalesApi'
import StatusBadge from '@/components/admin/StatusBadge'
import Modal from '@/components/admin/Modal'

// ── Lead select ──────────────────────────────────────────────────────────────

function LeadSelect({
  value,
  onChange,
  leads,
  required,
}: {
  value: string
  onChange: (id: string) => void
  leads: Lead[]
  required?: boolean
}) {
  return (
    <select
      required={required}
      className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 bg-white"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">— select a lead —</option>
      {leads.map((l) => (
        <option key={l.id} value={l.id}>
          {leadLabel(l)}
        </option>
      ))}
    </select>
  )
}

// ── Opportunity form ─────────────────────────────────────────────────────────

function OppForm({
  initial,
  leads,
  onSave,
  onCancel,
  saving,
  error,
}: {
  initial: OpportunityCreate | OpportunityUpdate
  leads: Lead[]
  onSave: (data: OpportunityCreate | OpportunityUpdate) => void
  onCancel: () => void
  saving: boolean
  error: string | null
}) {
  const [f, setF] = useState(initial)
  const isCreate = 'lead_id' in initial

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(f) }} className="space-y-3">
      {error && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</div>
      )}

      {isCreate && (
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">
            Lead <span className="text-red-500">*</span>
          </span>
          <LeadSelect
            required
            value={(f as OpportunityCreate).lead_id ?? ''}
            onChange={(id) => setF((p) => ({ ...p, lead_id: id }))}
            leads={leads}
          />
        </label>
      )}

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Stage</span>
        <select
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.stage ?? 'new_lead'}
          onChange={(e) => setF((p) => ({ ...p, stage: e.target.value as Opportunity['stage'] }))}
        >
          {PIPELINE_STAGES.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Est. value ($)</span>
          <input
            type="number"
            min="0"
            step="0.01"
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
            placeholder="0.00"
            value={f.estimated_value_cents != null ? f.estimated_value_cents / 100 : ''}
            onChange={(e) => {
              const val = e.target.value ? Math.round(parseFloat(e.target.value) * 100) : undefined
              setF((p) => ({ ...p, estimated_value_cents: val }))
            }}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Probability (%)</span>
          <input
            type="number"
            min="0"
            max="100"
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
            placeholder="0–100"
            value={f.probability ?? ''}
            onChange={(e) => setF((p) => ({ ...p, probability: e.target.value ? parseInt(e.target.value) : undefined }))}
          />
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Expected close date</span>
        <input
          type="date"
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.expected_close_date ? f.expected_close_date.split('T')[0] : ''}
          onChange={(e) => setF((p) => ({ ...p, expected_close_date: e.target.value || undefined }))}
        />
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onCancel} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function OpportunitiesPage() {
  const [opps, setOpps] = useState<Opportunity[]>([])
  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stageFilter, setStageFilter] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [editing, setEditing] = useState<Opportunity | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const [movingStage, setMovingStage] = useState<Opportunity | null>(null)
  const [stageData, setStageData] = useState<StageUpdate>({ stage: 'new_lead' })
  const [stageSaving, setStageSaving] = useState(false)
  const [stageError, setStageError] = useState<string | null>(null)

  // Build a lookup map: lead_id → lead for table display
  const leadMap = new Map(leads.map((l) => [l.id, l]))

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      salesApi.listOpportunities({ stage: stageFilter || undefined }),
      salesApi.listLeads(),
    ])
      .then(([o, l]) => { setOpps(o); setLeads(l) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [stageFilter])

  useEffect(() => { load() }, [load])

  async function handleCreate(data: OpportunityCreate | OpportunityUpdate) {
    setCreateSaving(true)
    setCreateError(null)
    try {
      await salesApi.createOpportunity(data as OpportunityCreate)
      setShowCreate(false)
      load()
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Error')
    } finally {
      setCreateSaving(false)
    }
  }

  async function handleEdit(data: OpportunityCreate | OpportunityUpdate) {
    if (!editing) return
    setEditSaving(true)
    setEditError(null)
    try {
      await salesApi.updateOpportunity(editing.id, data as OpportunityUpdate)
      setEditing(null)
      load()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : 'Error')
    } finally {
      setEditSaving(false)
    }
  }

  async function handleMoveStage() {
    if (!movingStage) return
    setStageSaving(true)
    setStageError(null)
    try {
      await salesApi.moveOpportunityStage(movingStage.id, stageData)
      setMovingStage(null)
      load()
    } catch (e: unknown) {
      setStageError(e instanceof Error ? e.message : 'Error')
    } finally {
      setStageSaving(false)
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Opportunities</h1>
        <button
          onClick={() => { setShowCreate(true); setCreateError(null) }}
          className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
        >
          + New opportunity
        </button>
      </div>

      <div className="mb-4">
        <select
          className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-[13px] bg-white outline-none"
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value)}
        >
          <option value="">All stages</option>
          {PIPELINE_STAGES.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading…
        </div>
      ) : error ? (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">{error}</div>
      ) : opps.length === 0 ? (
        <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
          No opportunities found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <table className="w-full text-[13px]">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0', background: '#F8F9FA' }}>
                {['Lead', 'Stage', 'Est. Value', 'Probability', 'Close Date', 'Won/Lost', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {opps.map((opp) => {
                const lead = leadMap.get(opp.lead_id)
                return (
                  <tr key={opp.id} className="transition-colors hover:bg-[#F8F9FA]" style={{ borderBottom: '1px solid #F1F5F9' }}>
                    <td className="px-4 py-3">
                      {lead ? (
                        <span className="font-medium text-[#0F172A]">{leadLabel(lead)}</span>
                      ) : (
                        <span className="font-mono text-[11px] text-[#94A3B8]">{opp.lead_id.slice(0, 12)}…</span>
                      )}
                    </td>
                    <td className="px-4 py-3"><StatusBadge value={opp.stage} /></td>
                    <td className="px-4 py-3 font-medium text-[#0F172A]">
                      {opp.estimated_value_cents != null ? formatCents(opp.estimated_value_cents) : '—'}
                    </td>
                    <td className="px-4 py-3 text-[#475569]">
                      {opp.probability != null ? `${opp.probability}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-[#475569]">{fmtDate(opp.expected_close_date)}</td>
                    <td className="px-4 py-3">
                      {opp.won_at ? <span className="text-green-600 font-medium">Won {fmtDate(opp.won_at)}</span>
                        : opp.lost_at ? <span className="text-red-500 font-medium">Lost {fmtDate(opp.lost_at)}</span>
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => { setEditing(opp); setEditError(null) }}
                          className="text-teal-600 hover:underline"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => { setMovingStage(opp); setStageData({ stage: opp.stage }); setStageError(null) }}
                          className="text-[#94A3B8] hover:text-[#0F172A]"
                        >
                          Stage
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <Modal title="New opportunity" onClose={() => setShowCreate(false)}>
          <OppForm
            initial={{ lead_id: '', stage: 'new_lead' } as OpportunityCreate}
            leads={leads}
            onSave={handleCreate}
            onCancel={() => setShowCreate(false)}
            saving={createSaving}
            error={createError}
          />
        </Modal>
      )}

      {editing && (
        <Modal title="Edit opportunity" onClose={() => setEditing(null)}>
          <OppForm
            initial={{
              stage: editing.stage,
              plan_id: editing.plan_id ?? undefined,
              price_id: editing.price_id ?? undefined,
              estimated_value_cents: editing.estimated_value_cents ?? undefined,
              probability: editing.probability ?? undefined,
              expected_close_date: editing.expected_close_date ?? undefined,
              lost_reason: editing.lost_reason ?? undefined,
            }}
            leads={leads}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={editSaving}
            error={editError}
          />
        </Modal>
      )}

      {movingStage && (
        <Modal title="Move stage" onClose={() => setMovingStage(null)}>
          {stageError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{stageError}</div>
          )}
          <div className="space-y-3">
            {(() => {
              const lead = leadMap.get(movingStage.lead_id)
              return lead ? (
                <p className="text-[13px] text-[#64748B]">{leadLabel(lead)}</p>
              ) : null
            })()}
            <p className="text-[13px] text-[#64748B]">
              Current stage: <StatusBadge value={movingStage.stage} />
            </p>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">New stage</span>
              <select
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={stageData.stage}
                onChange={(e) => setStageData((p) => ({ ...p, stage: e.target.value as Opportunity['stage'] }))}
              >
                {PIPELINE_STAGES.map((s) => (
                  <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            {stageData.stage === 'lost' && (
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Lost reason</span>
                <textarea
                  rows={2}
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  value={stageData.lost_reason ?? ''}
                  onChange={(e) => setStageData((p) => ({ ...p, lost_reason: e.target.value || undefined }))}
                />
              </label>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setMovingStage(null)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleMoveStage}
                disabled={stageSaving}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {stageSaving ? 'Moving…' : 'Move stage'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
