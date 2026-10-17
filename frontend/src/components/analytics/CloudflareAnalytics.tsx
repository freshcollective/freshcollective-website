'use client'

import { useEffect, useRef } from 'react'
import { usePathname } from 'next/navigation'

import { isTrackablePath } from '@/lib/analytics'

/**
 * Cloudflare Web Analytics, reporting one page view per allowed page.
 *
 * Renders nothing. Mounted once in the root layout; decides per
 * navigation whether this page may be reported at all
 * (``isTrackablePath``), and reports it by loading Cloudflare's beacon.
 *
 * Why SPA mode is off
 * -------------------
 *
 * Cloudflare's single-page-app mode works by patching
 * ``history.pushState`` and listening for ``popstate``. Once that
 * patch is installed it reports *every* subsequent route the visitor
 * opens — including, for a signed-in member who happened to arrive
 * via a public page, their dashboard and their private conversations.
 * Nothing here could then intervene: unmounting the element does not
 * remove the patch, and the ``popstate`` listener cannot be
 * intercepted at all.
 *
 * **It is on by default.** Read from the beacon source (js 2026.10.1):
 * ``spa == null`` resolves to ``HistoryAndNavigationAPI``, so the
 * snippet exactly as the dashboard supplies it patches the History
 * API. ``spa: false`` resolves to ``None``, and the whole
 * instrumentation block — soft-navigation observer, Navigation API
 * listener, ``pushState`` patch, ``popstate`` listener — sits behind
 * that one check. Passing it explicitly is therefore load-bearing,
 * not defensive.
 *
 * What is transmitted
 * -------------------
 *
 * Every URL in the payload passes through the beacon's own sanitiser
 * before it leaves the browser: it clears ``search``, ``hash``,
 * ``username`` and ``password``, so an allowed page visited as
 * ``/about?utm_source=x#team`` reports ``/about`` and nothing more. A
 * query parameter can never be transmitted, which is why the
 * allow-list only has to be right about paths.
 *
 * The payload also carries a referrer, path intact. That is not a
 * path this module chose, so it is governed elsewhere: the app sends
 * ``Referrer-Policy: strict-origin`` (see ``securityHeaders``), which
 * reduces a same-origin referrer to the bare origin. Without that
 * header a member arriving at a public page by a full page load from
 * a private one would hand over the private path.
 *
 * Why a classic script and not the ``type="module"`` snippet
 * ----------------------------------------------------------
 *
 * A module script is evaluated once per URL per document, so
 * re-inserting the same ``src`` after a client-side navigation would
 * do nothing at all and only the first page of a visit would be
 * counted. A classic script re-executes on each insertion, which is
 * exactly the per-page report wanted here. Same host, same file, same
 * token as the snippet from the dashboard — only the element type
 * differs, and only because the module form cannot express "report
 * again".
 *
 * Known limitation: what a long visit accumulates
 * -----------------------------------------------
 *
 * ``load: "multi"`` means the beacon's setup runs once per reported
 * page, and two things are registered each time: a
 * ``visibilitychange`` listener, and the web-vitals observers. They
 * are not removed when the element is — removing a script tag does
 * not undo what the script did — so a visit that passes through ten
 * tracked pages in one document holds ten of each.
 *
 * Accepted, with its shape understood rather than guessed at. The
 * tracked surface is the public site, the beacon never executes on a
 * member area, and the History API instrumentation stays off, so the
 * long navigation chains inside the app cost nothing here. A visitor
 * reading five or ten public pages is the realistic case and browsers
 * carry that without complaint. It does grow with the length of a
 * single visit rather than with time, so it is unbounded in
 * principle.
 *
 * The real cost is to Core Web Vitals, not to page views. Each
 * execution measures from the same document's performance timeline,
 * so the second and later page views in a visit report the *first*
 * load's LCP rather than their own — performance data for those rows
 * should not be trusted. Page view counts are unaffected: each
 * execution sends its own ``pageloadId`` with no re-send marker, so
 * Cloudflare counts each as a distinct view.
 *
 * Duplicate page views
 * --------------------
 *
 * ``reported`` holds the last path actually sent. A re-render, a
 * search-parameter change, or React's development double-effect
 * therefore cannot report the same page twice; only a change of
 * pathname can. Nothing is reported on a path the allow-list refuses,
 * so a visit that begins on a private page begins with no beacon at
 * all.
 */

/** The site token from the Cloudflare dashboard.
 *
 *  Public by nature — it identifies the site in a script tag every
 *  visitor can read, and it authorises nothing. Inlined rather than
 *  read from the environment on purpose: an env var would have to live
 *  in ``render.yaml`` or the Render dashboard, and a committed
 *  ``value:`` there has twice reverted a Dashboard change on sync. One
 *  less moving part, in a file that is already reviewed on every
 *  change. */
const BEACON_TOKEN = '70ffb39db6cd40878cdc55a81e499397'

const BEACON_SRC = 'https://static.cloudflareinsights.com/beacon.min.js'

/** Marks the element this component owns, so it never removes another. */
const OWNED_ATTR = 'data-fc-analytics'

export default function CloudflareAnalytics() {
  const pathname = usePathname()
  const reported = useRef<string | null>(null)

  useEffect(() => {
    if (!pathname || !isTrackablePath(pathname)) return
    if (reported.current === pathname) return
    reported.current = pathname

    // Drop the previous beacon element before adding the next, so a
    // long browsing session does not accumulate dead script tags.
    document
      .querySelectorAll(`script[${OWNED_ATTR}]`)
      .forEach((el) => el.remove())

    const script = document.createElement('script')
    script.src = BEACON_SRC
    // No ``defer``: a dynamically inserted script is async already, and
    // the attribute would be inert here — it only means something on a
    // script the parser encounters in the document.
    script.setAttribute(OWNED_ATTR, 'true')
    // Two settings, and the component does not work without either.
    //
    // ``spa: false`` — see the note above. Without it, including by
    // simply omitting the key (which is how the dashboard's own
    // snippet comes), the beacon patches the History API and follows
    // the visitor into pages this module exists to exclude.
    //
    // ``load: "multi"`` — without it the beacon reports only the first
    // page of each visit, silently. ``load`` defaults to ``"single"``,
    // and on a second execution the script returns early, before the
    // token gate and before anything that transmits; the page view it
    // recorded goes into a closure-local buffer that is then
    // abandoned. ``"multi"`` is Cloudflare's own key for a document
    // that loads the beacon more than once, and it persists across
    // executions because the config merge lets the existing
    // ``window.__cfBeacon`` win.
    script.setAttribute(
      'data-cf-beacon',
      JSON.stringify({ token: BEACON_TOKEN, spa: false, load: 'multi' }),
    )
    document.body.appendChild(script)
  }, [pathname])

  return null
}
