'use client'

/**
 * One email: its wording on the left, the real thing on the right.
 *
 * Editing is deliberately plain. Every field the backend declares is
 * shown and nothing else — there is no generic "body", because these
 * templates interleave Fresh Collective's voice with generated fact
 * inside a single paragraph, and one body field would hand both to an
 * admin at once. What the system owns is named in words rather than
 * shown as a disabled input pretending it might open later.
 *
 * Saving takes effect on the next send. There is no publish step and no
 * draft state: what the editor shows as current is what the next member
 * receives.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiUrl } from '@/lib/api'
import {
  STALE_DEFAULT_MESSAGE,
  defaultVariantSelection,
  dirtySlots,
  initialDrafts,
  missingRequiredFields,
  overLength,
  previewBody,
  savePayload,
  slotIsCustomised,
  testSendConfirmation,
} from '@/lib/emailTemplates'
import type {
  Drafts, PreviewMode, PreviewResponse, TemplateDetail, VariantSelection,
} from '@/lib/emailTemplates'
import MergeFieldsPanel from './MergeFieldsPanel'
import PreviewPane from './PreviewPane'
import {
  ClassificationPill, DeliveryPill, Divider, ErrorNote, Muted,
  PrimaryButton, QuietButton, StatePill, StalePill,
} from './Bits'
import {
  CARD_BG, CARD_BORDER, CARD_SHADOW, FIELD_BORDER, GOLD, HAIRLINE, INK,
  INK_MUTED, INK_SOFTER, SERIF_ITALIC, TEAL,
} from './tokens'

const BASE = '/api/admin/communications/email-templates'
const PREVIEW_DEBOUNCE_MS = 350

export default function TemplateDetailView({
  templateKey, adminEmail, onBack, onChanged,
}: {
  templateKey: string
  adminEmail: string
  onBack: () => void
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<TemplateDetail | null>(null)
  const [drafts, setDrafts] = useState<Drafts>({})
  const [selection, setSelection] = useState<VariantSelection>({})
  const [mode, setMode] = useState<PreviewMode>('effective')
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({})
  const [notice, setNotice] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)

  const adopt = useCallback((next: TemplateDetail) => {
    setDetail(next)
    setDrafts(initialDrafts(next))
    setSelection((prev) =>
      Object.keys(prev).length ? prev : defaultVariantSelection(next),
    )
    setFieldErrors({})
  }, [])

  useEffect(() => {
    let live = true
    fetch(apiUrl(`${BASE}/${templateKey}`), { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: TemplateDetail) => { if (live) adopt(d) })
      .catch(() => { if (live) setProblem('That email could not be loaded.') })
    return () => { live = false }
  }, [templateKey, adopt])

  // Preview follows the drafts, debounced. Every render comes from the
  // API — nothing is approximated here.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!detail) return
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      // Only once the request is genuinely in flight — a spinner that
      // appears on every keystroke is noise, not feedback.
      setPreviewing(true)
      fetch(apiUrl(`${BASE}/${templateKey}/preview`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(previewBody(detail, mode, drafts, selection)),
      })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((p: PreviewResponse) => setPreview(p))
        .catch(() => setPreview(null))
        .finally(() => setPreviewing(false))
    }, PREVIEW_DEBOUNCE_MS)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [detail, templateKey, mode, drafts, selection])

  const changed = useMemo(
    () => (detail ? dirtySlots(detail, drafts) : []), [detail, drafts],
  )

  async function save() {
    if (!detail) return
    setSaving(true)
    setProblem(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`${BASE}/${templateKey}`), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(savePayload(detail, drafts)),
      })
      if (res.status === 422) {
        const body = await res.json()
        setFieldErrors(body?.detail?.errors ?? {})
        setProblem('Some wording needs another look.')
        return
      }
      if (!res.ok) throw new Error(String(res.status))
      adopt(await res.json())
      setNotice('Saved. The next email sent uses this wording.')
      onChanged()
    } catch {
      setProblem('That could not be saved. Nothing was changed.')
    } finally {
      setSaving(false)
    }
  }

  async function resetSlot(slotId: string) {
    await mutate(`${BASE}/${templateKey}/slots/${slotId}`, 'Back to the Fresh Collective default.')
  }

  async function resetAll() {
    setConfirmReset(false)
    await mutate(`${BASE}/${templateKey}`, 'Every field is back to the Fresh Collective default.')
  }

  async function mutate(path: string, message: string) {
    setProblem(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(path), {
        method: 'DELETE', credentials: 'include',
      })
      if (!res.ok) throw new Error(String(res.status))
      adopt(await res.json())
      setNotice(message)
      onChanged()
    } catch {
      setProblem('That could not be reset. Nothing was changed.')
    }
  }

  /** Re-save the admin's own wording, which re-stamps it against the
   *  new default and clears the warning without changing a word. */
  async function keepMyVersion(slotId: string) {
    if (!detail) return
    setProblem(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`${BASE}/${templateKey}`), {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ overrides: { [slotId]: drafts[slotId] } }),
      })
      if (!res.ok) throw new Error(String(res.status))
      adopt(await res.json())
      setNotice('Kept your wording.')
      onChanged()
    } catch {
      setProblem('That could not be saved. Nothing was changed.')
    }
  }

  async function sendTest() {
    if (!detail) return
    setProblem(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`${BASE}/${templateKey}/test-send`), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        // Always the current wording, whichever way the preview
        // toggle happens to be set — a test exists to check an edit
        // before committing to it.
        body: JSON.stringify(previewBody(detail, 'effective', drafts, selection)),
      })
      if (!res.ok) throw new Error(String(res.status))
      const body = await res.json()
      setNotice(testSendConfirmation(body.sent_to ?? adminEmail))
    } catch {
      setProblem('The test email could not be sent.')
    }
  }

  if (problem && !detail) {
    return (
      <div className="flex flex-col gap-4">
        <BackLink onBack={onBack} />
        <Muted>{problem}</Muted>
      </div>
    )
  }
  if (!detail) {
    return (
      <div className="flex flex-col gap-4">
        <BackLink onBack={onBack} />
        <p className="text-[14px]" style={SERIF_ITALIC}>Opening…</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <BackLink onBack={onBack} />

      <header className="flex flex-col gap-2">
        <h1
          className="text-[24px] font-semibold"
          style={{ color: INK, letterSpacing: '-0.02em' }}
        >
          {detail.display_name}
        </h1>
        <div className="flex flex-wrap items-center gap-2">
          <ClassificationPill value={detail.classification} />
          {detail.editable && <StatePill customised={detail.customised} />}
          <DeliveryPill transactional={detail.is_transactional} />
        </div>
        <Muted>{detail.audience}</Muted>
      </header>

      {(notice || problem) && (
        <div
          className="rounded-lg px-4 py-3 text-[13px]"
          style={
            problem
              ? { background: 'rgba(214,96,87,0.07)', border: '1px solid rgba(214,96,87,0.26)', color: '#a63c30' }
              : { background: TEAL.bg, border: `1px solid ${TEAL.border}`, color: TEAL.text }
          }
        >
          {problem ?? notice}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
        {/* Left — the wording */}
        <div className="flex min-w-0 flex-col gap-5">
          {detail.editable ? (
            <>
              {detail.classification === 'partial' && (
                <PartialNote notes={detail.locked_notes} />
              )}
              <div
                className="flex flex-col rounded-xl"
                style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                {detail.slots.map((slot, i) => {
                  const value = drafts[slot.slot_id] ?? slot.effective
                  const customised = slotIsCustomised(slot, value)
                  const missing = missingRequiredFields(slot, value)
                  const long = overLength(slot, value)
                  const errors = fieldErrors[slot.slot_id] ?? []
                  return (
                    <div
                      key={slot.slot_id}
                      className="flex flex-col gap-2 px-4 py-4"
                      style={i > 0 ? { borderTop: HAIRLINE } : undefined}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <label
                          htmlFor={`slot-${slot.slot_id}`}
                          className="text-[13px] font-semibold"
                          style={{ color: INK }}
                        >
                          {slot.label}
                        </label>
                        <div className="flex items-center gap-2">
                          <StatePill customised={customised} />
                          {slot.customised && (
                            <QuietButton onClick={() => resetSlot(slot.slot_id)}>
                              Reset to default
                            </QuietButton>
                          )}
                        </div>
                      </div>

                      {slot.help_text && (
                        <p className="text-[12px]" style={{ color: INK_SOFTER }}>
                          {slot.help_text}
                        </p>
                      )}

                      {slot.multiline ? (
                        <textarea
                          id={`slot-${slot.slot_id}`}
                          value={value}
                          rows={3}
                          onChange={(e) => setDrafts({ ...drafts, [slot.slot_id]: e.target.value })}
                          className="w-full resize-y rounded-lg px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-[#22a598]"
                          style={{ border: FIELD_BORDER, color: INK }}
                        />
                      ) : (
                        <input
                          id={`slot-${slot.slot_id}`}
                          type="text"
                          value={value}
                          onChange={(e) => setDrafts({ ...drafts, [slot.slot_id]: e.target.value })}
                          className="w-full rounded-lg px-3 py-2 text-[13px] outline-none focus:border-[#22a598]"
                          style={{ border: FIELD_BORDER, color: INK }}
                        />
                      )}

                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-col gap-1">
                          {missing.map((f) => (
                            <ErrorNote key={f}>
                              Keep {`{{${f}}}`} — the email needs it to stay true.
                            </ErrorNote>
                          ))}
                          {long && (
                            <ErrorNote>
                              {value.length} characters; the limit is {slot.max_length}.
                            </ErrorNote>
                          )}
                          {errors.map((e) => <ErrorNote key={e}>{e}</ErrorNote>)}
                        </div>
                        <span className="text-[11px]" style={{ color: INK_SOFTER }}>
                          {value.length}/{slot.max_length}
                        </span>
                      </div>

                      {slot.default_changed && (
                        <StaleDefaultNotice
                          current={value}
                          nextDefault={slot.default}
                          onKeep={() => keepMyVersion(slot.slot_id)}
                          onReset={() => resetSlot(slot.slot_id)}
                        />
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <PrimaryButton onClick={save} disabled={saving || changed.length === 0}>
                  {saving ? 'Saving…' : 'Save changes'}
                </PrimaryButton>
                <QuietButton onClick={sendTest}>Send test email</QuietButton>
                <QuietButton
                  tone="danger"
                  disabled={!detail.customised}
                  onClick={() => setConfirmReset(true)}
                >
                  Reset all to Fresh Collective default
                </QuietButton>
              </div>
              <p className="text-[12px]" style={{ color: INK_SOFTER }}>
                Saved wording takes effect on the next email sent. A test goes
                only to {adminEmail}, using your current wording whether or not it
                is saved.
              </p>

              {confirmReset && (
                <ConfirmReset
                  count={detail.slots.filter((s) => s.customised).length}
                  onCancel={() => setConfirmReset(false)}
                  onConfirm={resetAll}
                />
              )}
            </>
          ) : (
            <SystemNotice notes={detail.locked_notes} />
          )}

          <MergeFieldsPanel fields={detail.merge_fields} />
        </div>

        {/* Right — the email itself */}
        <div className="min-w-0">
          <PreviewPane
            preview={preview}
            loading={previewing}
            mode={mode}
            onModeChange={setMode}
            variants={detail.preview_variants}
            selection={selection}
            onSelect={(id, value) => setSelection({ ...selection, [id]: value })}
          />
        </div>
      </div>
    </div>
  )
}

function BackLink({ onBack }: { onBack: () => void }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="self-start text-[13px] transition-colors hover:text-[#0f766e]"
      style={{ color: INK_MUTED }}
    >
      ← All email templates
    </button>
  )
}

function PartialNote({ notes }: { notes: string[] }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-xl px-4 py-3"
      style={{ background: 'rgba(56,116,180,0.05)', border: '1px solid rgba(56,116,180,0.22)' }}
    >
      <p className="text-[13px] font-medium" style={{ color: '#1e40af' }}>
        Some of this email is written by Fresh Collective
      </p>
      <ul className="flex flex-col gap-1">
        {notes.map((n) => (
          <li key={n} className="text-[12px] leading-relaxed" style={{ color: INK_MUTED }}>
            {n}
          </li>
        ))}
      </ul>
    </div>
  )
}

function SystemNotice({ notes }: { notes: string[] }) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl px-5 py-5"
      style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
    >
      <h2 className="text-[15px] font-semibold" style={{ color: INK }}>
        Fresh Collective writes this one
      </h2>
      <p className="text-[13px] leading-relaxed" style={{ color: INK_MUTED }}>
        This email states facts about money, access or security. Its wording is
        managed by Fresh Collective so it always matches what actually
        happened. You can read it here, exactly as a member receives it.
      </p>
      {notes.length > 0 && (
        <>
          <Divider />
          <ul className="flex flex-col gap-1.5">
            {notes.map((n) => (
              <li key={n} className="text-[13px] leading-relaxed" style={SERIF_ITALIC}>
                {n}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function StaleDefaultNotice({
  current, nextDefault, onKeep, onReset,
}: {
  current: string
  nextDefault: string
  onKeep: () => void
  onReset: () => void
}) {
  return (
    <div
      className="flex flex-col gap-3 rounded-lg px-3 py-3"
      style={{ background: GOLD.bg, border: `1px solid ${GOLD.border}` }}
    >
      <div className="flex items-center gap-2">
        <StalePill label="Default has changed" />
      </div>
      <p className="text-[12px] leading-relaxed" style={{ color: GOLD.text }}>
        {STALE_DEFAULT_MESSAGE} Your wording is still being sent — nothing has
        been overwritten.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Comparison label="Your version" value={current} />
        <Comparison label="New Fresh Collective default" value={nextDefault} />
      </div>
      <div className="flex flex-wrap gap-2">
        <QuietButton onClick={onKeep}>Keep my version</QuietButton>
        <QuietButton onClick={onReset}>Use the new default</QuietButton>
      </div>
    </div>
  )
}

function Comparison({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium" style={{ color: GOLD.text }}>
        {label}
      </span>
      <p
        className="rounded-md px-2 py-1.5 text-[12px] leading-relaxed"
        style={{ background: '#FFFFFF', color: INK_MUTED, border: HAIRLINE }}
      >
        {value}
      </p>
    </div>
  )
}

function ConfirmReset({
  count, onCancel, onConfirm,
}: {
  count: number
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30" onClick={onCancel} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Reset this email to the Fresh Collective default"
        className="relative flex w-full max-w-[420px] flex-col gap-4 rounded-xl p-5"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: '0 12px 40px rgba(16,24,40,0.18)' }}
      >
        <h2 className="text-[16px] font-semibold" style={{ color: INK }}>
          Reset this email to the Fresh Collective default?
        </h2>
        <p className="text-[13px] leading-relaxed" style={{ color: INK_MUTED }}>
          {count === 1
            ? 'Your one edited field will be deleted.'
            : `All ${count} of your edited fields will be deleted.`}{' '}
          Future emails will use Fresh Collective&rsquo;s current wording, and
          will follow it if it changes again later.
        </p>
        <div className="flex justify-end gap-2">
          <QuietButton onClick={onCancel}>Keep my wording</QuietButton>
          <PrimaryButton onClick={onConfirm}>Reset to default</PrimaryButton>
        </div>
      </div>
    </div>
  )
}
