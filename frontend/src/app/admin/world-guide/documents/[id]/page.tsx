'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { apiUrl, extractErrorMessage, type ApiError } from '@/lib/api'
import WorldGuideProse from '@/components/world-guide/WorldGuideProse'
import WriteModeEditor, { type WriteModeHandle } from '@/components/world-guide/tiptap/WriteModeEditor'
import {
  AUDIENCE_LABEL,
  CATEGORY_LABEL,
  continueListOnEnter,
  parseImportedMarkdown,
  WG,
  type DocumentDetail,
  type VersionSummary,
  type ImportResult,
} from '@/lib/worldGuide'

/**
 * World Guide — document editor.
 *
 * Writing-first layout. The main writing area occupies ~90% of the
 * available width; metadata and AI live in right-side drawers that
 * open on demand. The Markdown editor and the live preview render
 * from the *same* component the public World Guide uses, so preview
 * and published can never disagree.
 */

type Section = 'why_this_exists' | 'what_this_covers' | 'main_content' | 'whats_changed'

const SECTIONS: [key: Section, label: string, hint: string][] = [
  ['why_this_exists',  'Why this exists',
    'The purpose of this document in a paragraph or two.'],
  ['what_this_covers', 'What this covers',
    'A short outline of the ground this document covers.'],
  ['main_content',     'Main content',
    'The document itself. Markdown: headings, lists, links, tables, callouts.'],
  ['whats_changed',    "What’s changed",
    'Release notes for this version. What a returning reader should know.'],
]


