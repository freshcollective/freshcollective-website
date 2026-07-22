'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import SimpleRichTextEditor from '@/components/creator/SimpleRichTextEditor'
import type { CreatorSpaceDetail } from '@/types/platform'

interface Props {
  space: CreatorSpaceDetail
}

/**
 * Section labels ("Welcome", "This week", "Notes") are fixed across all
 * collectives — the DB `guidance_*_title` fields still exist so old values
 * round-trip through save, but they are no longer displayed or editable.
 * Only the body fields are edited here.
 */
type TitleKey = 'guidance_start_title' | 'guidance_focus_title' | 'guidance_links_title'
type BodyKey  = 'guidance_start_body'  | 'guidance_focus_body'  | 'guidance_links_body'
type FieldKey = TitleKey | BodyKey

type FormState = Record<FieldKey, string>

const SECTIONS: Array<{
  bodyKey: BodyKey
  label: string
  bodyPlaceholder: string
  /**
   * When true, the section is auto-generated from other data (upcoming
   * Gatherings) and not editable from this form. The DB fields still
   * round-trip on save; nothing typed elsewhere for them is shown to members.
   */
  autoPopulated?: boolean
}> = [
  {
    bodyKey: 'guidance_start_body',
    label: 'Welcome',
    bodyPlaceholder: 'e.g. Begin with the Foundations pathway, then join the weekly circle.',
  },
  {
    bodyKey: 'guidance_focus_body',
    label: 'This week',
    bodyPlaceholder: '',
    autoPopulated: true,
  },
  {
    bodyKey: 'guidance_links_body',
    label: 'Notes',
    bodyPlaceholder: 'e.g. Community guidelines · Zoom link · Resource folder',
  },
]

export default function GuidancePanelForm({ space }: Props) {
  const router = useRouter()
  const [form, setForm] = useState<FormState>({
    guidance_start_title: space.guidance_start_title ?? '',
    guidance_start_body:  space.guidance_start_body  ?? '',
    guidance_focus_title: space.guidance_focus_title ?? '',
    guidance_focus_body:  space.guidance_focus_body  ?? '',
    guidance_links_title: space.guidance_links_title ?? '',
    guidance_links_body:  space.guidance_links_body  ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function setField(key: FieldKey, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
    setSaved(false)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const body: Record<string, string | null> = {}
      for (const k of Object.keys(form) as FieldKey[]) {
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
    <form onSubmit={handleSave}>
      <div className="space-y-8">
        {SECTIONS.map(({ bodyKey, label, bodyPlaceholder, autoPopulated }) => (
          <div key={bodyKey}>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-black">
              {label}
            </p>
            {autoPopulated && (
              <div
                className="mb-3 rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed text-black"
                style={{
                  background: 'rgba(56,160,158,0.06)',
                  border: '1px solid rgba(56,160,158,0.20)',
                }}
              >
                <span className="font-semibold" style={{ color: '#38A09E' }}>Auto-populated.</span>{' '}
                Members see a live schedule of your upcoming Gatherings in the next
                7 days. This editor is kept for future use and is not currently
                shown in the Member Hub.
              </div>
            )}
            {!autoPopulated && (
              <SimpleRichTextEditor
                value={form[bodyKey]}
                onChange={(json) => setField(bodyKey, json)}
                placeholder={bodyPlaceholder}
                minHeight={90}
              />
            )}
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
  )
}
