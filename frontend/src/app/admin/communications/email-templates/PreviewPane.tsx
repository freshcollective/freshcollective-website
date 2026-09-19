'use client'

/**
 * The real email, rendered by the real renderer.
 *
 * The HTML comes from the preview endpoint, which runs the canonical
 * template and shell — there is no second rendering path, so what an
 * admin sees here is what a member receives. It is displayed in an
 * iframe with `sandbox` left empty: the email document brings its own
 * full-page styles, and an email is not a thing this page should let
 * run scripts or navigate anywhere.
 */

import { useEffect, useRef } from 'react'
import type {
  PreviewMode, PreviewResponse, PreviewVariant, VariantSelection,
} from '@/lib/emailTemplates'
import {
  CARD_BG, CARD_BORDER, CARD_SHADOW, HAIRLINE, INK, INK_MUTED, INK_SOFTER,
} from './tokens'

export default function PreviewPane({
  preview, loading, mode, onModeChange, variants, selection, onSelect,
}: {
  preview: PreviewResponse | null
  loading: boolean
  mode: PreviewMode
  onModeChange: (m: PreviewMode) => void
  variants: PreviewVariant[]
  selection: VariantSelection
  onSelect: (variantId: string, value: string) => void
}) {
  const frame = useRef<HTMLIFrameElement>(null)

  // srcDoc rather than a document.write: the iframe is sandboxed with
  // no allow-* tokens, so it has no script execution and no origin.
  useEffect(() => {
    const el = frame.current
    if (el && preview) el.srcdoc = preview.html
  }, [preview])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex rounded-lg p-0.5" style={{ background: 'rgba(12,24,38,0.05)' }}>
          <Toggle active={mode === 'effective'} onClick={() => onModeChange('effective')}>
            Current version
          </Toggle>
          <Toggle active={mode === 'default'} onClick={() => onModeChange('default')}>
            Fresh Collective default
          </Toggle>
        </div>
        {loading && (
          <span className="text-[12px]" style={{ color: INK_SOFTER }}>
            Rendering…
          </span>
        )}
      </div>

      {variants.length > 0 && (
        <div
          className="flex flex-col gap-3 rounded-xl px-4 py-3"
          style={{ background: CARD_BG, border: CARD_BORDER }}
        >
          {variants.map((v) => (
            <fieldset key={v.variant_id} className="flex flex-col gap-1.5">
              <legend className="text-[12px] font-semibold" style={{ color: INK }}>
                {v.label}
              </legend>
              {v.help_text && (
                <p className="text-[12px]" style={{ color: INK_SOFTER }}>
                  {v.help_text}
                </p>
              )}
              <div className="flex flex-wrap gap-3">
                {v.options.map((o) => (
                  <label
                    key={o.value}
                    className="inline-flex cursor-pointer items-center gap-1.5 text-[13px]"
                    style={{ color: INK_MUTED }}
                  >
                    <input
                      type="radio"
                      name={`variant-${v.variant_id}`}
                      checked={selection[v.variant_id] === o.value}
                      onChange={() => onSelect(v.variant_id, o.value)}
                      className="accent-[#22a598]"
                    />
                    {o.label}
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
      )}

      <div
        className="overflow-hidden rounded-xl"
        style={{ background: CARD_BG, border: CARD_BORDER, boxShadow: CARD_SHADOW }}
      >
        <div className="flex flex-col gap-0.5 px-4 py-3" style={{ borderBottom: HAIRLINE }}>
          <span className="text-[14px] font-semibold" style={{ color: INK }}>
            {preview?.subject ?? ' '}
          </span>
          {preview?.preheader && (
            <span className="text-[12px]" style={{ color: INK_SOFTER }}>
              {preview.preheader}
            </span>
          )}
        </div>
        <iframe
          ref={frame}
          title="Email preview"
          sandbox=""
          className="w-full"
          style={{ height: 620, border: 'none', background: '#FFFFFF' }}
        />
      </div>
    </div>
  )
}

function Toggle({
  active, onClick, children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-[6px] px-3 py-1.5 text-[12px] font-medium transition-colors"
      style={
        active
          ? { background: '#FFFFFF', color: '#0f766e', boxShadow: '0 1px 2px rgba(16,24,40,0.06)' }
          : { background: 'transparent', color: INK_MUTED }
      }
    >
      {children}
    </button>
  )
}