export default function DocumentEditorPage() {
  const params = useParams()
  const router = useRouter()
  const id = String(params.id)

  const [doc, setDoc] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [activeSection, setActiveSection] = useState<Section>('main_content')
  const [showPreview, setShowPreview] = useState(true)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  /** Which writing surface is active. Applies across every section so a
   *  writer does not have to choose a mode again on section switch. */
  const [writingMode, setWritingMode] = useState<'write' | 'markdown'>('write')
  const writeEditorRef = useRef<WriteModeHandle | null>(null)

  // Draft content edit state (mirrors the four textarea values).
  const [draftContent, setDraftContent] = useState<Record<Section, string>>({
    why_this_exists: '', what_this_covers: '', main_content: '', whats_changed: '',
  })
  const [draftEffective, setDraftEffective] = useState('')
  const [dirty, setDirty] = useState(false)

  // Metadata edit state.
  const [meta, setMeta] = useState({
    title: '', slug: '', category: 'governance', audience: 'everyone', summary: '',
  })
  const [metaDirty, setMetaDirty] = useState(false)

  const textareaRefs = useRef<Record<Section, HTMLTextAreaElement | null>>({
    why_this_exists: null, what_this_covers: null, main_content: null, whats_changed: null,
  })

  const reload = useCallback(() => {
    fetch(apiUrl(`/api/admin/world-guide/documents/${id}`), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Load: ${r.status}`)
        return r.json() as Promise<DocumentDetail>
      })
      .then((d) => {
        setDoc(d)
        setMeta({
          title: d.title,
          slug: d.slug,
          category: d.category,
          audience: d.audience,
          summary: d.summary ?? '',
        })
        setMetaDirty(false)
        const src = d.current_draft ?? d.current_published
        setDraftContent({
          why_this_exists:  src?.why_this_exists ?? '',
          what_this_covers: src?.what_this_covers ?? '',
          main_content:     src?.main_content ?? '',
          whats_changed:    src?.whats_changed ?? '',
        })
        setDraftEffective(src?.effective_date ?? '')
        setDirty(false)
      })
      .catch((e: Error) => setError(e.message))
  }, [id])

  useEffect(() => { reload() }, [reload])

  const draft = doc?.current_draft ?? null
  const published = doc?.current_published ?? null
  const archived = !!doc?.archived_at
  const canEditContent = !!draft && !archived

  // ---- API calls -------------------------------------------------------

  async function saveMetadata() {
    setBusy(true); setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/world-guide/documents/${id}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: meta.title.trim(),
          slug: meta.slug.trim(),
          category: meta.category,
          audience: meta.audience,
          summary: meta.summary.trim(),
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        throw new Error(body.detail ? extractErrorMessage(body as ApiError) : `Save: ${res.status}`)
      }
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function saveDraft(silent = false) {
    if (!draft) return
    if (!silent) setBusy(true)
    setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/world-guide/versions/${draft.id}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          effective_date: draftEffective || null,
          why_this_exists:  draftContent.why_this_exists,
          what_this_covers: draftContent.what_this_covers,
          main_content:     draftContent.main_content,
          whats_changed:    draftContent.whats_changed,
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        throw new Error(body.detail ? extractErrorMessage(body as ApiError) : `Save draft: ${res.status}`)
      }
      setDirty(false)
      if (!silent) reload()
    } catch (e) { setError((e as Error).message) } finally { if (!silent) setBusy(false) }
  }

  async function publish() {
    if (!draft) return
    if (!window.confirm(
      'Publish this version? Once published it is frozen in the version history and becomes the live version on the public World Guide.'
    )) return
    setBusy(true); setError(null)
    try {
      await saveDraft(true)
      const res = await fetch(apiUrl(`/api/admin/world-guide/versions/${draft.id}/publish`), {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        throw new Error(body.detail ? extractErrorMessage(body as ApiError) : `Publish: ${res.status}`)
      }
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function newDraft() {
    setBusy(true); setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/world-guide/documents/${id}/versions`), {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ carry_over_content: true }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
        throw new Error(body.detail ? extractErrorMessage(body as ApiError) : `New draft: ${res.status}`)
      }
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  async function archive() {
    if (!window.confirm('Archive this document? It will be hidden from the public World Guide.')) return
    setBusy(true); setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/world-guide/documents/${id}/archive`), {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) throw new Error(`Archive: ${res.status}`)
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  /** Open a private, admin-only preview of this document's current
   *  draft in a new tab. If there are unsaved changes, they are saved
   *  first so the preview always shows what will be published. */
  async function openPreview() {
    if (dirty && draft) {
      await saveDraft(true)
    }
    window.open(`/admin/world-guide/documents/${id}/preview`, '_blank', 'noopener,noreferrer')
  }

  async function duplicate() {
    setBusy(true); setError(null)
    try {
      const res = await fetch(apiUrl(`/api/admin/world-guide/documents/${id}/duplicate`), {
        method: 'POST', credentials: 'include',
      })
      if (!res.ok) throw new Error(`Duplicate: ${res.status}`)
      const dup = await res.json() as { id: string }
      router.push(`/admin/world-guide/documents/${dup.id}`)
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  // ---- Content editing helpers ----------------------------------------

  function updateContent(section: Section, next: string) {
    setDraftContent((c) => ({ ...c, [section]: next }))
    setDirty(true)
  }

  /** Insert text at the current cursor position of the active textarea,
   *  wrapping the current selection between `before` and `after`. */
  function insertMd(before: string, after: string = '', placeholder: string = '') {
    const ta = textareaRefs.current[activeSection]
    if (!ta) return
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const value = draftContent[activeSection]
    const selected = value.substring(start, end) || placeholder
    const newValue = value.substring(0, start) + before + selected + after + value.substring(end)
    updateContent(activeSection, newValue)
    // Restore cursor position after React re-renders.
    requestAnimationFrame(() => {
      const el = textareaRefs.current[activeSection]
      if (!el) return
      el.focus()
      const pos = start + before.length + selected.length
      el.selectionStart = el.selectionEnd = pos
    })
  }

  /** Prepend a marker to the start of the current line (headings, lists). */
  function prependLine(marker: string) {
    const ta = textareaRefs.current[activeSection]
    if (!ta) return
    const value = draftContent[activeSection]
    const pos = ta.selectionStart
    const lineStart = value.lastIndexOf('\n', pos - 1) + 1
    const newValue = value.substring(0, lineStart) + marker + value.substring(lineStart)
    updateContent(activeSection, newValue)
    requestAnimationFrame(() => {
      const el = textareaRefs.current[activeSection]
      if (!el) return
      el.focus()
      el.selectionStart = el.selectionEnd = pos + marker.length
    })
  }

  /** Replace the given range of the current section with `replacement`
   *  and place the cursor at `caretPos` after re-render. */
  function replaceRange(from: number, to: number, replacement: string, caretPos: number) {
    const value = draftContent[activeSection]
    const newValue = value.substring(0, from) + replacement + value.substring(to)
    updateContent(activeSection, newValue)
    requestAnimationFrame(() => {
      const el = textareaRefs.current[activeSection]
      if (!el) return
      el.focus()
      el.selectionStart = el.selectionEnd = caretPos
    })
  }

  /** Indent every line intersecting [start,end] by two spaces. */
  function indentSelection(reverse: boolean) {
    const ta = textareaRefs.current[activeSection]
    if (!ta) return
    const value = draftContent[activeSection]
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const blockStart = value.lastIndexOf('\n', start - 1) + 1
    const blockEnd = end < value.length && value[end] !== '\n'
      ? (value.indexOf('\n', end) === -1 ? value.length : value.indexOf('\n', end))
      : end
    const block = value.substring(blockStart, blockEnd)
    const lines = block.split('\n')
    const changed = lines.map((line) => {
      if (reverse) {
        if (line.startsWith('  ')) return line.substring(2)
        if (line.startsWith('\t')) return line.substring(1)
        return line
      }
      return '  ' + line
    })
    const rewritten = changed.join('\n')
    const delta = rewritten.length - block.length
    const newValue = value.substring(0, blockStart) + rewritten + value.substring(blockEnd)
    updateContent(activeSection, newValue)
    requestAnimationFrame(() => {
      const el = textareaRefs.current[activeSection]
      if (!el) return
      el.focus()
      // If it was a caret-only selection, keep it caret-only at the
      // adjusted offset; otherwise select the whole rewritten block.
      if (start === end) {
        el.selectionStart = el.selectionEnd = Math.max(blockStart, start + (reverse ? -2 : 2))
      } else {
        el.selectionStart = blockStart
        el.selectionEnd = blockEnd + delta
      }
    })
  }

  /** Keydown handler wired to every section textarea. */
  function onEditorKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!canEditContent) return
    const ta = e.currentTarget
    const value = draftContent[activeSection]
    const pos = ta.selectionStart
    const selEnd = ta.selectionEnd
    const meta = e.metaKey || e.ctrlKey

    // Cmd/Ctrl + S — save the draft, suppress browser save dialog.
    if (meta && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 's') {
      e.preventDefault()
      if (dirty) void saveDraft()
      return
    }
    // Cmd/Ctrl + B — bold
    if (meta && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'b') {
      e.preventDefault()
      insertMd('**', '**', 'bold text')
      return
    }
    // Cmd/Ctrl + I — italic
    if (meta && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'i') {
      e.preventDefault()
      insertMd('*', '*', 'italic text')
      return
    }
    // Cmd/Ctrl + K — link
    if (meta && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') {
      e.preventDefault()
      const selected = value.substring(pos, selEnd)
      if (selected) {
        insertMd('[', '](https://)', selected)
      } else {
        insertMd('[', '](https://)', 'link text')
      }
      return
    }
    // Tab / Shift+Tab — indent / outdent
    if (e.key === 'Tab') {
      e.preventDefault()
      indentSelection(e.shiftKey)
      return
    }
    // Enter — auto-continue list-shapes
    if (e.key === 'Enter' && !e.shiftKey && !meta && pos === selEnd) {
      const lineStart = value.lastIndexOf('\n', pos - 1) + 1
      const lineBeforeCursor = value.substring(lineStart, pos)
      const r = continueListOnEnter(lineBeforeCursor)
      if (r.kind === 'continue') {
        e.preventDefault()
        replaceRange(pos, pos, r.insert, pos + r.insert.length)
      } else if (r.kind === 'end') {
        e.preventDefault()
        // Delete the marker on the current line, leaving cursor on a
        // now-empty line ready for a fresh paragraph.
        replaceRange(lineStart, pos, '', lineStart)
      }
      return
    }
  }

  async function uploadImage() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const form = new FormData()
      form.append('file', file)
      try {
        const res = await fetch(apiUrl('/api/admin/world-guide/images'), {
          method: 'POST', credentials: 'include', body: form,
        })
        if (!res.ok) {
          const body = (await res.json().catch(() => ({}))) as Partial<ApiError>
          throw new Error(body.detail ? extractErrorMessage(body as ApiError) : `Upload: ${res.status}`)
        }
        const data = await res.json() as { url: string }
        const url = data.url.startsWith('http') ? data.url : apiUrl(data.url)
        const alt = file.name.replace(/\.[^.]+$/, '')
        if (writingMode === 'write' && writeEditorRef.current) {
          writeEditorRef.current.insertImage(url, alt)
        } else {
          insertMd(`![${alt}](${url})`)
        }
      } catch (e) { setError((e as Error).message) }
    }
    input.click()
  }

  // ---- Markdown import -----------------------------------------------

  function applyImport(parsed: ImportResult, replace: boolean) {
    setDraftContent((c) => {
      const next = { ...c }
      for (const k of ['why_this_exists','what_this_covers','main_content','whats_changed'] as Section[]) {
        const incoming = parsed[k].trim()
        if (!incoming) continue
        if (replace || !c[k].trim()) {
          next[k] = incoming
        } else {
          next[k] = (c[k].trimEnd() + '\n\n' + incoming).trim()
        }
      }
      return next
    })
    setDirty(true)
    setImportOpen(false)
  }

  const previewHtml = draftContent[activeSection]
  const activeMeta = SECTIONS.find(([k]) => k === activeSection)!

  if (!doc) {
    return (
      <div className="p-10 text-[13px]" style={{ color: WG.inkMuted, background: WG.pageBg, minHeight: '100vh' }}>
        Loading…
      </div>
    )
  }

  return (
    <div style={{ background: WG.pageBg, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1440px] px-6 py-6 md:px-10 md:py-8">

        {/* Header */}
        <div className="mb-6">
          <Link href="/admin/world-guide/documents" className="text-[13px]" style={{ color: WG.inkMuted }}>
            ← Documents
          </Link>
          <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h1
                className="font-serif text-[28px] leading-tight md:text-[32px]"
                style={{ color: WG.inkStrong }}
              >
                {doc.title}
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[12.5px]" style={{ color: WG.inkMuted }}>
                <span>/{doc.slug}</span>
                <StatusPill status={archived ? 'archived' : (published ? 'published' : 'draft')} />
                {published && <span>Live: v{published.version_number}</span>}
                {draft && <span>Working: v{draft.version_number}</span>}
                {doc.reading_time_minutes && <span>~{doc.reading_time_minutes} min read</span>}
                {dirty && <span style={{ color: WG.gold }}>Unsaved changes</span>}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {!archived && draft && (
                <>
                  <IconButton onClick={() => setImportOpen(true)} disabled={busy}>
                    Import Markdown
                  </IconButton>
                  <SecondaryButton onClick={() => saveDraft()} disabled={busy || !dirty}>
                    Save draft
                  </SecondaryButton>
                  <PrimaryButton onClick={publish} disabled={busy}>
                    Publish
                  </PrimaryButton>
                </>
              )}
              {!archived && !draft && (
                <PrimaryButton onClick={newDraft} disabled={busy}>
                  Create new draft
                </PrimaryButton>
              )}
              <IconButton onClick={() => setShowPreview((v) => !v)}>
                {showPreview ? 'Editor only' : 'Split view'}
              </IconButton>
              <IconButton onClick={() => { setDetailsOpen((v) => !v); setAiOpen(false) }} active={detailsOpen}>
                Details
              </IconButton>
              <IconButton onClick={() => { setAiOpen((v) => !v); setDetailsOpen(false) }} active={aiOpen}>
                AI
              </IconButton>
              <button
                type="button"
                onClick={openPreview}
                disabled={busy}
                className="rounded-full px-3.5 py-1.5 text-[12.5px] disabled:cursor-not-allowed disabled:opacity-50"
                style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
                title="Open a private preview of this draft in a new tab"
              >
                Preview ↗
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div
            className="mb-4 rounded-xl px-4 py-2.5 text-[13px]"
            style={{ background: 'rgba(214,96,87,0.08)', border: '1px solid rgba(214,96,87,0.24)', color: WG.danger }}
          >
            {error}
          </div>
        )}

        {/* Layout: [main writing area (grows)] · [right drawer if open] */}
        <div className="flex gap-6">
          <div className="min-w-0 flex-1">

            {/* Section tabs + mode switch */}
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div
                className="flex flex-wrap gap-2 rounded-full p-1"
                style={{ background: WG.surfaceBg, border: WG.divider, width: 'fit-content' }}
              >
                {SECTIONS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setActiveSection(key)}
                    className="rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors"
                    style={activeSection === key
                      ? { background: WG.navy, color: '#FFFFFF' }
                      : { background: 'transparent', color: WG.inkMuted }}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div
                className="flex gap-1 rounded-full p-1"
                style={{ background: WG.surfaceBg, border: WG.divider, width: 'fit-content' }}
                role="tablist"
                aria-label="Writing mode"
              >
                {(['write', 'markdown'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={writingMode === mode}
                    onClick={() => setWritingMode(mode)}
                    className="rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors"
                    style={writingMode === mode
                      ? { background: WG.teal, color: '#FFFFFF' }
                      : { background: 'transparent', color: WG.inkMuted }}
                  >
                    {mode === 'write' ? 'Write' : 'Markdown'}
                  </button>
                ))}
              </div>
            </div>

            {/* Section description */}
            <p className="mb-4 text-[13px]" style={{ color: WG.inkMuted }}>
              {activeMeta[2]}
            </p>

            {/* Markdown toolbar — same layout; mode determines what each button does. */}
            {canEditContent && (
              <MarkdownToolbar
                mode={writingMode}
                writeRef={writeEditorRef}
                onInsert={insertMd}
                onPrependLine={prependLine}
                onUploadImage={uploadImage}
              />
            )}

            {/* Editor + preview */}
            <div
              className="grid gap-0 rounded-xl"
              style={{
                gridTemplateColumns: showPreview ? '1fr 1fr' : '1fr',
                border: WG.divider,
                background: WG.cardBg,
                boxShadow: WG.cardShadow,
                overflow: 'hidden',
              }}
            >
              <div style={{ borderRight: showPreview ? WG.divider : 'none' }}>
                {writingMode === 'write' ? (
                  <WriteModeEditor
                    key={activeSection}
                    value={draftContent[activeSection]}
                    onChange={(md) => updateContent(activeSection, md)}
                    disabled={!canEditContent}
                    handleRef={writeEditorRef}
                  />
                ) : (
                  <textarea
                    ref={(el) => { textareaRefs.current[activeSection] = el }}
                    value={draftContent[activeSection]}
                    disabled={!canEditContent}
                    onChange={(e) => updateContent(activeSection, e.target.value)}
                    onKeyDown={onEditorKeyDown}
                    rows={activeSection === 'main_content' ? 32 : 18}
                    spellCheck
                    className="block w-full resize-none px-6 py-6 font-mono text-[14px] leading-[1.65] outline-none"
                    style={{
                      background: WG.cardBg,
                      color: WG.ink,
                      border: 'none',
                    }}
                    placeholder={canEditContent ? 'Write in Markdown…' : 'Create a new draft to edit content.'}
                  />
                )}
              </div>

              {showPreview && (
                <div
                  className="overflow-y-auto px-8 py-6"
                  style={{ background: WG.surfaceBg, maxHeight: '82vh' }}
                >
                  {previewHtml.trim()
                    ? <WorldGuideProse content={previewHtml} size="compact" />
                    : <p className="text-[13px] italic" style={{ color: WG.inkSofter }}>Preview will appear here.</p>
                  }
                </div>
              )}
            </div>

            {/* Footer actions */}
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              {!archived && (
                <>
                  <SecondaryButton onClick={duplicate} disabled={busy}>Duplicate</SecondaryButton>
                  <SecondaryButton onClick={archive} disabled={busy}>Archive</SecondaryButton>
                </>
              )}
              {archived && (
                <div
                  className="rounded-full px-3.5 py-1 text-[12px] font-semibold uppercase tracking-wide"
                  style={{ background: 'rgba(214,96,87,0.08)', color: WG.danger, border: '1px solid rgba(214,96,87,0.24)' }}
                >
                  Archived
                </div>
              )}
            </div>

            {/* Version history */}
            <VersionHistoryCard versions={doc.versions} />
          </div>

          {/* Right — Details / AI drawers */}
          {(detailsOpen || aiOpen) && (
            <aside className="w-[340px] shrink-0">
              {detailsOpen && (
                <DetailsDrawer
                  doc={doc}
                  meta={meta}
                  setMeta={(m) => { setMeta(m); setMetaDirty(true) }}
                  metaDirty={metaDirty}
                  onSaveMetadata={saveMetadata}
                  effective={draftEffective}
                  setEffective={(v) => { setDraftEffective(v); setDirty(true) }}
                  canEditContent={canEditContent}
                  archived={archived}
                  onClose={() => setDetailsOpen(false)}
                  busy={busy}
                />
              )}
              {aiOpen && <AIDrawer onClose={() => setAiOpen(false)} />}
            </aside>
          )}
        </div>
      </div>

      {importOpen && (
        <ImportMarkdownModal
          onClose={() => setImportOpen(false)}
          onApply={applyImport}
          existing={draftContent}
        />
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------


function MarkdownToolbar({
  mode, writeRef, onInsert, onPrependLine, onUploadImage,
}: {
  mode: 'write' | 'markdown'
  writeRef: React.RefObject<WriteModeHandle | null>
  onInsert: (before: string, after?: string, placeholder?: string) => void
  onPrependLine: (marker: string) => void
  onUploadImage: () => void
}) {
  const write = writeRef.current
  const H = (level: 1 | 2 | 3, marker: string) => mode === 'write'
    ? () => write?.setHeading(level)
    : () => onPrependLine(marker)
  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-1 rounded-lg px-2 py-1.5"
      style={{ background: WG.surfaceBg, border: WG.divider }}
    >
      <Tool onClick={H(1, '# ')} title="Heading 1">H1</Tool>
      <Tool onClick={H(2, '## ')} title="Heading 2">H2</Tool>
      <Tool onClick={H(3, '### ')} title="Heading 3">H3</Tool>
      <Divider />
      <Tool
        onClick={mode === 'write'
          ? () => write?.toggleBold()
          : () => onInsert('**', '**', 'bold text')}
        title="Bold"
      ><strong>B</strong></Tool>
      <Tool
        onClick={mode === 'write'
          ? () => write?.toggleItalic()
          : () => onInsert('*', '*', 'italic text')}
        title="Italic"
      ><em>I</em></Tool>
      <Tool
        onClick={mode === 'write'
          ? () => write?.toggleInlineCode()
          : () => onInsert('`', '`', 'code')}
        title="Inline code"
      >{'</>'}</Tool>
      <Divider />
      <Tool
        onClick={mode === 'write' ? () => write?.toggleBlockquote() : () => onPrependLine('> ')}
        title="Quote"
      >&ldquo; &rdquo;</Tool>
      <Tool
        onClick={mode === 'write' ? () => write?.toggleBullet() : () => onPrependLine('- ')}
        title="Bullet list"
      >• List</Tool>
      <Tool
        onClick={mode === 'write' ? () => write?.toggleOrdered() : () => onPrependLine('1. ')}
        title="Numbered list"
      >1. List</Tool>
      <Tool
        onClick={mode === 'write' ? () => write?.toggleTaskList() : () => onPrependLine('- [ ] ')}
        title="Checklist"
      >☐ List</Tool>
      <Divider />
      <Tool
        onClick={mode === 'write'
          ? () => write?.insertTable()
          : () => onInsert('\n\n| Column | Column |\n| --- | --- |\n| Value | Value |\n\n')}
        title="Table"
      >
        Table
      </Tool>
      <Tool
        onClick={mode === 'write'
          ? () => {
              const url = window.prompt('Link URL', 'https://')
              if (url) write?.insertLink(url, 'link text')
            }
          : () => onInsert('[', '](https://)', 'link text')}
        title="Link"
      >
        Link
      </Tool>
      <Tool onClick={onUploadImage} title="Insert image">Image</Tool>
      <Tool
        onClick={mode === 'write'
          ? () => write?.insertHorizontalRule()
          : () => onInsert('\n\n---\n\n')}
        title="Divider"
      >— HR</Tool>
      <Tool
        onClick={mode === 'write'
          ? () => write?.insertCallout('note')
          : () => onInsert('> [!note] Title\n> ', '', 'Body of the callout')}
        title="Callout"
      >
        Callout
      </Tool>
      <Tool
        onClick={mode === 'write'
          ? () => write?.insertCodeBlock()
          : () => onInsert('\n```\n', '\n```\n', 'code block')}
        title="Code block"
      >
        Code
      </Tool>
    </div>
  )
}

function Tool({ onClick, title, children }: {
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="rounded-md px-2.5 py-1 text-[12.5px] font-medium transition-colors hover:bg-white"
      style={{ color: WG.inkStrong, background: 'transparent' }}
    >
      {children}
    </button>
  )
}

function Divider() {
  return <span className="mx-1 h-4 w-px" style={{ background: 'rgba(15,23,42,0.12)' }} />
}


// ---------------------------------------------------------------------------
// Details drawer (metadata)
// ---------------------------------------------------------------------------


function DetailsDrawer({
  doc, meta, setMeta, metaDirty, onSaveMetadata,
  effective, setEffective, canEditContent, archived,
  onClose, busy,
}: {
  doc: DocumentDetail
  meta: { title: string; slug: string; category: string; audience: string; summary: string }
  setMeta: (m: typeof meta) => void
  metaDirty: boolean
  onSaveMetadata: () => void
  effective: string
  setEffective: (v: string) => void
  canEditContent: boolean
  archived: boolean
  onClose: () => void
  busy: boolean
}) {
  return (
    <div
      className="sticky top-4 rounded-xl p-5"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-serif text-[16px]" style={{ color: WG.inkStrong }}>Details</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-[15px]"
          style={{ color: WG.inkSofter }}
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <MetaField label="Title">
        <input
          type="text"
          value={meta.title}
          disabled={archived}
          onChange={(e) => setMeta({ ...meta, title: e.target.value })}
          className="w-full rounded-md px-2.5 py-1.5 text-[13px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        />
      </MetaField>
      <MetaField label="Slug">
        <input
          type="text"
          value={meta.slug}
          disabled={archived}
          onChange={(e) => setMeta({ ...meta, slug: e.target.value })}
          className="w-full rounded-md px-2.5 py-1.5 font-mono text-[12.5px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        />
      </MetaField>
      <MetaField label="Category">
        <select
          value={meta.category}
          disabled={archived}
          onChange={(e) => setMeta({ ...meta, category: e.target.value })}
          className="w-full cursor-pointer rounded-md px-2.5 py-1.5 text-[13px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        >
          {Object.entries(CATEGORY_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </MetaField>
      <MetaField label="Audience">
        <select
          value={meta.audience}
          disabled={archived}
          onChange={(e) => setMeta({ ...meta, audience: e.target.value })}
          className="w-full cursor-pointer rounded-md px-2.5 py-1.5 text-[13px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        >
          {Object.entries(AUDIENCE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </MetaField>
      <MetaField label="Summary">
        <textarea
          value={meta.summary}
          disabled={archived}
          onChange={(e) => setMeta({ ...meta, summary: e.target.value })}
          rows={3}
          className="w-full resize-none rounded-md px-2.5 py-1.5 text-[13px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        />
      </MetaField>
      <MetaField label="Effective date">
        <input
          type="date"
          value={effective}
          disabled={!canEditContent}
          onChange={(e) => setEffective(e.target.value)}
          className="w-full rounded-md px-2.5 py-1.5 text-[13px]"
          style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
        />
      </MetaField>

      {metaDirty && !archived && (
        <div className="mt-3 flex justify-end">
          <PrimaryButton onClick={onSaveMetadata} disabled={busy}>
            Save details
          </PrimaryButton>
        </div>
      )}

      <div
        className="mt-5 space-y-1 border-t pt-3 text-[11.5px]"
        style={{ borderColor: 'rgba(15,23,42,0.08)', color: WG.inkSofter }}
      >
        <div>Version: {doc.current_published?.version_number ?? doc.current_draft?.version_number ?? '—'}</div>
        <div>Status: {doc.archived_at ? 'Archived' : (doc.current_version_id ? 'Published' : 'Draft')}</div>
        <div>Author: {doc.author_name ?? '—'}</div>
        {doc.reading_time_minutes && <div>Reading time: ~{doc.reading_time_minutes} min</div>}
      </div>
    </div>
  )
}


function MetaField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="mb-3 block">
      <span
        className="mb-1 block text-[10.5px] font-semibold uppercase tracking-wide"
        style={{ color: WG.inkSofter }}
      >
        {label}
      </span>
      {children}
    </label>
  )
}


// ---------------------------------------------------------------------------
// AI drawer — placeholder that reserves architectural room
// ---------------------------------------------------------------------------


const AI_ACTIONS = [
  'Rewrite in plain English',
  'Make more formal',
  'Shorten',
  'Expand',
  'Check consistency with another policy',
  'Suggest missing sections',
  'Improve readability',
  'Suggest cross-links',
  'Explain legal language',
]

function AIDrawer({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="sticky top-4 rounded-xl p-5"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-serif text-[16px]" style={{ color: WG.inkStrong }}>AI assistant</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-[15px]"
          style={{ color: WG.inkSofter }}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div
        className="mb-4 rounded-lg px-3 py-2 text-[12px] font-medium"
        style={{ background: WG.tealSoft, color: WG.teal, border: `1px solid ${WG.teal}22` }}
      >
        Coming soon
      </div>
      <p className="mb-3 text-[12.5px]" style={{ color: WG.inkMuted }}>
        These actions will help you shape a document while writing.
        Nothing is implemented yet — the architecture is here so we can
        add each one without redesigning the editor.
      </p>
      <ul className="space-y-1.5">
        {AI_ACTIONS.map((a) => (
          <li
            key={a}
            className="rounded-md px-3 py-1.5 text-[12.5px]"
            style={{ background: WG.surfaceBg, border: WG.hairline, color: WG.inkMuted }}
          >
            {a}
          </li>
        ))}
      </ul>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Import modal
// ---------------------------------------------------------------------------


function ImportMarkdownModal({
  onClose, onApply, existing,
}: {
  onClose: () => void
  onApply: (parsed: ImportResult, replace: boolean) => void
  existing: Record<Section, string>
}) {
  const [raw, setRaw] = useState('')
  const parsed = useMemo(() => parseImportedMarkdown(raw), [raw])
  const overwriteWarn = (['why_this_exists','what_this_covers','main_content','whats_changed'] as Section[])
    .some((k) => existing[k].trim().length > 0 && parsed[k].trim().length > 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 py-10"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-[900px] rounded-xl bg-white shadow-xl"
        style={{ border: WG.divider }}
      >
        <div className="flex items-start justify-between border-b px-6 py-4" style={{ borderColor: 'rgba(15,23,42,0.08)' }}>
          <div>
            <h2 className="font-serif text-[20px]" style={{ color: WG.inkStrong }}>
              Import Markdown
            </h2>
            <p className="mt-1 text-[13px]" style={{ color: WG.inkMuted }}>
              Paste a Markdown document. Sections named &ldquo;Why this exists&rdquo;,
              &ldquo;What this covers&rdquo;, &ldquo;Main content&rdquo; and &ldquo;What&rsquo;s changed&rdquo;
              are matched automatically. Everything else lands in Main content.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-[16px]" style={{ color: WG.inkSofter }} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="grid gap-0 md:grid-cols-2" style={{ minHeight: '360px' }}>
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            rows={18}
            spellCheck={false}
            placeholder="# Why this exists&#10;…&#10;&#10;# What this covers&#10;…&#10;&#10;# Main content&#10;…"
            className="block w-full resize-none px-4 py-4 font-mono text-[13.5px] leading-[1.65] outline-none"
            style={{ background: WG.cardBg, color: WG.ink, borderRight: WG.divider }}
          />
          <div className="overflow-y-auto px-5 py-4" style={{ background: WG.surfaceBg, maxHeight: '60vh' }}>
            <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: WG.inkSofter }}>
              Section mapping
            </h4>
            <ul className="space-y-2 text-[12.5px]">
              {(['why_this_exists','what_this_covers','main_content','whats_changed'] as Section[]).map((k) => {
                const label = SECTIONS.find(([kk]) => kk === k)![1]
                const hasContent = parsed[k].trim().length > 0
                const matchedTitle = parsed.matched[k]
                return (
                  <li
                    key={k}
                    className="rounded-md px-3 py-2"
                    style={{ background: WG.cardBg, border: WG.hairline }}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-medium" style={{ color: WG.inkStrong }}>{label}</span>
                      <span className="text-[11px]" style={{ color: hasContent ? WG.teal : WG.inkSofter }}>
                        {hasContent ? `${parsed[k].split(/\s+/).length} words` : 'empty'}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[11.5px]" style={{ color: WG.inkMuted }}>
                      {matchedTitle
                        ? `Matched heading: ${matchedTitle}`
                        : k === 'main_content'
                          ? 'Default target for unmatched content'
                          : 'No matching heading found'}
                    </div>
                  </li>
                )
              })}
            </ul>
            {parsed.fallback_all_to_main && raw.trim() && (
              <p className="mt-3 text-[12px]" style={{ color: WG.gold }}>
                No section headings recognised — everything will go into Main content.
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-6 py-4" style={{ borderColor: 'rgba(15,23,42,0.08)' }}>
          <p className="text-[12px]" style={{ color: overwriteWarn ? WG.gold : WG.inkSofter }}>
            {overwriteWarn
              ? 'Some sections already have content. You can either replace or append.'
              : 'Existing sections are empty; the import will fill them.'}
          </p>
          <div className="flex gap-2">
            <SecondaryButton onClick={onClose}>Cancel</SecondaryButton>
            {overwriteWarn && (
              <SecondaryButton
                onClick={() => onApply(parsed, false)}
                disabled={!raw.trim()}
              >
                Append
              </SecondaryButton>
            )}
            <PrimaryButton
              onClick={() => onApply(parsed, true)}
              disabled={!raw.trim()}
            >
              {overwriteWarn ? 'Replace' : 'Import'}
            </PrimaryButton>
          </div>
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Buttons + pills
// ---------------------------------------------------------------------------


function PrimaryButton({ onClick, disabled, children }: {
  onClick: () => void; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      style={{ background: WG.navy }}
    >
      {children}
    </button>
  )
}
function SecondaryButton({ onClick, disabled, children }: {
  onClick: () => void; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-4 py-1.5 text-[12.5px] font-semibold transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
    >
      {children}
    </button>
  )
}
function IconButton({ onClick, disabled, active, children }: {
  onClick: () => void; disabled?: boolean; active?: boolean; children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-3.5 py-1.5 text-[12.5px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      style={active
        ? { background: WG.tealSoft, color: WG.teal, border: `1px solid ${WG.teal}22` }
        : { background: '#FFFFFF', border: WG.divider, color: WG.ink }}
    >
      {children}
    </button>
  )
}


function StatusPill({ status }: { status: 'draft' | 'published' | 'archived' }) {
  const style: Record<typeof status, React.CSSProperties> = {
    draft:     { background: WG.navySoft, color: WG.inkMuted, border: WG.hairline },
    published: { background: WG.tealSoft, color: WG.teal, border: `1px solid ${WG.teal}22` },
    archived:  { background: 'rgba(214,96,87,0.08)', color: WG.danger, border: '1px solid rgba(214,96,87,0.20)' },
  }
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide"
      style={style[status]}
    >
      {status[0].toUpperCase() + status.slice(1)}
    </span>
  )
}


function VersionHistoryCard({ versions }: { versions: VersionSummary[] }) {
  if (versions.length === 0) return null
  return (
    <div
      className="mt-8 rounded-xl p-5"
      style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
    >
      <h3 className="mb-3 font-serif text-[16px]" style={{ color: WG.inkStrong }}>
        Version history
      </h3>
      <ul className="divide-y" style={{ borderColor: 'rgba(15,23,42,0.06)' }}>
        {versions.map((v) => (
          <li key={v.id} className="flex items-center justify-between gap-3 py-2 text-[13px]">
            <div className="min-w-0">
              <span className="font-medium" style={{ color: WG.inkStrong }}>v{v.version_number}</span>
              <span className="ml-2 text-[11.5px]" style={{ color: WG.inkSofter }}>
                {v.status === 'published' && v.published_at
                  ? `Published ${fmtDate(v.published_at)}${v.published_by_name ? ` · ${v.published_by_name}` : ''}`
                  : v.status === 'archived'
                    ? 'Superseded'
                    : `Draft · updated ${fmtDate(v.updated_at)}`}
              </span>
            </div>
            <StatusPill status={v.status} />
          </li>
        ))}
      </ul>
    </div>
  )
}


function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}
