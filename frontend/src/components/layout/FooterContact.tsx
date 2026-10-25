'use client'

/**
 * "Get in touch" — the footer's two addresses, with a copy button each.
 *
 * Replaces a single ``mailto:`` link. A mailto asks the browser to hand
 * the visitor to an email application, and on a machine with none
 * configured that is a dialog about choosing a program rather than an
 * answer to "how do I contact you". Showing the addresses and offering
 * to copy them keeps the visitor where they are.
 *
 * So nothing here navigates: no ``mailto:``, no ``href``, no redirect.
 * The addresses are plain text, selectable by hand (``select-all``
 * makes one click take the whole address rather than a word), and the
 * button is the convenience rather than the only route.
 *
 * A client component because the clipboard is a browser API; the footer
 * itself stays a server component and renders this inside it.
 */

import { useCallback, useState } from 'react'
import { CONTACT_INFO_EMAIL, CONTACT_SUPPORT_EMAIL } from '@/lib/contact'

type Status = 'idle' | 'copied' | 'failed'

const ROWS: Array<{ label: string; email: string }> = [
  { label: 'General enquiries', email: CONTACT_INFO_EMAIL },
  { label: 'Technical & account support', email: CONTACT_SUPPORT_EMAIL },
]

export default function FooterContact() {
  // Keyed by address, so copying one does not clear the other's
  // confirmation — two independent buttons, two independent states.
  const [status, setStatus] = useState<Record<string, Status>>({})

  const copy = useCallback(async (email: string) => {
    try {
      // ``navigator.clipboard`` needs a secure context and permission.
      // Where it is missing the honest answer is "select it yourself",
      // not a confirmation of something that did not happen.
      if (!navigator.clipboard?.writeText) throw new Error('unavailable')
      await navigator.clipboard.writeText(email)
      setStatus((s) => ({ ...s, [email]: 'copied' }))
    } catch {
      setStatus((s) => ({ ...s, [email]: 'failed' }))
    }
    window.setTimeout(() => {
      setStatus((s) => ({ ...s, [email]: 'idle' }))
    }, 2000)
  }, [])

  return (
    <div className="mt-7">
      <p
        className="mb-2.5 text-[13px] font-medium"
        style={{ color: '#FFFFFF' }}
      >
        Get in touch
      </p>

      <ul className="space-y-3">
        {ROWS.map(({ label, email }) => {
          const state = status[email] ?? 'idle'
          return (
            <li key={email}>
              <p
                className="text-[12px] leading-snug"
                style={{ color: 'rgba(255,255,255,0.62)' }}
              >
                {label}
              </p>
              {/* Wraps rather than truncates on a narrow screen: an
                  address cut off with an ellipsis cannot be read or
                  copied by hand, which defeats the point. */}
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span
                  className="select-all break-all text-[13.5px]"
                  style={{ color: '#FFFFFF' }}
                >
                  {email}
                </span>
                <button
                  type="button"
                  onClick={() => void copy(email)}
                  // The visible word is "Copy" for everyone; the label
                  // says WHICH address, because two identical buttons
                  // are indistinguishable to a screen reader.
                  aria-label={`Copy ${email} to the clipboard`}
                  className="rounded-md px-2 py-0.5 text-[11.5px] font-medium transition-colors"
                  style={{
                    border: '1px solid rgba(255,255,255,0.22)',
                    color: 'rgba(255,255,255,0.82)',
                  }}
                >
                  {state === 'copied'
                    ? 'Copied!'
                    : state === 'failed'
                      ? 'Select to copy'
                      : 'Copy'}
                </button>
                {/* Announced to assistive tech, which cannot see the
                    button's label change. Visually hidden because the
                    button itself already shows the outcome. */}
                <span aria-live="polite" aria-atomic="true" className="sr-only">
                  {state === 'copied'
                    ? `${email} copied to the clipboard`
                    : state === 'failed'
                      ? `Could not copy ${email}. Select the address to copy it.`
                      : ''}
                </span>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
