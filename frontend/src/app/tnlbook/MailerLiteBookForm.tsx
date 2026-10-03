'use client'

/**
 * The Natural Leader book-resource opt-in form.
 *
 * MailerLite's own embed, transcribed into JSX. It is NOT reimplemented:
 * the action URL, the three ``fields[…]`` names, the reCAPTCHA site key,
 * both hidden inputs, the success markup, the global callback name and
 * both script URLs are exactly as MailerLite generated them. Changing
 * any of those silently stops subscribing people, which on a URL printed
 * in a book is a failure nobody would notice for weeks.
 *
 * What IS ours is the appearance. MailerLite ships ~600 lines of CSS
 * targeting ``#mlb2-27181412`` with Open Sans and a navy button, which
 * belongs to the old Wix page. Those rules are dropped and the inputs
 * and button carry Fresh Collective utilities instead. Nothing about
 * that touches the functional contract.
 *
 * Class names are load-bearing and must not be "tidied":
 *   * ``ml-subscribe-form-27181412`` — how the success callback finds
 *     this form;
 *   * ``row-form`` / ``row-success`` — what it shows and hides;
 *   * ``ml-validate-email`` / ``ml-validate-required`` — how
 *     webforms.min.js knows what to validate;
 *   * ``ml-error`` — what it adds to a field group that fails.
 *
 * ``style={{ display: 'none' }}`` on the success body is deliberate and
 * matches the embed: the callback toggles it with jQuery's show/hide,
 * which writes inline display. A Tailwind ``hidden`` class would work by
 * accident rather than by contract.
 *
 * Why a client component: it needs two external scripts and a global
 * callback, none of which a Server Component can carry. These are the
 * first third-party scripts in Fresh Collective, which is why the CSP
 * needed widening — see ``lib/securityHeaders.ts``.
 */

import Script from 'next/script'
import { useEffect } from 'react'

const FORM_ID = '27181412'
const ACTION =
  'https://assets.mailerlite.com/jsonp/998040/forms/157084874450142696/subscribe'
const TAKEL =
  'https://assets.mailerlite.com/jsonp/998040/forms/157084874450142696/takel'
const WEBFORMS_JS =
  'https://groot.mailerlite.com/js/w/webforms.min.js?v83147fa8ce2d95cb73ece7f28b469519'
const RECAPTCHA_JS = 'https://www.google.com/recaptcha/api.js'
const RECAPTCHA_SITE_KEY = '6Lf1KHQUAAAAAFNKEX1hdSWCS3mRMv4FlFaNslaD'

/** Field appearance. MailerLite adds ``ml-error`` to the surrounding
 *  group on a failed validation; the scoped rule below colours it. */
const INPUT =
  'w-full rounded-lg border border-[#CBD3DC] bg-white px-4 py-3 text-[15px] '
  + 'text-navy-900 placeholder:text-[#7A8898] focus:border-teal-600 '
  + 'focus:outline-none focus:ring-2 focus:ring-teal-600/20'

type JQueryLike = (selector: string) => { show: () => void; hide: () => void }

export default function MailerLiteBookForm() {
  useEffect(() => {
    const w = window as unknown as Record<string, unknown>
    const callbackName = `ml_webform_success_${FORM_ID}`

    // The success callback has to be a global of this exact name —
    // webforms.min.js calls it by name after a successful subscribe.
    // Same body as the embed: jQuery swaps the form for the thank-you.
    w[callbackName] = function () {
      const $ = (w.ml_jQuery || w.jQuery) as JQueryLike | undefined
      if (!$) return
      $(`.ml-subscribe-form-${FORM_ID} .row-success`).show()
      $(`.ml-subscribe-form-${FORM_ID} .row-form`).hide()
    }

    // MailerLite's own form-impression ping, unchanged. Failures are
    // swallowed: a blocked tracker must never break the form.
    void fetch(TAKEL).catch(() => {})

    return () => {
      delete w[callbackName]
    }
  }, [])

  return (
    <>
      {/* Scoped to the container id, as MailerLite's own CSS was. Only
          the two things utilities cannot reach: the error state it
          applies at runtime, and the reCAPTCHA widget, which renders at
          a fixed 304px and needs scaling to fit a narrow phone. */}
      <style>{`
        #mlb2-${FORM_ID} .ml-error input {
          border-color: #DC2626;
        }
        #mlb2-${FORM_ID} .ml-form-recaptcha.ml-error iframe {
          border: solid 1px #DC2626;
        }
        @media screen and (max-width: 480px) {
          #mlb2-${FORM_ID} .g-recaptcha {
            transform: scale(0.85);
            -webkit-transform: scale(0.85);
            transform-origin: 0 0;
            -webkit-transform-origin: 0 0;
          }
          #mlb2-${FORM_ID} .ml-form-recaptcha {
            height: 65px;
          }
        }
      `}</style>

      <div
        id={`mlb2-${FORM_ID}`}
        className={`ml-form-embedContainer ml-subscribe-form ml-subscribe-form-${FORM_ID}`}
      >
        <div className="ml-form-embedWrapper embedForm">
          <div className="ml-form-embedBody ml-form-embedBodyDefault row-form">
            <form
              className="ml-block-form"
              action={ACTION}
              data-code=""
              method="post"
              target="_blank"
            >
              <div className="ml-form-formContent space-y-3">
                <div className="ml-form-fieldRow">
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
                <div className="ml-form-fieldRow">
                  <div className="ml-field-group ml-field-name ml-validate-required">
                    <input
                      aria-label="name"
                      aria-required="true"
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
                  <div className="ml-field-group ml-field-last_name ml-validate-required">
                    <input
                      aria-label="last_name"
                      aria-required="true"
                      type="text"
                      className={`form-control ${INPUT}`}
                      data-inputmask=""
                      name="fields[last_name]"
                      placeholder="Last name"
                      autoComplete="family-name"
                    />
                  </div>
                </div>
              </div>

              <div className="ml-form-recaptcha ml-validate-required mt-5">
                <div className="g-recaptcha" data-sitekey={RECAPTCHA_SITE_KEY} />
              </div>

              <input type="hidden" name="ml-submit" value="1" />

              <div className="ml-form-embedSubmit mt-5">
                <button
                  type="submit"
                  className="primary w-full rounded-lg bg-teal-700 px-5 py-3 text-[15px] font-semibold text-white transition hover:bg-teal-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 focus-visible:ring-offset-2"
                >
                  Let me in!
                </button>
                {/* MailerLite swaps these two while submitting. */}
                <button
                  disabled
                  style={{ display: 'none' }}
                  type="button"
                  className="loading w-full rounded-lg bg-teal-700 px-5 py-3 text-[15px] font-semibold text-white"
                >
                  <div className="ml-form-embedSubmitLoad" />
                  <span className="sr-only">Loading...</span>
                </button>
              </div>

              <input type="hidden" name="anticsrf" value="true" />
            </form>
          </div>

          <div
            className="ml-form-successBody row-success"
            style={{ display: 'none' }}
          >
            <div className="ml-form-successContent">
              <h4 className="mb-2 font-serif text-2xl text-navy-900">
                Thank you!
              </h4>
              <p className="text-[15px] leading-relaxed text-[#4A5568]">
                Please check your inbox to get access to all The Natural Leader
                Book goodies!
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* reCAPTCHA first — webforms.min.js expects the widget to exist. */}
      <Script src={RECAPTCHA_JS} strategy="afterInteractive" />
      <Script src={WEBFORMS_JS} strategy="afterInteractive" />
    </>
  )
}
