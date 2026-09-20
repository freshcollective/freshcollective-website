'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'

import { apiUrl } from '@/lib/api'
import {
  joiningOptionPriceLabel,
  purchasabilityWarning,
} from '@/lib/joiningOptionPrice'
import type { JoinPolicy } from '@/types/platform'

/**
 * How people join this Collective.
 *
 * Free joining is the default and stays fully supported — most
 * Collectives should keep it. "Purchase required" closes the free door
 * only: membership then arrives attached to something the person
 * bought, which is already how every purchase on the platform behaves.
 *
 * Its own save rather than part of the big settings form, because
 * nominating doors writes to a different endpoint (each Payment
 * Option) than the policy does (the Space). Two saves that could half-
 * succeed inside one button is worse than two honest buttons.
 */

interface OptionSchedule {
  id: string
  name: string
  schedule_type: string
  status: string
  total_amount_cents: number | null
  installment_amount_cents: number | null
  installment_count: number | null
  interval: string | null
  currency: string
  /** The backend's answer, not ours. A surface must never re-decide
   *  what checkout will accept. */
  is_member_checkoutable: boolean
}

interface OptionRow {
  id: string
  name: string
  status: string
  is_joining_option: boolean
  payment_type: string
  currency: string
  /** Every published payment method for this Option. This is where
   *  the price actually lives. */
  schedules: OptionSchedule[]
  /** Option-level fallback for the rare shape with no usable
   *  schedule. Derived from the legacy columns server-side. */
  effective_price_cents: number | null
  /** 'ready' | 'configured_not_yet_checkoutable' | 'needs_attention'
   *  | 'draft' | 'archived', with the reasons behind it. */
  purchasability: string
  purchasability_notes: string[]
}

