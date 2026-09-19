'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiUrl } from '@/lib/api'
import type { TemplateListItem } from '@/lib/emailTemplates'
import TemplateList from './TemplateList'
import TemplateDetailView from './TemplateDetailView'
import { INK, INK_MUTED, SERIF_ITALIC } from './tokens'

const BASE = '/api/admin/communications/email-templates'

export default function EmailTemplatesClient({ adminEmail }: { adminEmail: string }) {
  const [templates, setTemplates] = useState<TemplateListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [openKey, setOpenKey] = useState<string | null>(null)

  const load = useCallback(() => {
    fetch(apiUrl(BASE), { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((rows: TemplateListItem[]) => { setTemplates(rows); setFailed(false) })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (openKey) {
    return (
      <div className="mx-auto max-w-[1400px]">
        <TemplateDetailView
          templateKey={openKey}
          adminEmail={adminEmail}
          onBack={() => setOpenKey(null)}
          onChanged={load}
        />
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[1000px] flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1
          className="text-[26px] font-semibold"
          style={{ color: INK, letterSpacing: '-0.02em' }}
        >
          Email Templates
        </h1>
        <p className="max-w-[62ch] text-[14px] leading-relaxed" style={{ color: INK_MUTED }}>
          The emails Fresh Collective sends on your behalf. Edit the voice of
          the ones that carry it; the ones that state money, access or security
          facts are written here and kept accurate for you.
        </p>
      </header>

      {loading && <p className="text-[14px]" style={SERIF_ITALIC}>Gathering the inventory…</p>}
      {failed && (
        <p className="text-[14px]" style={{ color: '#a63c30' }}>
          The email templates could not be loaded.
        </p>
      )}
      {!loading && !failed && (
        <TemplateList templates={templates} onOpen={setOpenKey} />
      )}
    </div>
  )
}
