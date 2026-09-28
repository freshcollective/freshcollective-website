'use client'

import { useRef, useState } from 'react'
import {
  describeApplied,
  normaliseCodeInput,
  previewDiscount,
  stateFromPreview,
  type DiscountFieldState,
} from '@/lib/discountPreview'

/**
 * "Have a discount code?" — optional, collapsed until asked for.
 *
 * Collapsed by default because most members do not have one, and a
 * prominent empty code box on a checkout page reads as "you are paying
 * more than someone else" to everyone who cannot fill it in.
 *
 * The figures shown come from the server's preview response and are
 * never recomputed here. When a code is applied, the parent is handed
 * the *code* to send at checkout — not the price. The server prices it
 * again from scratch, so what is shown here is a quote, not a contract;
 * if the code lapses in between, checkout refuses rather than silently
 * charging full price.
 */
export default function DiscountCodeField({
  paymentOptionId, paymentOptionScheduleId, onChange, disabled,
}: {
  paymentOptionId: string
  paymentOptionScheduleId: string
  /** The applied code, or null when there is none to send. */
  onChange: (code: string | null) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [state, setState] = useState<DiscountFieldState>({ status: 'empty' })
  const inFlight = useRef<AbortController | null>(null)

  function reset() {
    inFlight.current?.abort()
    setState({ status: 'empty' })
    onChange(null)
  }

  function apply() {
    const code = normaliseCodeInput(value)
    if (!code) return
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    setState({ status: 'checking' })
    // A code is only "applied" once the server says so, so onChange(null)
    // holds until then — an in-flight check must never let a stale code
    // reach checkout.
    onChange(null)

    previewDiscount({
      code, paymentOptionId, paymentOptionScheduleId, signal: controller.signal,
    })
      .then((preview) => {
        if (controller.signal.aborted) return
        const next = stateFromPreview(preview)
        setState(next)
        setValue(preview.code)
        onChange(next.status === 'applied' ? preview.code : null)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        // Reaching here means the server could not be asked. Distinct
        // from "that code is no good", and said differently, because the
        // member's next move is different: try again, not find another
        // code.
        setState({
          status: 'unreachable',
          message: String((err as Error)?.message ?? err),
        })
        onChange(null)
      })
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        className="self-start text-[12px] text-neutral-600 underline underline-offset-2 hover:text-neutral-900 disabled:opacity-60"
      >
        Have a discount code?
      </button>
    )
  }

  const applied = state.status === 'applied' ? describeApplied(state.preview) : null

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="discount-code" className="text-[12px] font-medium text-neutral-700">
        Discount code
      </label>
      <div className="flex gap-2">
        <input
          id="discount-code"
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            if (state.status !== 'empty') reset()
          }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); apply() } }}
          disabled={disabled || state.status === 'checking'}
          autoComplete="off"
          spellCheck={false}
          placeholder="Enter code"
          className="min-w-0 flex-1 rounded-lg border border-neutral-300 px-2.5 py-1.5 text-[13px] uppercase tracking-wide placeholder:normal-case placeholder:tracking-normal disabled:opacity-60"
        />
        <button
          type="button"
          onClick={state.status === 'applied' ? reset : apply}
          disabled={disabled || state.status === 'checking' || !value.trim()}
          className="shrink-0 rounded-lg border border-neutral-300 px-3 py-1.5 text-[12px] font-semibold text-neutral-800 hover:bg-neutral-50 disabled:opacity-60"
        >
          {state.status === 'checking' ? 'Checking…'
            : state.status === 'applied' ? 'Remove' : 'Apply'}
        </button>
      </div>

      {applied && (
        <p className="rounded-md bg-emerald-50 px-2 py-1 text-[12px] text-emerald-800">
          Code applied — you save {applied.saving}. Total {applied.final}.
        </p>
      )}
      {state.status === 'rejected' && (
        <p className="rounded-md bg-amber-50 px-2 py-1 text-[12px] text-amber-800">
          {state.message}
        </p>
      )}
      {state.status === 'unreachable' && (
        <p className="rounded-md bg-red-50 px-2 py-1 text-[12px] text-red-700">
          {state.message}
        </p>
      )}
    </div>
  )
}
