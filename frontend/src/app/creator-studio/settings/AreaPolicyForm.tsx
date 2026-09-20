'use client'

import { useCallback, useEffect, useState } from 'react'

import { apiUrl } from '@/lib/api'
import type { AreaPolicy } from '@/types/platform'

/**
 * What visitors and members can see.
 *
 * Each control decides whether an area can be **seen and reached** —
 * whether it appears in the Collective's navigation and on the
 * Collective Home, and whether its page answers. It is not the lock on
 * any individual thing inside: whether a particular Pathway opens or a
 * particular Gathering can be booked is decided by that Pathway's or
 * Gathering's own access rules, exactly as before.
 *
 * About, Collective Home and Messages are not offered. About is the
 * page people join from, the Home is where a member lands when their
 * term has ended, and Messages is how someone reaches the creator when
 * their access has lapsed — the moment a gate would hurt most.
 */

const AREA_COPY: Record<string, { label: string; helper: string; note?: string }> = {
  gatherings: {
    label: 'Gatherings',
    helper:
      'Who can see and open your Gatherings area — the schedule, individual gatherings and series. Booking a paid session still depends on that session’s own access rules.',
  },
  pathways: {
    label: 'Pathways',
    helper:
      'Who can see and open your Pathways area. Individual pathway and purchase pages stay publicly reachable, so people can still buy access without already having it.',
  },
  conversations: {
    label: 'Conversations',
    helper:
      'Who can see and open your community conversations. Individual channel permissions still apply underneath.',
  },
  members: {
    label: 'Members',
    helper: 'Who can see and open your members area.',
    note: 'The Members area also needs Member directory switched on, under Collective Home settings.',
  },
}

const POLICY_LABEL: Record<AreaPolicy, string> = {
  public: 'Everyone',
  members: 'Members',
  active_access: 'Members with active access',
}

const POLICY_HINT: Record<AreaPolicy, string> = {
  public: 'Anyone, including people who have not signed in.',
  members: 'Anyone who has joined this collective.',
  active_access:
    'Members who currently hold access — a term pass, a pathway, or access you have granted them.',
}

export default function AreaPolicyForm({ slug }: { slug: string }) {
  const [policies, setPolicies] = useState<Record<string, AreaPolicy>>({})
  const [options, setOptions] = useState<Record<string, AreaPolicy[]>>({})
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(apiUrl(`/api/creator/spaces/${slug}`), {
          credentials: 'include',
        })
        if (!res.ok) throw new Error('load failed')
        const data = (await res.json()) as {
          area_policies?: Record<string, AreaPolicy>
          area_policy_options?: Record<string, AreaPolicy[]>
        }
        if (cancelled) return
        // Resolved server-side, so an unconfigured Collective shows
        // the defaults actually in force rather than a blank.
        setPolicies(data.area_policies ?? {})
        setOptions(data.area_policy_options ?? {})
      } catch {
        if (!cancelled) setError('Could not load these settings.')
      } finally {
        if (!cancelled) setLoaded(true)
      }
    })()
    return () => { cancelled = true }
  }, [slug])

  const choose = useCallback(async (area: string, next: AreaPolicy) => {
    const previous = policies[area]
    setPolicies((p) => ({ ...p, [area]: next }))
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      // One request carrying the whole map, so a half-applied set of
      // doorways is not a state the Collective can be left in.
      const res = await fetch(apiUrl(`/api/creator/spaces/${slug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          area_policies: { areas: { ...policies, [area]: next } },
        }),
      })
      if (!res.ok) throw new Error('save failed')
      setNotice(
        `${AREA_COPY[area]?.label ?? area} is now visible to ${POLICY_LABEL[next].toLowerCase()}.`,
      )
    } catch {
      setPolicies((p) => ({ ...p, [area]: previous }))
      setError('Could not save that. Please try again.')
    } finally {
      setSaving(false)
    }
  }, [slug, policies])

  const areas = Object.keys(options)

  return (
    <section className="rounded-2xl border border-border bg-white p-6">
      <h2 className="mb-1 text-[17px] font-semibold text-navy-900">
        What visitors and members can see
      </h2>
      <p className="mb-5 max-w-[640px] text-[14px] leading-relaxed text-black">
        Each setting controls whether an area can be found and opened. What
        someone can then do inside — open a pathway, book a paid session —
        still depends on that pathway or session’s own access rules.
      </p>

      {!loaded ? (
        <p className="text-[13px] text-black">Loading…</p>
      ) : areas.length === 0 ? (
        <p className="text-[13px] text-black">No configurable areas.</p>
      ) : (
        <div className="space-y-6">
          {areas.map((area) => {
            const copy = AREA_COPY[area]
            const current = policies[area]
            return (
              <div key={area}>
                <p className="text-[14px] font-semibold text-navy-900">
                  {copy?.label ?? area}
                </p>
                {copy?.helper && (
                  <p className="mt-0.5 mb-2.5 max-w-[640px] text-[12.5px] leading-relaxed text-black">
                    {copy.helper}
                  </p>
                )}
                <div className="grid gap-2 sm:grid-cols-3">
                  {(options[area] ?? []).map((value) => (
                    <label
                      key={value}
                      className="flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 transition-all"
                      style={{
                        borderColor: current === value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                        background: current === value ? 'rgba(56,160,158,0.06)' : 'transparent',
                      }}
                    >
                      <input
                        type="radio"
                        name={`area-${area}`}
                        value={value}
                        checked={current === value}
                        disabled={saving}
                        onChange={() => void choose(area, value)}
                        className="mt-0.5 accent-teal-500"
                      />
                      <span>
                        <span className="block text-[13.5px] font-medium text-navy-900">
                          {POLICY_LABEL[value]}
                        </span>
                        <span className="mt-0.5 block text-[12px] leading-snug text-black">
                          {POLICY_HINT[value]}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
                {copy?.note && (
                  <p className="mt-2 text-[12px] leading-relaxed text-amber-700">
                    {copy.note}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}

      <p className="mt-4 min-h-[20px] text-[13px]" aria-live="polite">
        {error
          ? <span className="text-red-500">{error}</span>
          : notice
            ? <span className="text-black">{notice}</span>
            : null}
      </p>
    </section>
  )
}
