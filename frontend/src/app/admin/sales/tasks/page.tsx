'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  salesApi,
  type SalesTask,
  type TaskCreate,
  type TaskUpdate,
  fmtDate,
} from '@/lib/adminSalesApi'
import Modal from '@/components/admin/Modal'

type FilterMode = 'open' | 'completed' | 'all'

function TaskForm({
  initial,
  isEdit,
  onSave,
  onCancel,
  saving,
  error,
}: {
  initial: TaskCreate | TaskUpdate
  isEdit: boolean
  onSave: (data: TaskCreate | TaskUpdate) => void
  onCancel: () => void
  saving: boolean
  error: string | null
}) {
  const [f, setF] = useState(initial)

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(f) }} className="space-y-3">
      {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{error}</div>}

      {!isEdit && (
        <label className="block">
          <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Lead ID <span className="text-red-500">*</span></span>
          <input
            required
            className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] font-mono outline-none focus:border-teal-400"
            placeholder="lead UUID"
            value={(f as TaskCreate).lead_id ?? ''}
            onChange={(e) => setF((p) => ({ ...p, lead_id: e.target.value }))}
          />
        </label>
      )}

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Title <span className="text-red-500">*</span></span>
        <input
          required
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.title ?? ''}
          onChange={(e) => setF((p) => ({ ...p, title: e.target.value }))}
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Description</span>
        <textarea
          rows={2}
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.description ?? ''}
          onChange={(e) => setF((p) => ({ ...p, description: e.target.value || undefined }))}
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Due date</span>
        <input
          type="datetime-local"
          className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
          value={f.due_at ? f.due_at.slice(0, 16) : ''}
          onChange={(e) => setF((p) => ({ ...p, due_at: e.target.value || undefined }))}
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

export default function TasksPage() {
  const [tasks, setTasks] = useState<SalesTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterMode>('open')

  const [showCreate, setShowCreate] = useState(false)
  const [createSaving, setCreateSaving] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [editing, setEditing] = useState<SalesTask | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const [completing, setCompleting] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    const params =
      filter === 'open' ? { completed: false }
      : filter === 'completed' ? { completed: true }
      : {}
    salesApi.listTasks(params)
      .then(setTasks)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

  useEffect(() => { load() }, [load])

  async function handleCreate(data: TaskCreate | TaskUpdate) {
    setCreateSaving(true)
    setCreateError(null)
    try {
      await salesApi.createTask(data as TaskCreate)
      setShowCreate(false)
      load()
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : 'Error')
    } finally {
      setCreateSaving(false)
    }
  }

  async function handleEdit(data: TaskCreate | TaskUpdate) {
    if (!editing) return
    setEditSaving(true)
    setEditError(null)
    try {
      await salesApi.updateTask(editing.id, data as TaskUpdate)
      setEditing(null)
      load()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : 'Error')
    } finally {
      setEditSaving(false)
    }
  }

  async function handleComplete(id: string) {
    setCompleting(id)
    try {
      await salesApi.completeTask(id)
      load()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error')
    } finally {
      setCompleting(null)
    }
  }

  const now = new Date()

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[1.5rem] font-bold text-[#0F172A]">Tasks</h1>
        <button
          onClick={() => { setShowCreate(true); setCreateError(null) }}
          className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white hover:bg-teal-600"
        >
          + New task
        </button>
      </div>

      {/* Filter tabs */}
      <div className="mb-4 flex gap-1 rounded-lg p-1 w-fit" style={{ background: '#F1F5F9' }}>
        {(['open', 'completed', 'all'] as FilterMode[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors capitalize ${
              filter === f ? 'bg-white text-[#0F172A] shadow-sm' : 'text-[#64748B] hover:text-[#0F172A]'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
          Loading…
        </div>
      ) : error ? (
        <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">{error}</div>
      ) : tasks.length === 0 ? (
        <div className="rounded-xl bg-white p-8 text-center text-[14px] text-[#94A3B8]" style={{ border: '1px solid #E2E8F0' }}>
          No tasks found.
        </div>
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => {
            const overdue = !t.completed_at && t.due_at && new Date(t.due_at) < now
            return (
              <div
                key={t.id}
                className="flex items-start justify-between gap-3 rounded-xl bg-white p-4"
                style={{
                  border: `1px solid ${overdue ? '#FCA5A5' : '#E2E8F0'}`,
                  background: overdue ? '#FFF8F8' : t.completed_at ? '#F8FFF8' : 'white',
                }}
              >
                <div className="flex-1 min-w-0">
                  <p className={`text-[13px] font-medium leading-snug ${t.completed_at ? 'line-through text-[#94A3B8]' : 'text-[#0F172A]'}`}>
                    {t.title}
                  </p>
                  {t.description && (
                    <p className="mt-0.5 text-[12px] text-[#64748B]">{t.description}</p>
                  )}
                  <div className="mt-1 flex flex-wrap gap-3">
                    {t.due_at && (
                      <span className={`text-[12px] ${overdue ? 'text-red-500 font-semibold' : 'text-[#94A3B8]'}`}>
                        {overdue ? '⚠ Overdue · ' : ''}Due {fmtDate(t.due_at)}
                      </span>
                    )}
                    {t.completed_at && (
                      <span className="text-[12px] text-green-600">✓ Completed {fmtDate(t.completed_at)}</span>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <button
                    onClick={() => { setEditing(t); setEditError(null) }}
                    className="text-[12px] text-[#94A3B8] hover:text-[#0F172A]"
                  >
                    Edit
                  </button>
                  {!t.completed_at && (
                    <button
                      onClick={() => handleComplete(t.id)}
                      disabled={completing === t.id}
                      className="rounded-lg border border-[#E2E8F0] px-3 py-1 text-[12px] font-medium text-[#475569] hover:border-green-300 hover:text-green-600 disabled:opacity-50"
                    >
                      {completing === t.id ? '…' : 'Complete'}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showCreate && (
        <Modal title="New task" onClose={() => setShowCreate(false)}>
          <TaskForm
            initial={{ lead_id: '', title: '' } as TaskCreate}
            isEdit={false}
            onSave={handleCreate}
            onCancel={() => setShowCreate(false)}
            saving={createSaving}
            error={createError}
          />
        </Modal>
      )}

      {editing && (
        <Modal title="Edit task" onClose={() => setEditing(null)}>
          <TaskForm
            initial={{
              title: editing.title,
              description: editing.description ?? undefined,
              due_at: editing.due_at ?? undefined,
              assigned_to_user_id: editing.assigned_to_user_id ?? undefined,
            }}
            isEdit={true}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={editSaving}
            error={editError}
          />
        </Modal>
      )}
    </div>
  )
}
