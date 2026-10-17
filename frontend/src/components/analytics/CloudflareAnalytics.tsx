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
 * Why the beacon is loaded per page instead of once
 * -------------------------------------------------
 *
 * Cloudflare's own single-page-app mode (``spa: true``) works by
 * patching ``history.pushState`` and listening for ``popstate``. Once
 * that patch is installed it reports *every* subsequent route the
 * visitor opens — including, for a signed-in member who happened to
 * arrive via a public page, their dashboard and their private
 * conversations. Nothing in this component could then intervene:
 * unmounting the element does not remove the patch.
 *
 * So SPA mode is explicitly **off**, and this component does the
 * reporting itself: a fresh beacon per allowed page, one page view
 * each. The beacon never touches the History API, which means it can
 * only ever report a path this module decided to allow. Every
 * transmission is one we caused.
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
    // ``spa: false`` is the load-bearing half of this component — see
    // the note above. Without it the beacon patches the History API
    // and follows the visitor into pages this module exists to
    // exclude.
    script.setAttribute(
      'data-cf-beacon',
      JSON.stringify({ token: BEACON_TOKEN, spa: false }),
    )
    document.body.appendChild(script)
  }, [pathname])

  return null
}
