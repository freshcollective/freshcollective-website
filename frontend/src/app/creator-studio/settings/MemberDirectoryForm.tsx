'use client'

import { useCallback, useState } from 'react'

import { Switch } from '@/components/platform/Switch'
import { apiUrl } from '@/lib/api'
import type { CreatorSpaceDetail } from '@/types/platform'

/**
 * Whether members of this Collective can see each other.
 *
 * The setting has existed on ``spaces`` since migration 027 and has
 * never had a control — every Collective has been sitting on the
 * column default. That is a decision a creator should get to make, and
 * it reaches further than the one screen it is named after, so the
 * copy here lists the consequences rather than making the creator
 * discover them one surface at a time.
 *
 * Deliberately its own save, and deliberately not part of the Home
 * configuration: privacy belongs on the Space, and a Home layout must
 * never be able to reopen a directory a creator has closed. The
 * backend enforces that independently — ``home_config.resolve`` drops
 * the Members tile whatever the stored layout says.
 */

interface Props {
  space: CreatorSpaceDetail
  /** Called after a successful save so the Home tile editor can pick
   *  up the tile list this setting decides. */
  onSaved?: (enabled: boolean) => void
}

export default function MemberDirectoryForm({ space, onSaved }: Props) {
  const [enabled, setEnabled] = useState(space.show_member_directory ?? false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const toggle = useCallback(async (next: boolean) => {
    // Optimistic: the switch answers immediately and rolls back if the
    // save fails, so a privacy control never sits in a state the
    // server has not agreed to.
    setEnabled(next)
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${space.slug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ show_member_directory: next }),
      })
      if (!res.ok) throw new Error('save failed')
      setNotice(next
        ? 'Members can now see who else is here.'
        : 'The member directory is closed.')
      onSaved?.(next)
    } catch {
      setEnabled(!next)
      setError('Could not save that. Please try again.')
    } finally {
      setSaving(false)
    }
  }, [space.slug, onSaved])

  return (
    <section>
      <h2 className="mb-1 text-[17px] font-semibold text-navy-900">Member directory</h2>
      <p className="mb-4 max-w-[640px] text-[13.5px] leading-relaxed text-black">
        Whether the people in this Collective can see each other.
      </p>

      <div
        className="rounded-2xl bg-white p-5"
        style={{ border: '1px solid rgba(0,0,0,0.07)' }}
      >
        <Switch
          checked={enabled}
          disabled={saving}
          onChange={(e) => void toggle(e.target.checked)}
          label="Allow members to see who else is part of this Collective"
        />

        <div className="mt-4 text-[13px] leading-relaxed text-black">
          <p className="mb-1.5 font-semibold text-navy-900">When this is on</p>
          <ul className="mb-3 list-disc space-y-1 pl-5">
            <li>Members appears in this Collective&rsquo;s navigation and on the Collective Home.</li>
            <li>Members can see the other people here, following the existing directory rules.</li>
            <li>
              Fresh Collective can recognise people as sharing this Collective — so a
              member who meets someone here sees that connection elsewhere on the platform.
            </li>
          </ul>
          <p className="mb-1.5 font-semibold text-navy-900">When it is off</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>There is no Members area in the navigation and no Members tile on the Home.</li>
            <li>Members see how many people are here, but not who they are. Leaders stay visible.</li>
            <li>Shared membership of this Collective stays private, and is not used to connect people elsewhere.</li>
          </ul>
        </div>
      </div>

      <p className="mt-3 min-h-[20px] text-[13px]" aria-live="polite">
        {error
          ? <span className="text-red-500">{error}</span>
          : notice
            ? <span className="text-black">{notice}</span>
            : null}
      </p>
    </section>
  )
}
