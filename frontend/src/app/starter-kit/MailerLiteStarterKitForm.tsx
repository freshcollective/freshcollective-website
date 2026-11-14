'use client'

/**
 * Creator Starter Kit opt-in form.
 *
 * MailerLite's own embed, transcribed into JSX — the same treatment as
 * ``app/tnlbook/MailerLiteBookForm.tsx``, and for the same reason: the
 * action URL, the ``fields[…]`` names, the hidden inputs, the class
 * names, the global callback name and the script URL are MailerLite's
 * functional contract, not ours. Changing any of them silently stops
 * subscribing people, and on an opt-in page nobody notices for weeks.
 *
 * What IS ours is the appearance. MailerLite ships ~600 lines of CSS
 * targeting ``#mlb2-48497910`` — Open Sans, a teal panel, a yellow
 * hover — which belongs to its own hosted page. Those rules are
 * dropped and the inputs and button carry Fresh Collective utilities
 * instead. Nothing about that touches the functional contract.
 *
 * Two differences from the book form, both taken from this embed
 * rather than assumed:
 *
 *   * **The name comes first and is optional.** Its field group is
 *     ``ml-field-name`` with no ``ml-validate-required``, where the
 *     book form's is required. Adding the class would make the form
 *     reject a submission MailerLite accepts.
 *   * **Email is second and carries ``ml-last-item``.**
 *
 * Class names are load-bearing and must not be "tidied":
 *   * ``ml-subscribe-form-48497910`` — how the success callback finds
 *     this form;
 *   * ``row-form`` / ``row-success`` — what it shows and hides;
 *   * ``ml-validate-email`` / ``ml-validate-required`` — how
 *     webforms.min.js knows what to validate;
 *   * ``ml-error`` — what it adds to a field group that fails.
 *
 * ``style={{ display: 'none' }}`` on the success body matches the
 * embed: the callback toggles it with jQuery, which writes inline
 * display. A Tailwind ``hidden`` class would work by accident.
 *
 * **The success copy is deliberately NOT MailerLite's.** The generated
 * text says the kit "is on it's way" and promises a download link —
 * but this form is double opt-in, so at that moment nothing has been
 * sent and nothing will be until the person confirms. Shipping that
 * wording would leave people waiting for a PDF that never arrives
 * because they never clicked. The replacement says what is actually
 * true. This is copy, not contract: ``row-success`` and the markup
 * around it are untouched.
 *
 * The small print under the heading is MailerLite's own and is kept —
 * it is what the subscriber is being told they are agreeing to.
 *
 * No CSP change was needed. The action and impression ping go to
 * ``assets.mailerlite.com`` and the script is the same
 * ``groot.mailerlite.com`` bundle the book form already loads; both
 * are granted. Dropping MailerLite's stylesheet also drops its
 * ``assets.mlcdn.com`` font and icon references, so no new origin is
 * reached. See ``lib/securityHeaders.ts``.
 *
 * reCAPTCHA is not in this embed — the ``.g-recaptcha`` rule in
 * MailerLite's CSS is vestigial, with no widget to match it.
 */

import Script from 'next/script'
import { useEffect } from 'react'

import {
  HERO_PRIMARY_SHAPE_CLASS,
  HERO_PRIMARY_SKIN_CLASS,
  HERO_PRIMARY_STYLE_AA,
} from '@/components/marketing/heroCtaButtons'

const FORM_ID = '48497910'
const ACTION =
  'https://assets.mailerlite.com/jsonp/998040/forms/204012058054755951/subscribe'
const TAKEL =
  'https://assets.mailerlite.com/jsonp/998040/forms/204012058054755951/takel'
const WEBFORMS_JS =
  'https://groot.mailerlite.com/js/w/webforms.min.js?v83147fa8ce2d95cb73ece7f28b469519'

/** Field appearance. MailerLite adds ``ml-error`` to the surrounding
 *  group on a failed validation; the scoped rule below colours it. */
const INPUT =
  'w-full rounded-lg border border-[#CBD3DC] bg-white px-4 py-3 text-[15px] '
  + 'text-navy-900 placeholder:text-[#7A8898] focus:border-teal-600 '
  + 'focus:outline-none focus:ring-2 focus:ring-teal-600/20'

type JQueryLike = (selector: string) => { show: () => void; hide: () => void }

