'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ACTIVE_SPACE_COOKIE } from '@/lib/activeSpaceCookie'
import { extractApiErrorMessage } from '@/lib/apiError'

/**
 * Danger Zone — draft-Collective permanent delete.
 *
 * Deliberately narrow: only shown when ``space.status === 'draft'``.
 * The backend re-computes full eligibility on the actual DELETE
 * call (six commerce/membership counters plus owner check); this
 * component's job is (a) never present a destructive action when
 * it clearly wouldn't apply, and (b) require a match-the-name
 * confirmation before firing.
 *
 * Post-success:
 *   * Clear the active-collective cookie if it named the deleted
 *     slug (otherwise the sidebar would render "current
 *     collective" chrome for a Collective that no longer exists).
 *   * Navigate to /creator-studio (the index page) so the creator
 *     sees the switcher and their remaining Collectives.
 *
 * If the backend refuses with a 409 (eligibility drift — e.g., a
 * paying purchase materialised between page load and delete) the
 * modal shows the exact server message inline; the row is
 * untouched and the creator can dismiss.
 */

interface Props {
  slug: string
  name: string
  status: string
}

export default function DangerZone({ slug, name, status }: Props) {
  // Never render for anything but a draft — the archive lifecycle
  // for active/archived Collectives is deliberately out of scope
  // for this ticket and lives as a separate future feature.
  if (status !== 'draft') return null

  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const canConfirm = typed === name && !pending

  async function handleDelete() {
    setError(null)
    setPending(true)
    try {
      const res = await fetch(`/api/creator/spaces/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
      })
      if (!res.ok) {
        // Best-effort JSON parse; some errors come back as text.
        let body: unknown = null
        try { body = await res.json() } catch { /* non-JSON */ }
        setError(
          extractApiErrorMessage(body, {
            fallback: `Deletion failed (HTTP ${res.status}).`,
          }),
        )
        setPending(false)
        return
      }

      // Success. Clear the active-collective cookie if it named
      // this slug — otherwise the sidebar keeps rendering chrome
      // for a Collective that no longer exists. Cookies get
      // cleared by setting an expired ``max-age``; ``path`` MUST
      // match the original set-cookie in
      // ``creator-studio/collective/switch/[slug]/route.ts``.
      if (typeof document !== 'undefined') {
        const cookies = document.cookie.split(';').map((c) => c.trim())
        const activeRaw = cookies.find(
          (c) => c.startsWith(`${ACTIVE_SPACE_COOKIE}=`),
        )
        const active = activeRaw?.slice(ACTIVE_SPACE_COOKIE.length + 1)
        if (active === slug) {
          document.cookie = `${ACTIVE_SPACE_COOKIE}=; path=/; max-age=0; SameSite=Lax`
        }
      }

      // Return to Creator Studio index. router.push is fine — this is
      // client-side navigation, no server Redirect involved, so the
      // "absolute URL from Host header" concern that applied to
      // Route Handlers doesn't apply here.
      router.push('/creator-studio')
      router.refresh()
    } catch (err) {
      setError(extractApiErrorMessage(err, { fallback: 'Deletion failed.' }))
      setPending(false)
    }
  }

  return (
    <>
      <div
        className="mt-10 rounded-xl border p-5"
        style={{
          borderColor: 'rgba(220, 38, 38, 0.20)',
          background: 'rgba(254, 242, 242, 0.40)',
        }}
      >
        <h3
          className="mb-1 text-[14px] font-semibold uppercase tracking-wide"
          style={{ color: '#991b1b' }}
        >
          Danger zone
        </h3>
        <p
          className="mb-4 text-[13.5px] italic leading-relaxed"
          style={{ color: 'rgba(12, 24, 38, 0.66)', fontFamily: 'Georgia, serif' }}
        >
          This Collective is still a draft and has never been shared with
          members. You can delete it permanently. This cannot be undone.
        </p>
        <button
          type="button"
          onClick={() => { setTyped(''); setError(null); setOpen(true) }}
          className="rounded-full px-4 py-2 text-[13px] font-medium transition-colors"
          style={{
            background: 'white',
            color: '#991b1b',
            border: '1px solid rgba(220, 38, 38, 0.35)',
          }}
        >
          Delete this Collective
        </button>
      </div>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: 'rgba(12, 24, 38, 0.50)' }}
          onClick={() => !pending && setOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-[20px] leading-tight text-navy-900">
              Delete “{name}”?
            </h2>
            <p className="mt-3 text-[14px] leading-relaxed text-black">
              This will permanently remove the Collective and all of its
              content. This cannot be undone.
            </p>
            <label className="mt-4 block text-[13px] text-black">
              Type the Collective name to confirm:
              <input
                type="text"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoFocus
                disabled={pending}
                placeholder={name}
                className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-[14px] focus:border-slate-500 focus:outline-none"
              />
            </label>

            {error && (
              <p
                className="mt-3 rounded-lg px-3 py-2 text-[13px]"
                style={{
                  background: 'rgba(254, 242, 242, 0.8)',
                  color: '#991b1b',
                  border: '1px solid rgba(220, 38, 38, 0.25)',
                }}
              >
                {error}
              </p>
            )}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                disabled={pending}
                className="rounded-full px-4 py-2 text-[13px] font-medium text-navy-900 hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={!canConfirm}
                className="rounded-full px-4 py-2 text-[13px] font-semibold text-white transition-opacity disabled:opacity-40"
                style={{ background: '#dc2626' }}
              >
                {pending ? 'Deleting…' : 'Delete permanently'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
