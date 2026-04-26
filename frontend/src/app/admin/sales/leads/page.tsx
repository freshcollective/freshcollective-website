'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import {
  salesApi,
  type Lead,
  type LeadCreate,
  LEAD_STATUSES,
  PIPELINE_STAGES,
  INTEREST_LEVELS,
  fmtDate,
} from '@/lib/adminSalesApi'
import StatusBadge from '@/components/admin/StatusBadge'
import Modal from '@/components/admin/Modal'

const EMPTY: LeadCreate = { email: '' }

function LeadForm({
  initial,
  onSave,
  onCancel,
  saving,
  error,
}: {
  initial: LeadCreate
  onSave: (data: LeadCreate) => void
  onCancel: () => void
  saving: boolean
  error: string | null
}) {
  const [f, setF] = useState<LeadCreate>(initial)
  const set = (k: keyof LeadCreate, v: string) => setF((p) => ({ ...p, [k]: v || undefined }))

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSave(f) }}
      className="space-y-3"
    >
      {error && (
        <div className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">
          {error}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">First name</span>
          <input
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
            value={f.first_name ?? ''}
            onChange={(e) => set('first_name', e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Last name</span>
          <input
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
            value={f.last_name ?? ''}
            onChange={(e) => set('last_name', e.target.value)}
          />
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">
          Email <span className="text-red-500">*</span>
        </span>
        <input
          type="email"
          required
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
          value={f.email}
          onChange={(e) => setF((p) => ({ ...p, email: e.target.value }))}
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Phone</span>
          <input
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
            value={f.phone ?? ''}
            onChange={(e) => set('phone', e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Source</span>
          <input
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
            placeholder="e.g. Instagram, referral"
            value={f.source ?? ''}
            onChange={(e) => set('source', e.target.value)}
          />
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Status</span>
          <select
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
            value={f.status ?? 'prospect'}
            onChange={(e) => setF((p) => ({ ...p, status: e.target.value as Lead['status'] }))}
          >
            {LEAD_STATUSES.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Stage</span>
          <select
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
            value={f.current_stage ?? 'new_lead'}
            onChange={(e) => setF((p) => ({ ...p, current_stage: e.target.value as Lead['current_stage'] }))}
          >
            {PIPELINE_STAGES.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Interest level</span>
        <select
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.interest_level ?? ''}
          onChange={(e) => setF((p) => ({ ...p, interest_level: e.target.value as Lead['interest_level'] ?? undefined }))}
        >
          <option value="">— not set —</option>
          {INTEREST_LEVELS.map((l) => (
            <option key={l} value={l}>{l.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </label>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Notes</span>
        <textarea
          rows={3}
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400 focus:ring-1 focus:ring-teal-400"
          value={f.notes_summary ?? ''}
          onChange={(e) => set('notes_summary', e.target.value)}
        />
      </label>

      <div className="flex justify-end gap-2 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-4 py-2 text-[13px] font-medium text-[#64748B] hover:bg-[#F1F5F9]"
        >
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

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stageFilter, setStageFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showDeleted, setShowDeleted] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    salesApi
      .listLeads({
        stage: stageFilter || undefined,
        status: statusFilter || undefined,
        include_deleted: showDeleted || undefined,
      })
      .then(setLeads)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [stageFilter, statusFilter, showDeleted])

  useEffect(() => { load() }, [load])

  async function handleCreate(data: LeadCreate) {
    setSaving(true)
    setFormError(null)
    try {
      await salesApi.createLead(data)
      setShowCreate(false)
      load()
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : 'Error')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(lead: Lead) {
    if (!confirm(`Soft-delete lead ${lead.email}? The record is kept but marked deleted.`)) return
    setDeleting(lead.id)
    try {
      await salesApi.deleteLead(lead.id)
      load()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error deleting lead')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Leads</h1>
        <button
          onClick={() => { setShowCreate(true); setFormError(null) }}
          className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
        >
          + New lead
        </button>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-2">
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
        <select
          className="rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-[13px] bg-white outline-none"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          {LEAD_STATUSES.map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 rounded-lg border border-[#E2E8F0] bg-white px-3 py-1.5 text-[13px] cursor-pointer">
          <input
            type="checkbox"
            checked={showDeleted}
            onChange={(e) => setShowDeleted(e.target.checked)}
            className="accent-teal-500"
          />
          Show deleted
        </label>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading…
        </div>
      ) : error ? (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">
          {error}
        </div>
      ) : leads.length === 0 ? (
        <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
          No leads found.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white" style={{ border: '1px solid #E2E8F0' }}>
          <table className="w-full text-[13px]">
            <thead>
              <tr style={{ borderBottom: '1px solid #E2E8F0', background: '#F8F9FA' }}>
                {['Name', 'Email', 'Source', 'Status', 'Stage', 'Interest', 'Created', ''].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr
                  key={lead.id}
                  className="transition-colors hover:bg-[#F8F9FA]"
                  style={{ borderBottom: '1px solid #F1F5F9', opacity: lead.deleted_at ? 0.5 : 1 }}
                >
                  <td className="px-4 py-3 font-medium text-[#0F172A]">
                    {lead.first_name || lead.last_name
                      ? `${lead.first_name ?? ''} ${lead.last_name ?? ''}`.trim()
                      : '—'}
                  </td>
                  <td className="px-4 py-3 text-[#475569]">{lead.email}</td>
                  <td className="px-4 py-3 text-[#475569]">{lead.source ?? '—'}</td>
                  <td className="px-4 py-3"><StatusBadge value={lead.status} /></td>
                  <td className="px-4 py-3"><StatusBadge value={lead.current_stage} /></td>
                  <td className="px-4 py-3">
                    {lead.interest_level ? <StatusBadge value={lead.interest_level} /> : '—'}
                  </td>
                  <td className="px-4 py-3 text-[#94A3B8]">{fmtDate(lead.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/admin/sales/leads/${lead.id}`}
                        className="text-teal-600 hover:underline"
                      >
                        View
                      </Link>
                      {!lead.deleted_at && (
                        <button
                          onClick={() => handleDelete(lead)}
                          disabled={deleting === lead.id}
                          className="text-[#94A3B8] hover:text-red-500 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <Modal title="New lead" onClose={() => setShowCreate(false)}>
          <LeadForm
            initial={EMPTY}
            onSave={handleCreate}
            onCancel={() => setShowCreate(false)}
            saving={saving}
            error={formError}
          />
        </Modal>
      )}
    </div>
  )
}
