'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import SimpleRichTextEditor from '@/components/creator/SimpleRichTextEditor'
import type { CreatorSpaceDetail } from '@/types/platform'

/**
 * Sidebar guidance — the creator-authored half of the Important panel
 * that sits beside Conversations, Gatherings and Pathways.
 *
 * Named for where it appears. It is *not* the Collective Home, which
 * is why the old grouping stopped making sense once the Home shipped:
 * a creator editing "Member Hub" reasonably expected to be editing the
 * page members land on, and was editing a sidebar three pages away.
 *
 * Two editable sections, matching the two the panel actually renders.
 * The panel's third slot, "This week", is filled by a live list of the
 * next seven days' Gatherings and has no creator input — see the note
 * on ``guidance_focus_body`` below.
 *
 * Section labels ("Welcome", "Notes") are fixed across all
 * Collectives; the ``guidance_*_title`` columns they came from are no
 * longer displayed, editable, or sent by this form.
 */

type BodyKey = 'guidance_start_body' | 'guidance_links_body'

type FormState = Record<BodyKey, string>

/**
 * Fields this form deliberately does not touch.
 *
 * ``guidance_focus_body`` backed the old "This week" editor. The
 * member-facing slot has been driven by the live upcoming-Gatherings
 * list since well before the Collective Home, so anything typed there
 * could never reach a member — the renderer passes ``body: null`` for
 * that section and always has. The editor is gone rather than sitting
 * there disabled.
 *
 * The column stays, and this form omits the field from its PATCH body
 * so the stored text survives every save. At least one live Collective
 * has a real paragraph in there, written in good faith and never seen;
 * it is worth offering back to its creator as Welcome or About copy
 * rather than quietly deleting. Same for the three ``*_title``
 * columns, retired from the UI long ago but still holding values.
 */
const PRESERVED_UNUSED_COLUMNS = [
  'guidance_focus_title', 'guidance_focus_body',
  'guidance_start_title', 'guidance_links_title',
] as const

const SECTIONS: Array<{
  bodyKey: BodyKey
  label: string
  hint: string
  bodyPlaceholder: string
}> = [
  {
    bodyKey: 'guidance_start_body',
    label: 'Welcome',
    hint: 'How to begin here. Shown first in the sidebar.',
    bodyPlaceholder: 'e.g. Begin with the Foundations pathway, then join the weekly circle.',
  },
  {
    bodyKey: 'guidance_links_body',
    label: 'Notes',
    hint: 'Anything members need to hand. Left empty, this section is not shown at all.',
    bodyPlaceholder: 'e.g. Community guidelines · Zoom link · Resource folder',
  },
]

interface Props {
  space: CreatorSpaceDetail
}

export default function GuidancePanelForm({ space }: Props) {
  const router = useRouter()
  const [form, setForm] = useState<FormState>({
    guidance_start_body: space.guidance_start_body ?? '',
    guidance_links_body: space.guidance_links_body ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function setField(key: BodyKey, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
    setSaved(false)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      // Only the two fields this form owns. Everything in
      // PRESERVED_UNUSED_COLUMNS is absent from the body, and the
      // endpoint applies only the fields it is sent, so those columns
      // keep whatever they already hold.
      const body: Record<string, string | null> = {}
      for (const k of Object.keys(form) as BodyKey[]) {
        const v = form[k].trim()
        // A TipTap JSON doc with no content is treated as empty
        if (!v) { body[k] = null; continue }
        try {
          const parsed = JSON.parse(v)
          const isEmpty =
            parsed?.type === 'doc' &&
            (!parsed.content || parsed.content.length === 0 ||
              parsed.content.every((n: { type: string; content?: unknown[] }) =>
                n.type === 'paragraph' && (!n.content || n.content.length === 0)
              ))
          body[k] = isEmpty ? null : v
        } catch {
          body[k] = v || null
        }
      }
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError((data as { detail?: string }).detail ?? 'Could not save. Please try again.')
        return
      }
      setSaved(true)
      router.refresh()
    } catch {
      setError('Network error. Please check your connection.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section>
      <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Sidebar guidance</h2>
      <p className="mb-4 max-w-[640px] text-[13.5px] leading-relaxed text-black">
        Optional guidance shown to members in the sidebar on Conversations,
        Gatherings and Pathways. It does not appear on the Collective Home.
      </p>

      <form onSubmit={handleSave}>
        <div className="space-y-8">
          {SECTIONS.map(({ bodyKey, label, hint, bodyPlaceholder }) => (
            <div key={bodyKey}>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
                {label}
              </p>
              <p className="mb-3 text-[12.5px] leading-relaxed text-black">{hint}</p>
              <SimpleRichTextEditor
                value={form[bodyKey]}
                onChange={(json) => setField(bodyKey, json)}
                placeholder={bodyPlaceholder}
                minHeight={90}
              />
            </div>
          ))}
        </div>

        {error && (
          <p className="mt-4 text-[13px] text-red-500">{error}</p>
        )}

        <div className="mt-6 flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl px-5 py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          {saved && (
            <span className="text-[13px] font-medium" style={{ color: '#38A09E' }}>
              Saved
            </span>
          )}
        </div>
      </form>
    </section>
  )
}

export { PRESERVED_UNUSED_COLUMNS }
