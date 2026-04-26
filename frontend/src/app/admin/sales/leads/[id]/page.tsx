'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  salesApi,
  type Lead,
  type LeadUpdate,
  type Activity,
  type ActivityCreate,
  type SalesTask,
  type TaskCreate,
  LEAD_STATUSES,
  PIPELINE_STAGES,
  INTEREST_LEVELS,
  ACTIVITY_TYPES,
  fmtDate,
} from '@/lib/adminSalesApi'
import StatusBadge from '@/components/admin/StatusBadge'
import Modal from '@/components/admin/Modal'

export default function LeadDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()

  const [lead, setLead] = useState<Lead | null>(null)
  const [activities, setActivities] = useState<Activity[]>([])
  const [tasks, setTasks] = useState<SalesTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [showEdit, setShowEdit] = useState(false)
  const [editData, setEditData] = useState<LeadUpdate>({})
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const [showActivity, setShowActivity] = useState(false)
  const [actForm, setActForm] = useState<ActivityCreate>({ title: '', activity_type: 'note' })
  const [actSaving, setActSaving] = useState(false)
  const [actError, setActError] = useState<string | null>(null)

  const [showTask, setShowTask] = useState(false)
  const [taskForm, setTaskForm] = useState<Omit<TaskCreate, 'lead_id'>>({ title: '' })
  const [taskSaving, setTaskSaving] = useState(false)
  const [taskError, setTaskError] = useState<string | null>(null)

  const loadAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      salesApi.getLead(id),
      salesApi.listActivities(id),
      salesApi.listTasks({ lead_id: id }),
    ])
      .then(([l, a, t]) => {
        setLead(l)
        setActivities(a)
        setTasks(t)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { loadAll() }, [loadAll])

  async function handleEdit() {
    setEditSaving(true)
    setEditError(null)
    try {
      await salesApi.updateLead(id, editData)
      setShowEdit(false)
      loadAll()
    } catch (e: unknown) {
      setEditError(e instanceof Error ? e.message : 'Error')
    } finally {
      setEditSaving(false)
    }
  }

  async function handleAddActivity() {
    setActSaving(true)
    setActError(null)
    try {
      await salesApi.createActivity(id, actForm)
      setShowActivity(false)
      setActForm({ title: '', activity_type: 'note' })
      loadAll()
    } catch (e: unknown) {
      setActError(e instanceof Error ? e.message : 'Error')
    } finally {
      setActSaving(false)
    }
  }

  async function handleAddTask() {
    setTaskSaving(true)
    setTaskError(null)
    try {
      await salesApi.createTask({ ...taskForm, lead_id: id })
      setShowTask(false)
      setTaskForm({ title: '' })
      loadAll()
    } catch (e: unknown) {
      setTaskError(e instanceof Error ? e.message : 'Error')
    } finally {
      setTaskSaving(false)
    }
  }

  async function handleCompleteTask(taskId: string) {
    try {
      await salesApi.completeTask(taskId)
      loadAll()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Error')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-8 text-[14px] text-[#64748B]">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-teal-500 border-t-transparent" />
        Loading…
      </div>
    )
  }

  if (error || !lead) {
    return (
      <div className="rounded-xl bg-red-50 p-4 text-[14px] text-red-600">
        {error ?? 'Lead not found.'}
      </div>
    )
  }

  return (
    <div>
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="mb-4 text-[13px] text-[#64748B] hover:text-[#0F172A]"
      >
        ← Back to leads
      </button>

      {/* Lead header */}
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.5rem] font-bold text-[#0F172A]">
            {lead.first_name || lead.last_name
              ? `${lead.first_name ?? ''} ${lead.last_name ?? ''}`.trim()
              : lead.email}
          </h1>
          <p className="mt-0.5 text-[14px] text-[#64748B]">{lead.email}</p>
        </div>
        <button
          onClick={() => {
          setEditData({
            email: lead.email,
            first_name: lead.first_name ?? undefined,
            last_name: lead.last_name ?? undefined,
            phone: lead.phone ?? undefined,
            source: lead.source ?? undefined,
            status: lead.status,
            current_stage: lead.current_stage,
            interest_level: lead.interest_level ?? undefined,
            notes_summary: lead.notes_summary ?? undefined,
          })
          setShowEdit(true)
        }}
          className="rounded-lg border border-[#E2E8F0] px-4 py-2 text-[13px] font-medium text-[#475569] hover:bg-[#F1F5F9]"
        >
          Edit
        </button>
      </div>

      {/* Lead info card */}
      <div className="mb-5 rounded-xl bg-white p-5" style={{ border: '1px solid #E2E8F0' }}>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[
            ['Phone', lead.phone ?? '—'],
            ['Source', lead.source ?? '—'],
            ['Status', null, lead.status],
            ['Stage', null, lead.current_stage],
            ['Interest', null, lead.interest_level ?? undefined],
            ['Created', fmtDate(lead.created_at)],
            ['Updated', fmtDate(lead.updated_at)],
            ['Deleted', lead.deleted_at ? fmtDate(lead.deleted_at) : null],
          ]
            .filter(([, v, badge]) => v !== null || badge !== undefined)
            .map(([label, value, badge]) => (
              <div key={label as string}>
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">
                  {label as string}
                </p>
                {badge ? (
                  <StatusBadge value={badge as string} />
                ) : (
                  <p className="text-[13px] text-[#0F172A]">{value as string}</p>
                )}
              </div>
            ))}
        </div>
        {lead.notes_summary && (
          <div className="mt-4 pt-4" style={{ borderTop: '1px solid #F1F5F9' }}>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#94A3B8]">Notes</p>
            <p className="text-[13px] leading-relaxed text-[#475569]">{lead.notes_summary}</p>
          </div>
        )}
      </div>

      {/* Activities */}
      <div className="mb-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-[#0F172A]">Activities</h2>
          <button
            onClick={() => { setShowActivity(true); setActError(null) }}
            className="rounded-lg bg-teal-500 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-teal-600"
          >
            + Add
          </button>
        </div>
        {activities.length === 0 ? (
          <div className="rounded-xl p-4 text-[13px] text-[#94A3B8]" style={{ border: '1px dashed #E2E8F0' }}>
            No activities yet.
          </div>
        ) : (
          <div className="space-y-2">
            {activities.map((a) => (
              <div key={a.id} className="rounded-xl bg-white p-4" style={{ border: '1px solid #E2E8F0' }}>
                <div className="mb-1 flex items-center gap-2">
                  <StatusBadge value={a.activity_type} />
                  <span className="text-[12px] text-[#94A3B8]">{fmtDate(a.occurred_at)}</span>
                </div>
                <p className="text-[13px] font-medium text-[#0F172A]">{a.title}</p>
                {a.body && <p className="mt-1 text-[13px] leading-relaxed text-[#475569]">{a.body}</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tasks */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-[#0F172A]">Tasks</h2>
          <button
            onClick={() => { setShowTask(true); setTaskError(null) }}
            className="rounded-lg bg-teal-500 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-teal-600"
          >
            + Add task
          </button>
        </div>
        {tasks.length === 0 ? (
          <div className="rounded-xl p-4 text-[13px] text-[#94A3B8]" style={{ border: '1px dashed #E2E8F0' }}>
            No tasks yet.
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((t) => {
              const overdue = !t.completed_at && t.due_at && new Date(t.due_at) < new Date()
              return (
                <div
                  key={t.id}
                  className="flex items-start justify-between gap-3 rounded-xl bg-white p-4"
                  style={{
                    border: `1px solid ${overdue ? '#FCA5A5' : '#E2E8F0'}`,
                    background: overdue ? '#FFF8F8' : 'white',
                  }}
                >
                  <div>
                    <p className={`text-[13px] font-medium ${t.completed_at ? 'line-through text-[#94A3B8]' : 'text-[#0F172A]'}`}>
                      {t.title}
                    </p>
                    {t.due_at && (
                      <p className={`mt-0.5 text-[12px] ${overdue ? 'text-red-500 font-medium' : 'text-[#94A3B8]'}`}>
                        {overdue ? 'Overdue · ' : 'Due '}
                        {fmtDate(t.due_at)}
                      </p>
                    )}
                    {t.completed_at && (
                      <p className="mt-0.5 text-[12px] text-green-600">Completed {fmtDate(t.completed_at)}</p>
                    )}
                  </div>
                  {!t.completed_at && (
                    <button
                      onClick={() => handleCompleteTask(t.id)}
                      className="shrink-0 rounded-lg border border-[#E2E8F0] px-3 py-1.5 text-[12px] font-medium text-[#475569] hover:border-green-300 hover:text-green-600"
                    >
                      Complete
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Edit modal */}
      {showEdit && (
        <Modal title="Edit lead" onClose={() => setShowEdit(false)}>
          {editError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{editError}</div>
          )}
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              {(['first_name', 'last_name'] as const).map((k) => (
                <label key={k} className="block">
                  <span className="mb-1 block text-[12px] font-medium text-[#64748B]">
                    {k === 'first_name' ? 'First name' : 'Last name'}
                  </span>
                  <input
                    className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                    value={(editData[k] as string | undefined) ?? ''}
                    onChange={(e) => setEditData((p) => ({ ...p, [k]: e.target.value || undefined }))}
                  />
                </label>
              ))}
            </div>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Email</span>
              <input
                type="email"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={editData.email ?? ''}
                onChange={(e) => setEditData((p) => ({ ...p, email: e.target.value }))}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Phone</span>
                <input
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  value={editData.phone ?? ''}
                  onChange={(e) => setEditData((p) => ({ ...p, phone: e.target.value || undefined }))}
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Source</span>
                <input
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  value={editData.source ?? ''}
                  onChange={(e) => setEditData((p) => ({ ...p, source: e.target.value || undefined }))}
                />
              </label>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Status</span>
                <select
                  className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                  value={editData.status ?? ''}
                  onChange={(e) => setEditData((p) => ({ ...p, status: e.target.value as Lead['status'] }))}
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
                  value={editData.current_stage ?? ''}
                  onChange={(e) => setEditData((p) => ({ ...p, current_stage: e.target.value as Lead['current_stage'] }))}
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
                value={editData.interest_level ?? ''}
                onChange={(e) => setEditData((p) => ({ ...p, interest_level: e.target.value as Lead['interest_level'] ?? undefined }))}
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
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={editData.notes_summary ?? ''}
                onChange={(e) => setEditData((p) => ({ ...p, notes_summary: e.target.value || undefined }))}
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowEdit(false)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleEdit}
                disabled={editSaving}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {editSaving ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Add activity modal */}
      {showActivity && (
        <Modal title="Add activity" onClose={() => setShowActivity(false)}>
          {actError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{actError}</div>
          )}
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Type</span>
              <select
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={actForm.activity_type}
                onChange={(e) => setActForm((p) => ({ ...p, activity_type: e.target.value as Activity['activity_type'] }))}
              >
                {ACTIVITY_TYPES.map((t) => (
                  <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Title <span className="text-red-500">*</span></span>
              <input
                required
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={actForm.title}
                onChange={(e) => setActForm((p) => ({ ...p, title: e.target.value }))}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Notes</span>
              <textarea
                rows={3}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={actForm.body ?? ''}
                onChange={(e) => setActForm((p) => ({ ...p, body: e.target.value || undefined }))}
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowActivity(false)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleAddActivity}
                disabled={actSaving || !actForm.title.trim()}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {actSaving ? 'Saving…' : 'Add activity'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* Add task modal */}
      {showTask && (
        <Modal title="Add task" onClose={() => setShowTask(false)}>
          {taskError && (
            <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-600">{taskError}</div>
          )}
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Title <span className="text-red-500">*</span></span>
              <input
                required
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={taskForm.title}
                onChange={(e) => setTaskForm((p) => ({ ...p, title: e.target.value }))}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Description</span>
              <textarea
                rows={2}
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={taskForm.description ?? ''}
                onChange={(e) => setTaskForm((p) => ({ ...p, description: e.target.value || undefined }))}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-[#64748B]">Due date</span>
              <input
                type="datetime-local"
                className="w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-[13px] outline-none focus:border-teal-400"
                value={taskForm.due_at ?? ''}
                onChange={(e) => setTaskForm((p) => ({ ...p, due_at: e.target.value || undefined }))}
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowTask(false)} className="rounded-lg px-4 py-2 text-[13px] text-[#64748B] hover:bg-[#F1F5F9]">
                Cancel
              </button>
              <button
                onClick={handleAddTask}
                disabled={taskSaving || !taskForm.title.trim()}
                className="rounded-lg bg-teal-500 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60 hover:bg-teal-600"
              >
                {taskSaving ? 'Saving…' : 'Add task'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