export default function MailerLiteStarterKitForm() {
  useEffect(() => {
    const w = window as unknown as Record<string, unknown>
    const callbackName = `ml_webform_success_${FORM_ID}`

    // Has to be a global of this exact name — webforms.min.js calls it
    // by name after a successful subscribe. Same body as the embed.
    w[callbackName] = function () {
      const $ = (w.ml_jQuery || w.jQuery) as JQueryLike | undefined
      if (!$) return
      $(`.ml-subscribe-form-${FORM_ID} .row-success`).show()
      $(`.ml-subscribe-form-${FORM_ID} .row-form`).hide()
    }

    // MailerLite's form-impression ping, unchanged. Failures are
    // swallowed: a blocked tracker must never break the form.
    void fetch(TAKEL).catch(() => {})

    return () => {
      delete w[callbackName]
    }
  }, [])

  return (
    <>
      {/* Scoped to the container id, as MailerLite's own CSS was. One
          rule, for the only thing utilities cannot reach: the error
          state MailerLite applies to a field group at runtime. */}
      <style>{`
        #mlb2-${FORM_ID} .ml-error input {
          border-color: #DC2626;
        }
      `}</style>

      <div
        id={`mlb2-${FORM_ID}`}
        className={`ml-form-embedContainer ml-subscribe-form ml-subscribe-form-${FORM_ID}`}
      >
        <div className="ml-form-embedWrapper embedForm">
          <div className="ml-form-embedBody ml-form-embedBodyDefault row-form">
            {/* MailerLite's own content block. Its ``<h4>Creator Starter
                Kit</h4>`` is dropped — the page's h1 already says that,
                and repeating it inside the card would be a third
                heading saying the same words. The expectation-setting
                line stays: it is what the subscriber is agreeing to. */}
            <div className="ml-form-embedContent">
              <p className="text-[13.5px] leading-relaxed text-[#4A5568]">
                <em>
                  You&rsquo;ll also get a few short emails about building a
                  home for your work. Unsubscribe any time.
                </em>
              </p>
            </div>

            <form
              className="ml-block-form mt-4"
              action={ACTION}
              data-code=""
              method="post"
              target="_blank"
            >
              <div className="ml-form-formContent space-y-3">
                {/* Name first, and optional — no ``ml-validate-required``,
                    exactly as MailerLite generated it. */}
                <div className="ml-form-fieldRow">
                  <div className="ml-field-group ml-field-name">
                    <input
                      aria-label="name"
                      type="text"
                      className={`form-control ${INPUT}`}
                      data-inputmask=""
                      name="fields[name]"
                      placeholder="First Name"
                      autoComplete="given-name"
                    />
                  </div>
                </div>
                <div className="ml-form-fieldRow ml-last-item">
                  <div className="ml-field-group ml-field-email ml-validate-email ml-validate-required">
                    <input
                      aria-label="email"
                      aria-required="true"
                      type="email"
                      className={`form-control ${INPUT}`}
                      data-inputmask=""
                      name="fields[email]"
                      placeholder="Email"
                      autoComplete="email"
                    />
                  </div>
                </div>
              </div>

              <input type="hidden" name="ml-submit" value="1" />

              <div className="ml-form-embedSubmit mt-5">
                {/* The homepage's primary CTA, worn by a submit
                    button: the same shape, glow, radius and padding,
                    reused from ``heroCtaButtons`` rather than
                    matched by eye, in the deeper teal that lets
                    white type clear 4.5:1 — the homepage's own
                    gradient manages 3.06:1 at best, and this is the
                    only control on the page. ``primary`` stays first —
                    MailerLite's script finds this button by that
                    class to swap in the loading one below.

                    The focus ring is kept from the old button. The
                    hero links do without one; a form control that
                    submits an address should not. */}
                <button
                  type="submit"
                  className={
                    `primary w-full text-[16px] ${HERO_PRIMARY_SHAPE_CLASS} ${HERO_PRIMARY_SKIN_CLASS} `
                    + 'focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2'
                  }
                  style={HERO_PRIMARY_STYLE_AA}
                >
                  Send me the kit
                </button>
                {/* MailerLite swaps these two while submitting. The
                    same surface, so the swap is invisible apart from
                    the spinner. */}
                <button
                  disabled
                  style={{ display: 'none', ...HERO_PRIMARY_STYLE_AA }}
                  type="button"
                  className={`loading w-full text-[16px] ${HERO_PRIMARY_SHAPE_CLASS} ${HERO_PRIMARY_SKIN_CLASS}`}
                >
                  <div className="ml-form-embedSubmitLoad" />
                  <span className="sr-only">Loading...</span>
                </button>
              </div>

              <input type="hidden" name="anticsrf" value="true" />
            </form>
          </div>

          {/* Double opt-in: nothing has been sent yet, and the copy says
              so. See the note in the module docstring. */}
          <div
            className="ml-form-successBody row-success"
            style={{ display: 'none' }}
          >
            <div className="ml-form-successContent">
              <h3
                className="mb-2 text-[20px] text-navy-900"
                style={{ fontFamily: 'var(--font-serif)' }}
              >
                Nearly there
              </h3>
              <p className="text-[15px] leading-relaxed text-[#4A5568]">
                Check your inbox and confirm your email, and your kit will be
                on its way.
              </p>
            </div>
          </div>
        </div>
      </div>

      <Script src={WEBFORMS_JS} strategy="afterInteractive" />
    </>
  )
}
