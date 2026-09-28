'use client'

/**
 * Managing discount codes: the list, and the form that creates or edits one.
 *
 * Two principles run through this file.
 *
 * The API owns the rules. Whether a code may still be edited or deleted
 * comes back as ``definition_editable`` and ``deletable``; nothing here
 * recomputes them from a redemption count it would then have to keep in
 * step. When the API refuses something, its message is shown — it is
 * written for Creators, and replacing it with "Something went wrong"
 * would throw away the only useful part of the response.
 *
 * Creators see Creator units. Percentages are percentages and money is
 * dollars; basis points and cents exist only on the wire, converted in
 * ``lib/discountCodes`` at the boundary.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiUrl } from '@/lib/api'
import { extractApiErrorFromResponse } from '@/lib/apiError'
import {
  MAX_PERCENT,
  type DiscountCode,
  type DiscountFormValues,
  describeStatus,
  emptyForm,
  formFromCode,
  formatDiscountValue,
  formatExpiry,
  formatScope,
  formatUsage,
  normaliseCodeInput,
  toCreatePayload,
  toUpdatePayload,
  validateForm,
} from '@/lib/discountCodes'

interface OptionRow {
  id: string
  name: string
  status: 'draft' | 'published' | 'archived'
}

interface Props {
  spaceSlug: string
  defaultCurrency: string
}

const TONE_CLASS: Record<string, string> = {
  active: 'bg-teal-50 text-teal-700',
  inactive: 'bg-slate-100 text-slate-500',
  expired: 'bg-amber-50 text-amber-700',
  'used-up': 'bg-amber-50 text-amber-700',
}

export default function DiscountCodesClient({ spaceSlug, defaultCurrency }: Props) {
  const [codes, setCodes] = useState<DiscountCode[] | null>(null)
  const [options, setOptions] = useState<OptionRow[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editing, setEditing] = useState<DiscountCode | 'new' | null>(null)
  const [banner, setBanner] = useState<string | null>(null)

  const base = `/api/creator/spaces/${spaceSlug}/discount-codes`

  /** Refresh after a change. Called from handlers, never from an effect
   *  body — see the mount effect below for why that distinction matters. */
  const load = useCallback(async () => {
    try {
      const res = await fetch(apiUrl(base), { credentials: 'include' })
      if (!res.ok) {
        setLoadError(await extractApiErrorFromResponse(res, {
          fallback: 'We couldn’t load your discount codes.',
        }))
        return
      }
      setCodes(await res.json())
      setLoadError(null)
    } catch {
      setLoadError('We couldn’t reach the server. Please try again.')
    }
  }, [base])

  // The initial load is a promise chain rather than an awaited call, the
  // same shape ``PaymentOptionsIndexClient`` uses: setState reached
  // synchronously from an effect body triggers cascading renders, and
  // ``react-hooks/set-state-in-effect`` rightly objects.
  useEffect(() => {
    fetch(apiUrl(base), { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(await extractApiErrorFromResponse(r, {
            fallback: 'We couldn’t load your discount codes.',
          }))
        }
        return r.json() as Promise<DiscountCode[]>
      })
      .then((rows) => { setCodes(rows); setLoadError(null) })
      .catch((err: unknown) => setLoadError(
        err instanceof Error ? err.message : 'We couldn’t reach the server. Please try again.',
      ))
  }, [base])

  useEffect(() => {
    // Payment Options for the scope picker. Archived ones are left out
    // deliberately: Creator Studio treats archived Options as historical
    // and freezes them out of active workflows, so scoping a NEW code to
    // one would point at something no longer on sale. An existing code
    // already scoped to an Option that has since been archived still
    // shows its name, which the API supplies.
    fetch(
      apiUrl(`/api/creator/spaces/${spaceSlug}/commerce/payment-options`),
      { credentials: 'include' },
    )
      .then((r) => (r.ok ? (r.json() as Promise<OptionRow[]>) : []))
      .then((rows) => setOptions(rows.filter((o) => o.status !== 'archived')))
      .catch(() => { /* picker degrades to empty; scope stays Collective-wide */ })
  }, [spaceSlug])

  async function setActive(code: DiscountCode, active: boolean) {
    setBanner(null)
    const res = await fetch(
      apiUrl(`${base}/${code.id}/${active ? 'activate' : 'deactivate'}`),
      { method: 'POST', credentials: 'include' },
    )
    if (!res.ok) {
      setBanner(await extractApiErrorFromResponse(res, {
        fallback: 'We couldn’t change that code’s status.',
      }))
      return
    }
    await load()
  }

  async function remove(code: DiscountCode) {
    setBanner(null)
    if (!window.confirm(`Delete ${code.code}? This cannot be undone.`)) return
    const res = await fetch(apiUrl(`${base}/${code.id}`), {
      method: 'DELETE', credentials: 'include',
    })
    if (!res.ok) {
      // A 409 here is the redeemed-code refusal, and its message names
      // deactivation as the alternative. Surfaced verbatim.
      setBanner(await extractApiErrorFromResponse(res, {
        fallback: 'We couldn’t delete that code.',
      }))
      return
    }
    await load()
  }

  return (
    <div className="mt-8">
      {banner && (
        <div
          role="alert"
          className="mb-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13.5px] text-amber-900"
        >
          {banner}
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[58ch] text-[13.5px] text-slate-600">
          Codes aren’t case-sensitive — someone can type <em>family50</em> and
          it will match <strong>FAMILY50</strong>.
        </p>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
        >
          New discount code
        </button>
      </div>

      {loadError && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13.5px] text-red-800">
          {loadError}
        </div>
      )}

      {!loadError && codes === null && (
        <p className="text-[13.5px] text-slate-500">Loading…</p>
      )}

      {!loadError && codes?.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center">
          <p className="text-[15px] font-medium text-navy-900">No discount codes yet</p>
          <p className="mx-auto mt-1 max-w-md text-[13px] text-slate-600">
            Create one to offer a reduced price — on everything you sell, or on
            a single Payment Option.
          </p>
        </div>
      )}

      {!loadError && codes && codes.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-2xl border border-slate-200 bg-white">
          {codes.map((code) => {
            const status = describeStatus(code)
            return (
              <li key={code.id} className="flex flex-wrap items-start gap-4 px-5 py-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[15px] font-semibold text-navy-900">
                      {code.code}
                    </span>
                    <span className="text-[14px] text-slate-700">
                      {formatDiscountValue(code)} off
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold uppercase tracking-wider ${TONE_CLASS[status.tone]}`}
                    >
                      {status.label}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px] text-slate-600">
                    {formatScope(code)} · {formatUsage(code)}
                    {formatExpiry(code.expires_on) && ` · Ends ${formatExpiry(code.expires_on)}`}
                  </p>
                  {status.detail && (
                    <p className="mt-0.5 text-[12px] text-amber-700">{status.detail}</p>
                  )}
                  {!code.definition_editable && (
                    <p className="mt-0.5 text-[12px] text-slate-500">
                      This code has been used, so its code, value and what it
                      applies to are now fixed. You can still change when it
                      ends, how many times it can be used, and whether it’s on.
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditing(code)}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => void setActive(code, !code.is_active)}
                    className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-700 transition-colors hover:border-teal-300 hover:text-teal-700"
                  >
                    {code.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                  {code.deletable ? (
                    <button
                      type="button"
                      onClick={() => void remove(code)}
                      className="rounded-lg border border-slate-200 px-3 py-1.5 text-[12px] font-medium text-slate-600 transition-colors hover:border-red-200 hover:text-red-600"
                    >
                      Delete
                    </button>
                  ) : (
                    <span
                      className="text-[11.5px] text-slate-400"
                      title="Codes that have been used stay in your records. Deactivate it instead."
                    >
                      Used — deactivate instead
                    </span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {editing && (
        <DiscountCodeForm
          spaceSlug={spaceSlug}
          defaultCurrency={defaultCurrency}
          options={options}
          existing={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await load() }}
        />
      )}
    </div>
  )
}


function DiscountCodeForm({
  spaceSlug, defaultCurrency, options, existing, onClose, onSaved,
}: {
  spaceSlug: string
  defaultCurrency: string
  options: OptionRow[]
  existing: DiscountCode | null
  onClose: () => void
  onSaved: () => void | Promise<void>
}) {
  const definitionEditable = existing ? existing.definition_editable : true
  const [values, setValues] = useState<DiscountFormValues>(
    existing ? formFromCode(existing) : emptyForm(defaultCurrency),
  )
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const set = <K extends keyof DiscountFormValues>(key: K, v: DiscountFormValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: v }))

  // An Option this code already points at may have been archived since;
  // keep it listed so the selector does not silently lose the value.
  const selectable = useMemo(() => {
    if (!existing?.scope_id) return options
    if (options.some((o) => o.id === existing.scope_id)) return options
    return [
      ...options,
      {
        id: existing.scope_id,
        name: `${existing.scope_payment_option_name ?? 'Archived option'} (archived)`,
        status: 'archived' as const,
      },
    ]
  }, [options, existing])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const problem = validateForm(values)
    if (problem) { setError(problem); return }

    setSaving(true)
    try {
      const base = `/api/creator/spaces/${spaceSlug}/discount-codes`
      const res = existing
        ? await fetch(apiUrl(`${base}/${existing.id}`), {
            method: 'PATCH', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(toUpdatePayload(values, definitionEditable)),
          })
        : await fetch(apiUrl(base), {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(toCreatePayload(values)),
          })

      if (!res.ok) {
        // Duplicate code, invalid scope, a definition edit after
        // redemption — the API says exactly what happened, in Creator
        // language. Show it rather than a generic apology.
        setError(await extractApiErrorFromResponse(res, {
          fallback: 'We couldn’t save that code. Please check the details and try again.',
        }))
        return
      }
      await onSaved()
    } catch {
      setError('We couldn’t reach the server. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/30 p-4 py-10">
      <form
        onSubmit={submit}
        className="w-full max-w-[560px] rounded-2xl bg-white p-6 shadow-xl"
      >
        <h2 className="font-serif text-[20px] text-navy-900">
          {existing ? `Edit ${existing.code}` : 'New discount code'}
        </h2>

        {!definitionEditable && (
          <p className="mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-[12.5px] text-slate-600">
            This code has already been used, so its code, value and what it
            applies to can’t be changed — people have bought at that price.
            You can still change when it ends, how many times it can be used,
            and whether it’s on.
          </p>
        )}

        {error && (
          <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-800">
            {error}
          </p>
        )}

        <label className="mt-5 block text-[13px] font-medium text-navy-900">
          Code
          <input
            value={values.code}
            disabled={!definitionEditable}
            onChange={(e) => set('code', normaliseCodeInput(e.target.value))}
            placeholder="FAMILY50"
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-[14px] uppercase text-navy-900 outline-none focus:border-teal-400 disabled:bg-slate-50 disabled:text-slate-400"
          />
          <span className="mt-1 block text-[12px] font-normal text-slate-500">
            Shown in capitals, but it doesn’t matter how someone types it.
          </span>
        </label>

        <fieldset className="mt-4" disabled={!definitionEditable}>
          <legend className="text-[13px] font-medium text-navy-900">Discount</legend>
          <div className="mt-1 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-[13px] text-slate-700">
              <input
                type="radio" name="discount-type" value="percentage"
                checked={values.discountType === 'percentage'}
                onChange={() => set('discountType', 'percentage')}
              />
              A percentage off
            </label>
            <label className="flex items-center gap-2 text-[13px] text-slate-700">
              <input
                type="radio" name="discount-type" value="fixed_amount"
                checked={values.discountType === 'fixed_amount'}
                onChange={() => set('discountType', 'fixed_amount')}
              />
              A set amount off
            </label>
          </div>

          {values.discountType === 'percentage' ? (
            <label className="mt-3 block text-[13px] text-slate-700">
              Percentage
              <div className="mt-1 flex items-center gap-2">
                <input
                  type="number" min={1} max={MAX_PERCENT} step="0.01"
                  value={values.percent}
                  onChange={(e) => set('percent', e.target.value)}
                  className="w-32 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400 disabled:bg-slate-50"
                />
                <span className="text-[14px] text-slate-600">%</span>
              </div>
              <span className="mt-1 block text-[12px] text-slate-500">
                Up to {MAX_PERCENT}%. To give someone access for free, use a
                complimentary pass rather than a discount.
              </span>
            </label>
          ) : (
            <div className="mt-3 flex flex-wrap gap-3">
              <label className="text-[13px] text-slate-700">
                Amount
                <input
                  type="number" min="0.01" step="0.01"
                  value={values.amount}
                  onChange={(e) => set('amount', e.target.value)}
                  className="mt-1 block w-36 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400 disabled:bg-slate-50"
                />
              </label>
              <label className="text-[13px] text-slate-700">
                Currency
                <input
                  value={values.currency}
                  onChange={(e) => set('currency', e.target.value.toUpperCase())}
                  maxLength={3}
                  className="mt-1 block w-24 rounded-lg border border-slate-200 px-3 py-2 text-[14px] uppercase text-navy-900 outline-none focus:border-teal-400 disabled:bg-slate-50"
                />
              </label>
            </div>
          )}
        </fieldset>

        <fieldset className="mt-4" disabled={!definitionEditable}>
          <legend className="text-[13px] font-medium text-navy-900">Applies to</legend>
          <label className="mt-1 flex items-center gap-2 text-[13px] text-slate-700">
            <input
              type="radio" name="scope" value="space"
              checked={values.scope === 'space'}
              onChange={() => set('scope', 'space')}
            />
            Everything in this Collective
          </label>
          <label className="mt-1 flex items-center gap-2 text-[13px] text-slate-700">
            <input
              type="radio" name="scope" value="payment_option"
              checked={values.scope === 'payment_option'}
              onChange={() => set('scope', 'payment_option')}
            />
            One Payment Option
          </label>
          {values.scope === 'payment_option' && (
            <select
              value={values.paymentOptionId}
              onChange={(e) => set('paymentOptionId', e.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400 disabled:bg-slate-50"
            >
              <option value="">Choose a Payment Option…</option>
              {selectable.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          )}
        </fieldset>

        <div className="mt-4 flex flex-wrap gap-4">
          <label className="text-[13px] text-slate-700">
            Ends on <span className="text-slate-400">(optional)</span>
            <input
              type="date"
              value={values.expiresAt}
              onChange={(e) => set('expiresAt', e.target.value)}
              className="mt-1 block rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400"
            />
          </label>
          <label className="text-[13px] text-slate-700">
            Limit on uses <span className="text-slate-400">(optional)</span>
            <input
              type="number" min={1} step={1}
              value={values.maxRedemptions}
              onChange={(e) => set('maxRedemptions', e.target.value)}
              placeholder="No limit"
              className="mt-1 block w-36 rounded-lg border border-slate-200 px-3 py-2 text-[14px] text-navy-900 outline-none focus:border-teal-400"
            />
          </label>
        </div>

        <label className="mt-4 flex items-center gap-2 text-[13px] text-slate-700">
          <input
            type="checkbox"
            checked={values.isActive}
            onChange={(e) => set('isActive', e.target.checked)}
          />
          Available for people to use now
        </label>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button" onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-[13px] font-medium text-slate-600"
          >
            Cancel
          </button>
          <button
            type="submit" disabled={saving}
            className="rounded-lg px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
          >
            {saving ? 'Saving…' : existing ? 'Save changes' : 'Create code'}
          </button>
        </div>
      </form>
    </div>
  )
}
