'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import type { CreatorSpaceDetail } from '@/types/platform'

interface Props {
  space: CreatorSpaceDetail
}

type FieldKey =
  | 'guidance_start_title'
  | 'guidance_start_body'
  | 'guidance_focus_title'
  | 'guidance_focus_body'
  | 'guidance_links_title'
  | 'guidance_links_body'

type FormState = Record<FieldKey, string>

const SECTIONS: Array<{
  titleKey: FieldKey
  bodyKey: FieldKey
  label: string
  titlePlaceholder: string
  bodyPlaceholder: string
}> = [
  {
    titleKey: 'guidance_start_title',
    bodyKey:  'guidance_start_body',
    label: 'Start here',
    titlePlaceholder: 'Start here',
    bodyPlaceholder:  'e.g. Begin with the Foundations pathway, then join the weekly circle.',
  },
  {
    titleKey: 'guidance_focus_title',
    bodyKey:  'guidance_focus_body',
    label: 'Upcoming focus',
    titlePlaceholder: 'Upcoming focus',
    bodyPlaceholder:  'e.g. This week we are exploring the theme of rest and recovery.',
  },
  {
    titleKey: 'guidance_links_title',
    bodyKey:  'guidance_links_body',
    label: 'Helpful links',
    titlePlaceholder: 'Helpful links',
    bodyPlaceholder:  'e.g. Community guidelines · Zoom link · Resource folder',
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

  function set(key: FieldKey, value: string) {
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
        body[k] = form[k].trim() || null
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
      <div className="space-y-6">
        {SECTIONS.map(({ titleKey, bodyKey, label, titlePlaceholder, bodyPlaceholder }) => (
          <div key={titleKey}>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              {label}
            </p>
            <div className="space-y-2">
              <div>
                <label className="mb-1 block text-[13px] font-medium text-slate-600">
                  Title
                </label>
                <input
                  type="text"
                  value={form[titleKey]}
                  onChange={(e) => set(titleKey, e.target.value)}
                  placeholder={titlePlaceholder}
                  maxLength={100}
                  className="w-full rounded-xl border border-slate-200 px-3.5 py-2.5 text-[14px] text-slate-800 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-[13px] font-medium text-slate-600">
                  Text
                </label>
                <textarea
                  rows={3}
                  value={form[bodyKey]}
                  onChange={(e) => set(bodyKey, e.target.value)}
                  placeholder={bodyPlaceholder}
                  maxLength={500}
                  className="w-full resize-none rounded-xl border border-slate-200 px-3.5 py-2.5 text-[14px] text-slate-800 placeholder:text-slate-300 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-100"
                />
              </div>
            </div>
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