export default function JoinPolicyForm({ slug }: { slug: string }) {
  const [policy, setPolicy] = useState<JoinPolicy>('open')
  const [options, setOptions] = useState<OptionRow[]>([])
  const [loaded, setLoaded] = useState(false)
  const [savingPolicy, setSavingPolicy] = useState(false)
  const [busyOptionId, setBusyOptionId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [spaceRes, optionsRes] = await Promise.all([
          fetch(apiUrl(`/api/creator/spaces/${slug}`), { credentials: 'include' }),
          fetch(apiUrl(`/api/creator/spaces/${slug}/commerce/payment-options`), {
            credentials: 'include',
          }),
        ])
        if (cancelled) return
        if (spaceRes.ok) {
          const space = (await spaceRes.json()) as { join_policy?: JoinPolicy }
          setPolicy(space.join_policy ?? 'open')
        }
        if (optionsRes.ok) {
          setOptions((await optionsRes.json()) as OptionRow[])
        }
      } catch {
        if (!cancelled) setError('Could not load joining settings.')
      } finally {
        if (!cancelled) setLoaded(true)
      }
    })()
    return () => { cancelled = true }
  }, [slug])

  const savePolicy = useCallback(async (next: JoinPolicy) => {
    const previous = policy
    setPolicy(next)
    setSavingPolicy(true)
    setError(null)
    setNotice(null)
    try {
      const res = await fetch(apiUrl(`/api/creator/spaces/${slug}`), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ join_policy: next }),
      })
      if (!res.ok) throw new Error('save failed')
      setNotice(next === 'open'
        ? 'Anyone signed in can join for free.'
        : 'Joining now happens through a purchase.')
    } catch {
      setPolicy(previous)
      setError('Could not save that. Please try again.')
    } finally {
      setSavingPolicy(false)
    }
  }, [slug, policy])

  const toggleDoor = useCallback(async (option: OptionRow, next: boolean) => {
    setBusyOptionId(option.id)
    setError(null)
    setNotice(null)
    setOptions((prev) => prev.map((o) =>
      o.id === option.id ? { ...o, is_joining_option: next } : o))
    try {
      const res = await fetch(
        apiUrl(`/api/creator/spaces/${slug}/commerce/payment-options/${option.id}`),
        {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_joining_option: next }),
        },
      )
      if (!res.ok) throw new Error('save failed')
      setNotice(next
        ? `“${option.name}” is now a way to join.`
        : `“${option.name}” is no longer offered as a way to join.`)
    } catch {
      setOptions((prev) => prev.map((o) =>
        o.id === option.id ? { ...o, is_joining_option: !next } : o))
      setError('Could not save that. Please try again.')
    } finally {
      setBusyOptionId(null)
    }
  }, [slug])

  const published = options.filter((o) => o.status === 'published')
  const nominatedPublished = published.filter((o) => o.is_joining_option)
  const nominatedUnpublished = options.filter(
    (o) => o.is_joining_option && o.status !== 'published')

  return (
    <section className="rounded-2xl border border-border bg-white p-6">
      <h2 className="mb-1 text-[17px] font-semibold text-navy-900">How people join</h2>
      <p className="mb-5 max-w-[640px] text-[14px] leading-relaxed text-black">
        Whether someone can join this collective for free, or whether
        membership comes with a purchase.
      </p>

      {!loaded ? (
        <p className="text-[13px] text-black">Loading…</p>
      ) : (
        <>
          <div className="grid gap-2 sm:grid-cols-2">
            {([
              {
                value: 'open' as const,
                label: 'Free to join',
                desc: 'Anyone signed in can join. Paid pathways and gatherings inside still work as they do now.',
              },
              {
                value: 'purchase_required' as const,
                label: 'Purchase required',
                desc: 'No free join. People come in by buying one of the options you choose below.',
              },
            ]).map((opt) => (
              <label
                key={opt.value}
                className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-all"
                style={{
                  borderColor: policy === opt.value ? 'rgba(56,160,158,0.40)' : '#e2e8f0',
                  background: policy === opt.value ? 'rgba(56,160,158,0.06)' : 'transparent',
                }}
              >
                <input
                  type="radio"
                  name="join-policy"
                  value={opt.value}
                  checked={policy === opt.value}
                  disabled={savingPolicy}
                  onChange={() => void savePolicy(opt.value)}
                  className="mt-0.5 accent-teal-500"
                />
                <div>
                  <p className="text-[14px] font-medium text-navy-900">{opt.label}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-black">{opt.desc}</p>
                </div>
              </label>
            ))}
          </div>

          {policy === 'purchase_required' && (
            <div className="mt-6">
              <h3 className="mb-1 text-[15px] font-semibold text-navy-900">
                Ways to join
              </h3>
              <p className="mb-4 max-w-[640px] text-[13px] leading-relaxed text-black">
                Choose which published Payment Options appear on your public
                page as ways in. Buying one brings the person into the
                collective <strong>and</strong> gives them everything that
                option already grants — one purchase, not two.
              </p>

              {published.length === 0 ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-[13px] font-medium text-amber-800">
                    You have no published Payment Options yet.
                  </p>
                  <p className="mt-1 text-[12.5px] text-amber-700">
                    Until one is published and chosen here, nobody can join this
                    collective — visitors see “not open for new members right now”.{' '}
                    <Link href="/creator-studio/payment-options" className="underline">
                      Payment Options →
                    </Link>
                  </p>
                </div>
              ) : (
                <ul className="space-y-2 p-0">
                  {published.map((option) => (
                    <li
                      key={option.id}
                      className="flex items-start gap-3 rounded-xl border border-slate-200 p-3.5"
                    >
                      <input
                        type="checkbox"
                        id={`door-${option.id}`}
                        checked={option.is_joining_option}
                        disabled={busyOptionId !== null}
                        onChange={(e) => void toggleDoor(option, e.target.checked)}
                        className="mt-0.5 accent-teal-500"
                      />
                      <label htmlFor={`door-${option.id}`} className="cursor-pointer">
                        <p className="text-[14px] font-medium text-navy-900">
                          {option.name}
                        </p>
                        <p className="mt-0.5 text-[12.5px] text-black">
                          {joiningOptionPriceLabel(option)}
                        </p>
                        {purchasabilityWarning(option) && (
                          <p className="mt-1 text-[12px] leading-snug text-amber-700">
                            {purchasabilityWarning(option)}
                          </p>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
              )}

              {published.length > 0 && nominatedPublished.length === 0 && (
                <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                  <p className="text-[13px] font-medium text-amber-800">
                    No ways to join are selected.
                  </p>
                  <p className="mt-1 text-[12.5px] text-amber-700">
                    Visitors see “not open for new members right now”. Nobody can
                    join until you choose at least one.
                  </p>
                </div>
              )}

              {nominatedUnpublished.length > 0 && (
                <p className="mt-3 text-[12.5px] leading-relaxed text-amber-700">
                  {nominatedUnpublished.length === 1 ? 'One option is' : `${nominatedUnpublished.length} options are`}{' '}
                  chosen as a way to join but not published yet, so {nominatedUnpublished.length === 1 ? 'it is' : 'they are'} not shown to visitors.
                </p>
              )}

              <p className="mt-4 text-[12.5px] leading-relaxed text-black">
                People who are already members keep their access — changing this
                setting never removes anyone.
              </p>
            </div>
          )}
        </>
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
