'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiUrl } from '@/lib/api'
import {
  AUDIENCE_LABEL,
  CATEGORY_LABEL,
  WG,
  type DocumentListRow,
} from '@/lib/worldGuide'


const SERIF_ITALIC: React.CSSProperties = {
  color: WG.inkMuted,
  fontFamily: 'Georgia, serif',
  fontStyle: 'italic',
}


export default function DocumentsListPage() {
  const router = useRouter()
  const [rows, setRows] = useState<DocumentListRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  function reload() {
    fetch(apiUrl('/api/admin/world-guide/documents'), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`List: ${r.status}`)
        return r.json() as Promise<DocumentListRow[]>
      })
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }

  useEffect(() => reload(), [])

  async function duplicate(id: string) {
    setBusyId(id)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/world-guide/documents/${id}/duplicate`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) throw new Error(`Duplicate: ${res.status}`)
      const dup = await res.json() as { id: string }
      router.push(`/admin/world-guide/documents/${dup.id}`)
    } catch (e) { setError((e as Error).message); setBusyId(null) }
  }

  async function archive(id: string) {
    setBusyId(id)
    try {
      const res = await fetch(
        apiUrl(`/api/admin/world-guide/documents/${id}/archive`),
        { method: 'POST', credentials: 'include' },
      )
      if (!res.ok) throw new Error(`Archive: ${res.status}`)
      reload()
    } catch (e) { setError((e as Error).message) } finally { setBusyId(null) }
  }

  return (
    <div style={{ background: WG.pageBg, minHeight: '100%' }}>
      <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10">

        <header className="mb-8 flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-[720px]">
            <Link
              href="/admin/world-guide"
              className="text-[12.5px]"
              style={{ color: WG.inkMuted }}
            >
              ← World Guide
            </Link>
            <h1
              className="mt-2 font-serif text-[28px] leading-tight md:text-[32px]"
              style={{ color: WG.inkStrong }}
            >
              Documents
            </h1>
            <p className="mt-2 text-[14px] leading-relaxed" style={SERIF_ITALIC}>
              Every governance document across Fresh Collective — drafts, published versions, and archived records.
            </p>
          </div>
          <Link
            href="/admin/world-guide/documents/new"
            className="rounded-full px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
            style={{ background: WG.navy }}
          >
            Create document
          </Link>
        </header>

        {error && (
          <div
            className="mb-6 rounded-2xl px-4 py-3 text-[13px]"
            style={{ background: 'rgba(214, 96, 87, 0.08)', border: '1px solid rgba(214, 96, 87, 0.28)', color: '#a63c30' }}
          >
            {error}
          </div>
        )}

        <div
          className="overflow-hidden rounded-2xl"
          style={{ background: WG.cardBg, border: WG.divider, boxShadow: WG.cardShadow }}
        >
          {rows === null ? (
            <div className="p-8 text-[13px]" style={{ color: WG.inkMuted }}>Loading…</div>
          ) : rows.length === 0 ? (
            <div className="p-10 text-center">
              <p className="mx-auto max-w-[520px] text-[14px] leading-relaxed" style={SERIF_ITALIC}>
                No documents yet. Create the first governance document to begin building
                the Fresh Collective World Guide.
              </p>
            </div>
          ) : (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr style={{ background: WG.navySoft, color: WG.inkSofter}}>
                  <Th>Title</Th>
                  <Th>Category</Th>
                  <Th>Audience</Th>
                  <Th>Status</Th>
                  <Th>Version</Th>
                  <Th>Effective</Th>
                  <Th>Updated</Th>
                  <Th>Updated by</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr
                    key={r.id}
                    style={{ borderTop: idx === 0 ? undefined : WG.hairline, color: WG.ink }}
                  >
                    <Td>
                      <Link
                        href={`/admin/world-guide/documents/${r.id}`}
                        className="font-medium hover:underline"
                        style={{ color: WG.ink }}
                      >
                        {r.title}
                      </Link>
                      <div className="mt-0.5 text-[11.5px]" style={{ color: WG.inkSofter }}>
                        /{r.slug}
                      </div>
                    </Td>
                    <Td>{CATEGORY_LABEL[r.category] ?? r.category}</Td>
                    <Td>{AUDIENCE_LABEL[r.audience] ?? r.audience}</Td>
                    <Td><StatusPill status={r.status} /></Td>
                    <Td>{r.current_version_number ? `v${r.current_version_number}` : '—'}</Td>
                    <Td>{fmtDate(r.effective_date)}</Td>
                    <Td>{fmtDateTime(r.updated_at)}</Td>
                    <Td>{r.last_updated_by_name ?? '—'}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1.5">
                        <RowAction href={`/admin/world-guide/documents/${r.id}`}>Edit</RowAction>
                        <RowAction href={`/world-guide/${r.slug}`} external>Preview</RowAction>
                        <RowActionBtn
                          disabled={busyId === r.id}
                          onClick={() => duplicate(r.id)}
                        >
                          Duplicate
                        </RowActionBtn>
                        {r.status !== 'archived' && (
                          <RowActionBtn
                            disabled={busyId === r.id}
                            onClick={() => {
                              if (window.confirm('Archive this document? It will be hidden from the public World Guide.')) {
                                archive(r.id)
                              }
                            }}
                          >
                            Archive
                          </RowActionBtn>
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}


function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wide">
      {children}
    </th>
  )
}
function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 align-top">{children}</td>
}


function StatusPill({ status }: { status: 'draft' | 'published' | 'archived' }) {
  const style: Record<typeof status, React.CSSProperties> = {
    draft:     { background: WG.navySoft, color: WG.inkMuted, border: WG.hairline },
    published: { background: WG.accentSoft, color: WG.accent, border: `1px solid ${WG.accent}22` },
    archived:  { background: 'rgba(214,96,87,0.06)', color: '#a63c30', border: '1px solid rgba(214,96,87,0.20)' },
  }
  const label = status === 'published' ? 'Published' : status === 'draft' ? 'Draft' : 'Archived'
  return (
    <span
      className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={style[status]}
    >
      {label}
    </span>
  )
}


function RowAction({ href, external, children }: { href: string; external?: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      target={external ? '_blank' : undefined}
      rel={external ? 'noopener noreferrer' : undefined}
      className="rounded-full px-2.5 py-1 text-[12px] transition-colors"
      style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
    >
      {children}
    </Link>
  )
}
function RowActionBtn({
  onClick, disabled, children,
}: { onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full px-2.5 py-1 text-[12px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      style={{ background: '#FFFFFF', border: WG.divider, color: WG.ink }}
    >
      {children}
    </button>
  )
}


function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
}
function fmtDateTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
