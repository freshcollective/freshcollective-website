'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import LinkExt from '@tiptap/extension-link'
import Placeholder from '@tiptap/extension-placeholder'
import { apiUrl } from '@/lib/api'
import type {
  CreatorOfferPage,
  CreatorPathway,
  OfferCreatorSection,
  OfferFaqItem,
  OfferFaqsSection,
  OfferInvitationSection,
  OfferPageStatus,
  OfferPracticalSection,
  OfferSectionsConfig,
  OfferWhatsIncludedSection,
} from '@/types/platform'
import {
  Button,
  FormField,
  Input,
  Switch,
  TextArea,
  useToast,
} from '@/components/platform'
import ImagePickerField from '@/components/creator/ImagePickerField'

/**
 * Offer Page Editor.
 *
 * One long calm form. Sections in a fixed order (Basics → Invitation
 * → What's Included → Practical → FAQs → Creator); each section has
 * its own enable-toggle so a creator can turn off anything they don't
 * want to fill in without losing the content.
 *
 * Autosave persists content changes ~750ms after the last edit. The
 * only actions that change ``status`` are explicit: Publish, Unpublish,
 * Archive. Autosave never touches status, so nobody accidentally
 * publishes by typing.
 *
 * Slug lock: once the offer has ever been published (``slug_locked``
 * true on the payload), the slug field switches to a read-only
 * affordance and the backend rejects any change. Language mirrors the
 * backend error copy so a creator sees the same story in both places.
 */

interface Props {
  spaceSlug: string
  initialOffer: CreatorOfferPage
  pathways: CreatorPathway[]
}

// ---------------------------------------------------------------------------
// Normalise the raw sections dict → strongly-typed shape for the form.
// The backend returns whatever was written, so we defensively build a
// full shape at the boundary — this keeps every section render safe
// even against older rows or partially-typed blobs.
// ---------------------------------------------------------------------------

function normaliseSections(raw: unknown): OfferSectionsConfig {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>

  const invitation = (src.invitation ?? {}) as Partial<OfferInvitationSection>
  const whatsIncluded = (src.whats_included ?? {}) as Partial<OfferWhatsIncludedSection>
  const practical = (src.practical ?? {}) as Partial<OfferPracticalSection>
  const faqs = (src.faqs ?? {}) as Partial<OfferFaqsSection>
  const creator = (src.creator ?? {}) as Partial<OfferCreatorSection>

  return {
    invitation: {
      enabled: !!invitation.enabled,
      body: typeof invitation.body === 'string' ? invitation.body : null,
    },
    whats_included: {
      enabled: !!whatsIncluded.enabled,
      items: Array.isArray(whatsIncluded.items)
        ? whatsIncluded.items.filter((s): s is string => typeof s === 'string')
        : [],
    },
    practical: {
      enabled: !!practical.enabled,
      dates: (practical.dates as string | null | undefined) ?? null,
      duration: (practical.duration as string | null | undefined) ?? null,
      location: (practical.location as string | null | undefined) ?? null,
      format: (practical.format as string | null | undefined) ?? null,
      access_period: (practical.access_period as string | null | undefined) ?? null,
      capacity: (practical.capacity as string | null | undefined) ?? null,
      requirements: (practical.requirements as string | null | undefined) ?? null,
    },
    faqs: {
      enabled: !!faqs.enabled,
      items: Array.isArray(faqs.items)
        ? (faqs.items as Partial<OfferFaqItem>[])
            .map((it) => ({
              question: typeof it?.question === 'string' ? it.question : '',
              answer: typeof it?.answer === 'string' ? it.answer : '',
            }))
        : [],
    },
    creator: {
      enabled: !!creator.enabled,
    },
  }
}

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

export default function OfferPageEditor({ spaceSlug, initialOffer, pathways }: Props) {
  const router = useRouter()
  const { show } = useToast()

  const [offer, setOffer] = useState<CreatorOfferPage>(initialOffer)
  const [title, setTitle] = useState(initialOffer.title)
  const [promise, setPromise] = useState(initialOffer.promise ?? '')
  const [heroImageUrl, setHeroImageUrl] = useState<string | null>(initialOffer.hero_image_url)
  const [sections, setSections] = useState<OfferSectionsConfig>(
    () => normaliseSections(initialOffer.sections_config),
  )

  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [statusBusy, setStatusBusy] = useState(false)

  // Track whether autosave is allowed to run. The initial render sets
  // state from props; without this gate the setState calls in the
  // section forms would immediately fire an autosave for no change.
  const dirtyRef = useRef(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const baseUrl = apiUrl(
    `/api/creator/spaces/${spaceSlug}/offers/${offer.slug}`,
  )

  async function save(patch: Record<string, unknown>) {
    try {
      const res = await fetch(baseUrl, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setSaveState('error')
        show(
          typeof body.detail === 'string' ? body.detail : 'Could not save changes.',
          { tone: 'error' },
        )
        return null
      }
      const updated: CreatorOfferPage = await res.json()
      setOffer(updated)
      setSaveState('saved')
      return updated
    } catch {
      setSaveState('error')
      show('Network error while saving.', { tone: 'error' })
      return null
    }
  }

  // ── Autosave content-only fields ──────────────────────────────────────
  useEffect(() => {
    if (!dirtyRef.current) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    setSaveState('saving')
    debounceRef.current = setTimeout(() => {
      void save({
        title,
        promise: promise.trim() ? promise.trim() : '',
        hero_image_url: heroImageUrl ?? '',
        sections_config: sections,
      })
    }, 750)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, promise, heroImageUrl, sections])

  // Any state change from a child section flips the dirty flag so the
  // autosave effect can fire. Wrap the setters used by section forms.
  function markDirty<T>(setter: (v: T) => void) {
    return (v: T) => {
      dirtyRef.current = true
      setter(v)
    }
  }

  // ── Explicit publish / unpublish / archive ───────────────────────────
  async function changeStatus(next: OfferPageStatus, confirmMsg?: string) {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setStatusBusy(true)
    try {
      // Flush any pending autosave first so the publish snapshot
      // reflects the latest typed content, not a stale save.
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
      const flushed = await save({
        title,
        promise: promise.trim() ? promise.trim() : '',
        hero_image_url: heroImageUrl ?? '',
        sections_config: sections,
        status: next,
      })
      if (flushed) {
        dirtyRef.current = false
        show(
          next === 'published'
            ? 'Offer Page published.'
            : next === 'archived'
              ? 'Offer Page archived.'
              : 'Offer Page unpublished.',
          { tone: 'success' },
        )
        router.refresh()
      }
    } finally {
      setStatusBusy(false)
    }
  }

  const publicUrl = `/spaces/${spaceSlug}/offers/${offer.slug}`
  const targetPathway = pathways.find((p) => p.id === offer.target_id) ?? null

  return (
    <div className="pb-32">

      {/* ── Sticky publish bar ── */}
      <PublishBar
        status={offer.status}
        publishedAt={offer.published_at}
        saveState={saveState}
        busy={statusBusy}
        publicUrl={publicUrl}
        onPublish={() =>
          changeStatus(
            'published',
            offer.published_at
              ? undefined
              : 'Publish this Offer Page? Its slug will be permanently locked so shared links stay stable.',
          )
        }
        onUnpublish={() => changeStatus('draft')}
        onArchive={() => changeStatus(
          'archived',
          'Archive this Offer Page? It will no longer appear as an active offer.',
        )}
      />

      {/* ── Basics ── */}
      <Section title="Basics" description="Title, URL, hero image and one-line promise.">
        <div className="space-y-5">
          <FormField label="Offer Page title">
            <Input
              value={title}
              onChange={(e) => markDirty(setTitle)(e.target.value)}
              placeholder="e.g. Join the winter cohort"
              maxLength={200}
            />
          </FormField>

          <SlugField
            slug={offer.slug}
            locked={offer.slug_locked}
            spaceSlug={spaceSlug}
            baseUrl={baseUrl}
            onSlugChanged={(next, newBaseUrl) => {
              setOffer((prev) => ({ ...prev, slug: next }))
              // baseUrl is re-derived from offer.slug on next render;
              // caller doesn't need it beyond side-effect signalling.
              void newBaseUrl
            }}
            onError={(msg) => show(msg, { tone: 'error' })}
          />

          <FormField
            label="One-line promise"
            helper="Optional. Appears near the hero as a short subtitle. Keep it warm and specific."
          >
            <Input
              value={promise}
              onChange={(e) => markDirty(setPromise)(e.target.value)}
              placeholder="e.g. Six weeks to build a daily grounding practice."
              maxLength={200}
            />
          </FormField>

          <FormField label="Hero image" helper="Optional. Wide 16:9 works best.">
            <ImagePickerField
              spaceSlug={spaceSlug}
              value={heroImageUrl}
              onChange={markDirty(setHeroImageUrl)}
            />
          </FormField>

          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Pathway
            </p>
            <p className="text-[14px] text-navy-900">
              {targetPathway?.title ?? '(target no longer available)'}
            </p>
            <p className="mt-1 text-[12.5px] text-slate-500">
              The pathway this Offer Page invites people into. The CTA on
              the public page uses this pathway&rsquo;s existing checkout.
            </p>
          </div>
        </div>
      </Section>

      {/* ── Invitation ── */}
      <SectionWithToggle
        title="Invitation"
        description="Welcome people into the experience and help them understand what it's for."
        enabled={sections.invitation.enabled}
        onToggle={(enabled) =>
          markDirty(setSections)({
            ...sections,
            invitation: { ...sections.invitation, enabled },
          })
        }
      >
        <RestrainedRichTextEditor
          value={sections.invitation.body ?? ''}
          onChange={(body) =>
            markDirty(setSections)({
              ...sections,
              invitation: { ...sections.invitation, body },
            })
          }
          placeholder="Speak directly. Say who this is for and what shifts. Two or three short paragraphs is plenty."
        />
      </SectionWithToggle>

      {/* ── What's Included ── */}
      <SectionWithToggle
        title="What's included"
        description="Show clearly what someone receives when they join."
        enabled={sections.whats_included.enabled}
        onToggle={(enabled) =>
          markDirty(setSections)({
            ...sections,
            whats_included: { ...sections.whats_included, enabled },
          })
        }
      >
        <WhatsIncludedEditor
          items={sections.whats_included.items}
          onChange={(items) =>
            markDirty(setSections)({
              ...sections,
              whats_included: { ...sections.whats_included, items },
            })
          }
        />
      </SectionWithToggle>

      {/* ── Practical Details ── */}
      <SectionWithToggle
        title="Practical details"
        description="Share the useful details — when, where, how long and what to expect."
        enabled={sections.practical.enabled}
        onToggle={(enabled) =>
          markDirty(setSections)({
            ...sections,
            practical: { ...sections.practical, enabled },
          })
        }
      >
        <PracticalEditor
          value={sections.practical}
          onChange={(next) =>
            markDirty(setSections)({
              ...sections,
              practical: next,
            })
          }
        />
      </SectionWithToggle>

      {/* ── FAQs ── */}
      <SectionWithToggle
        title="FAQs"
        description="Answer the questions people are most likely to have before joining."
        enabled={sections.faqs.enabled}
        onToggle={(enabled) =>
          markDirty(setSections)({
            ...sections,
            faqs: { ...sections.faqs, enabled },
          })
        }
      >
        <FaqsEditor
          items={sections.faqs.items}
          onChange={(items) =>
            markDirty(setSections)({
              ...sections,
              faqs: { ...sections.faqs, items },
            })
          }
        />
      </SectionWithToggle>

      {/* ── Creator ── */}
      <SectionWithToggle
        title="About the creator"
        description="Introduce yourself using the profile from your Collective."
        enabled={sections.creator.enabled}
        onToggle={(enabled) =>
          markDirty(setSections)({
            ...sections,
            creator: { ...sections.creator, enabled },
          })
        }
      />

    </div>
  )
}

// ---------------------------------------------------------------------------
// Sticky publish bar
// ---------------------------------------------------------------------------

function PublishBar({
  status, publishedAt, saveState, busy, publicUrl,
  onPublish, onUnpublish, onArchive,
}: {
  status: OfferPageStatus
  publishedAt: string | null
  saveState: 'idle' | 'saving' | 'saved' | 'error'
  busy: boolean
  publicUrl: string
  onPublish: () => void
  onUnpublish: () => void
  onArchive: () => void
}) {
  const statusLabel =
    status === 'published' ? 'Published' :
    status === 'archived'  ? 'Archived'  : 'Draft'
  const statusStyle: React.CSSProperties =
    status === 'published' ? { background: 'rgba(56,160,158,0.10)', color: '#0f766e' } :
    status === 'archived'  ? { background: 'rgba(12,24,38,0.06)', color: 'rgba(12,24,38,0.55)' } :
                             { background: 'rgba(214,177,63,0.14)', color: '#8a6a1f' }

  const saveLabel =
    saveState === 'saving' ? 'Saving…' :
    saveState === 'saved'  ? 'Saved'   :
    saveState === 'error'  ? 'Save failed — will retry on next change' :
                             ''

  return (
    <div className="sticky top-0 z-10 -mx-8 mb-6 border-b border-slate-100 bg-white/95 px-8 py-3 backdrop-blur md:-mx-10 md:px-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold uppercase tracking-wider"
            style={statusStyle}
          >
            {statusLabel}
          </span>
          {publishedAt && (
            <span className="text-[11.5px] text-slate-500">
              First published {new Date(publishedAt).toLocaleDateString('en-AU', {
                day: 'numeric', month: 'short', year: 'numeric',
              })}
            </span>
          )}
          {saveLabel && (
            <span
              className={`text-[11.5px] ${
                saveState === 'error' ? 'text-red-600' : 'text-slate-500'
              }`}
            >
              · {saveLabel}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <a
            href={publicUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-[13px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
          >
            Preview →
          </a>
          {status !== 'published' && status !== 'archived' && (
            <Button variant="primary" onClick={onPublish} disabled={busy}>
              {busy ? 'Working…' : 'Publish'}
            </Button>
          )}
          {status === 'published' && (
            <>
              <Button variant="tertiary" onClick={onUnpublish} disabled={busy}>
                Unpublish
              </Button>
              <Button variant="tertiary" onClick={onArchive} disabled={busy}>
                Archive
              </Button>
            </>
          )}
          {status === 'archived' && (
            <Button variant="primary" onClick={onPublish} disabled={busy}>
              Republish
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section shells
// ---------------------------------------------------------------------------

function Section({
  title, description, children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8">
      <header className="mb-5">
        <h2 className="font-serif text-[18px] text-navy-900">{title}</h2>
        {description && (
          <p className="mt-1 text-[13.5px] leading-relaxed text-slate-600">
            {description}
          </p>
        )}
      </header>
      {children}
    </section>
  )
}

function SectionWithToggle({
  title, description, enabled, onToggle, children,
}: {
  title: string
  description?: string
  enabled: boolean
  onToggle: (v: boolean) => void
  children?: React.ReactNode
}) {
  return (
    <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-6 md:p-8">
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-serif text-[18px] text-navy-900">{title}</h2>
          {description && (
            <p className="mt-1 max-w-2xl text-[13.5px] leading-relaxed text-slate-600">
              {description}
            </p>
          )}
        </div>
        <Switch
          checked={enabled}
          onChange={(e) => onToggle(e.target.checked)}
          label="Show on page"
        />
      </header>
      {enabled && children ? <div className="mt-2">{children}</div> : null}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Slug field
// ---------------------------------------------------------------------------

function SlugField({
  slug, locked, spaceSlug, baseUrl, onSlugChanged, onError,
}: {
  slug: string
  locked: boolean
  spaceSlug: string
  baseUrl: string
  onSlugChanged: (next: string, newBaseUrl: string) => void
  onError: (msg: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(slug)
  const [busy, setBusy] = useState(false)

  async function commit() {
    const next = draft.trim().toLowerCase()
    if (!next || next === slug) {
      setEditing(false)
      setDraft(slug)
      return
    }
    setBusy(true)
    try {
      const res = await fetch(baseUrl, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug: next }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        onError(typeof body.detail === 'string' ? body.detail : 'Could not update the URL.')
        setDraft(slug)
      } else {
        const updated = await res.json()
        onSlugChanged(
          updated.slug,
          apiUrl(`/api/creator/spaces/${spaceSlug}/offers/${updated.slug}`),
        )
        setEditing(false)
      }
    } finally {
      setBusy(false)
    }
  }

  if (locked) {
    return (
      <FormField
        label="URL"
        helper={
          'Locked — Offer Pages have their slug set permanently once first '
          + 'published, so previously shared links stay stable.'
        }
      >
        <div className="flex items-center gap-2">
          <div
            className="flex-1 truncate rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13.5px] text-slate-700"
          >
            /spaces/{spaceSlug}/offers/<span className="font-medium text-navy-900">{slug}</span>
          </div>
          <span
            aria-hidden="true"
            className="rounded-full bg-slate-100 px-2 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500"
          >
            🔒 Locked
          </span>
        </div>
      </FormField>
    )
  }

  return (
    <FormField
      label="URL"
      helper="Only lowercase letters, numbers and hyphens. Locks permanently once you publish."
    >
      {editing ? (
        <div className="flex items-center gap-2">
          <div className="flex flex-1 items-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13.5px]">
            <span className="shrink-0 text-slate-500">/spaces/{spaceSlug}/offers/</span>
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="flex-1 bg-transparent text-navy-900 outline-none"
              maxLength={120}
              disabled={busy}
            />
          </div>
          <Button variant="primary" onClick={() => void commit()} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </Button>
          <Button
            variant="tertiary"
            onClick={() => { setDraft(slug); setEditing(false) }}
            disabled={busy}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <div className="flex-1 truncate rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[13.5px] text-slate-700">
            /spaces/{spaceSlug}/offers/<span className="font-medium text-navy-900">{slug}</span>
          </div>
          <Button variant="tertiary" onClick={() => setEditing(true)}>
            Edit
          </Button>
        </div>
      )}
    </FormField>
  )
}

// ---------------------------------------------------------------------------
// Restrained TipTap — paragraphs, one heading level, bold, italic,
// bullet + ordered list, links. Deliberately smaller than
// ``SimpleRichTextEditor`` (which offers H1/H2/H3) so Offer Pages
// stay consistent in shape.
// ---------------------------------------------------------------------------

function RestrainedRichTextEditor({
  value, onChange, placeholder,
}: {
  value: string
  onChange: (json: string) => void
  placeholder?: string
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
        // We only allow one heading level.
        heading: { levels: [2] },
      }),
      LinkExt.configure({
        openOnClick: false,
        HTMLAttributes: { rel: 'noopener noreferrer', target: '_blank' },
      }),
      Placeholder.configure({ placeholder: placeholder ?? 'Add some text…' }),
    ],
    // Immediate rendering causes an SSR hydration mismatch warning in
    // Next 15's App Router. Deferring until mount keeps the DOM stable.
    immediatelyRender: false,
    content: parseTipTapContent(value),
    onUpdate({ editor }) {
      onChange(JSON.stringify(editor.getJSON()))
    },
    editorProps: {
      attributes: { class: 'focus:outline-none min-h-[140px]' },
    },
  })

  if (!editor) return null

  function addLink() {
    const url = window.prompt('Enter URL (include https://):')
    if (!url) return
    const safe = /^https?:\/\//.test(url) ? url : `https://${url}`
    editor?.chain().focus().extendMarkRange('link').setLink({ href: safe }).run()
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white focus-within:border-teal-400 focus-within:ring-2 focus-within:ring-teal-100">
      <div className="flex flex-wrap items-center gap-0.5 rounded-t-xl border-b border-slate-100 bg-slate-50 px-2 py-1.5">
        <ToolbarBtn
          onClick={() => editor.chain().focus().setParagraph().run()}
          active={editor.isActive('paragraph')}
          title="Paragraph"
        >
          ¶
        </ToolbarBtn>
        <ToolbarBtn
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          active={editor.isActive('heading', { level: 2 })}
          title="Section heading"
        >
          H
        </ToolbarBtn>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolbarBtn
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive('bold')}
          title="Bold"
        >
          <strong>B</strong>
        </ToolbarBtn>
        <ToolbarBtn
          onClick={() => editor.chain().focus().toggleItalic().run()}
          active={editor.isActive('italic')}
          title="Italic"
        >
          <em>I</em>
        </ToolbarBtn>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolbarBtn
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          active={editor.isActive('bulletList')}
          title="Bullet list"
        >
          •≡
        </ToolbarBtn>
        <ToolbarBtn
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          active={editor.isActive('orderedList')}
          title="Numbered list"
        >
          1≡
        </ToolbarBtn>

        <span className="mx-1 h-3.5 w-px bg-slate-200" />

        <ToolbarBtn
          onClick={() => editor.isActive('link') ? editor.chain().focus().unsetLink().run() : addLink()}
          active={editor.isActive('link')}
          title={editor.isActive('link') ? 'Remove link' : 'Add link'}
        >
          🔗
        </ToolbarBtn>
      </div>
      <div className="px-3.5 py-3 text-[14px] leading-relaxed text-slate-800">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

function ToolbarBtn({
  onClick, active, title, children,
}: {
  onClick: () => void
  active?: boolean
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onMouseDown={(e) => { e.preventDefault(); onClick() }}
      title={title}
      className={`flex h-7 min-w-7 items-center justify-center rounded px-1.5 text-[12.5px] transition-colors ${
        active ? 'bg-teal-600 text-white' : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
      }`}
    >
      {children}
    </button>
  )
}

function parseTipTapContent(value: string): object {
  if (!value) return { type: 'doc', content: [] }
  try {
    const parsed = JSON.parse(value)
    if (parsed?.type === 'doc') return parsed
  } catch {}
  return {
    type: 'doc',
    content: [{ type: 'paragraph', content: value ? [{ type: 'text', text: value }] : [] }],
  }
}

// ---------------------------------------------------------------------------
// What's Included — reorderable checklist repeater
// ---------------------------------------------------------------------------

function WhatsIncludedEditor({
  items, onChange,
}: {
  items: string[]
  onChange: (items: string[]) => void
}) {
  function update(i: number, val: string) {
    const next = [...items]
    next[i] = val
    onChange(next)
  }
  function remove(i: number) {
    onChange(items.filter((_, idx) => idx !== i))
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= items.length) return
    const next = [...items]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  function add() {
    onChange([...items, ''])
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-teal-600">✓</span>
          <input
            value={item}
            onChange={(e) => update(i, e.target.value)}
            placeholder="e.g. Weekly live circle on Tuesdays"
            className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[14px] text-navy-900 outline-none transition-colors focus:border-teal-400"
            maxLength={300}
          />
          <button
            type="button"
            onClick={() => move(i, -1)}
            disabled={i === 0}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => move(i, 1)}
            disabled={i === items.length - 1}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
            title="Move down"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={() => remove(i)}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
            title="Remove"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="mt-1 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-300 hover:text-teal-700"
      >
        + Add item
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Practical details — typed inputs
// ---------------------------------------------------------------------------

function PracticalEditor({
  value, onChange,
}: {
  value: OfferPracticalSection
  onChange: (next: OfferPracticalSection) => void
}) {
  function set<K extends keyof OfferPracticalSection>(k: K, v: OfferPracticalSection[K]) {
    onChange({ ...value, [k]: v })
  }
  const fields = useMemo(() => [
    { key: 'dates',         label: 'Dates',          placeholder: 'e.g. 3 Feb – 17 Mar' },
    { key: 'duration',      label: 'Duration',       placeholder: 'e.g. 6 weeks, ~2 hrs / week' },
    { key: 'location',      label: 'Location',       placeholder: 'e.g. Online (Zoom) or Sydney' },
    { key: 'format',        label: 'Format',         placeholder: 'e.g. Live + self-paced' },
    { key: 'access_period', label: 'Access period',  placeholder: 'e.g. Lifetime access to recordings' },
    { key: 'capacity',      label: 'Capacity',       placeholder: 'e.g. 12 women per cohort' },
  ] as const, [])

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields.map(({ key, label, placeholder }) => (
        <FormField key={key} label={label}>
          <Input
            value={(value[key] ?? '') as string}
            onChange={(e) => set(key, (e.target.value || null) as OfferPracticalSection[typeof key])}
            placeholder={placeholder}
            maxLength={200}
          />
        </FormField>
      ))}
      <div className="sm:col-span-2">
        <FormField
          label="Requirements"
          helper="Anything a member needs before starting — a device, a journal, a prior pathway, etc."
        >
          <TextArea
            value={value.requirements ?? ''}
            onChange={(e) => set('requirements', e.target.value || null)}
            placeholder="e.g. A journal you're willing to write in weekly."
            rows={2}
            maxLength={500}
          />
        </FormField>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FAQs — question/answer repeater
// ---------------------------------------------------------------------------

function FaqsEditor({
  items, onChange,
}: {
  items: OfferFaqItem[]
  onChange: (items: OfferFaqItem[]) => void
}) {
  function update(i: number, patch: Partial<OfferFaqItem>) {
    const next = [...items]
    next[i] = { ...next[i], ...patch }
    onChange(next)
  }
  function remove(i: number) {
    onChange(items.filter((_, idx) => idx !== i))
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir
    if (j < 0 || j >= items.length) return
    const next = [...items]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  function add() {
    onChange([...items, { question: '', answer: '' }])
  }

  return (
    <div className="space-y-4">
      {items.map((item, i) => (
        <div key={i} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
              Q&amp;A {i + 1}
            </p>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => move(i, -1)}
                disabled={i === 0}
                className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                title="Move up"
              >
                ↑
              </button>
              <button
                type="button"
                onClick={() => move(i, 1)}
                disabled={i === items.length - 1}
                className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                title="Move down"
              >
                ↓
              </button>
              <button
                type="button"
                onClick={() => remove(i)}
                className="rounded p-1 text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600"
                title="Remove"
              >
                ✕
              </button>
            </div>
          </div>
          <div className="space-y-3">
            <FormField label="Question">
              <Input
                value={item.question}
                onChange={(e) => update(i, { question: e.target.value })}
                placeholder="e.g. Is this a live cohort or self-paced?"
                maxLength={300}
              />
            </FormField>
            <FormField label="Answer">
              <TextArea
                value={item.answer}
                onChange={(e) => update(i, { answer: e.target.value })}
                placeholder="Short, direct, warm."
                rows={3}
                maxLength={800}
              />
            </FormField>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="rounded-lg border border-dashed border-slate-300 px-3 py-2 text-[13px] font-medium text-slate-600 transition-colors hover:border-teal-300 hover:text-teal-700"
      >
        + Add question
      </button>
    </div>
  )
}
