'use client'

/**
 * Google Analytics 4, on the public pages only.
 *
 * Mounted once in the root layout, because a tag that has to be
 * remembered on each new public page is a tag that will be forgotten.
 * It renders nothing, and on the great majority of routes it does
 * nothing either: every decision it makes is delegated to
 * ``googleAnalytics.ts``, which delegates the one that matters to the
 * allow-list in ``analytics.ts``.
 *
 * Four gates, in order:
 *
 *   1. No measurement ID in the environment — no script, no
 *      ``dataLayer``, no hit. The component returns ``null``.
 *   2. The current page is not on the allow-list — the loader is not
 *      rendered, so on a visit that never touches a public page no
 *      request to Google is made at all. Nothing under the signed-in
 *      surfaces, Creator Studio, admin, an invitation token or an auth
 *      page can start the tag.
 *   3. The tag is switched off outright for a non-trackable path, via
 *      Google's ``window['ga-disable-<id>']`` opt-out, re-evaluated on
 *      every navigation.
 *   4. A page view is sent only for a path the allow-list agrees to,
 *      checked again at send time.
 *
 * Gate 3 is the one that protects a member area, and it is separate
 * from gate 2 because unmounting a ``<Script>`` does not unload the
 * script: once ``gtag/js`` is in the document it stays there for the
 * life of the page, so a visitor who reads the homepage and then opens
 * their dashboard still has a live tag. It is separate from gate 4
 * because a live tag does not wait to be asked — GA4's enhanced
 * measurement fires ``scroll``, ``click``, ``file_download`` and the
 * video events from its own listeners, each stamped with the current
 * URL. Withholding a page view would not stop any of them. Gate 3
 * stops all of them, which is why it is set before anything else runs
 * and on every navigation rather than only the trackable ones.
 *
 * Why the page view is sent from here rather than by GA
 * ----------------------------------------------------
 *
 * GA4's "page changes based on browser history events" is switched off
 * in the GA admin, and ``send_page_view: false`` switches off the
 * initial one. Both are deliberate — see the note at the top of
 * ``googleAnalytics.ts``. The consequence is that this effect is the
 * only thing that reports a page, which is exactly the property
 * wanted: one place, one rule, and a navigation GA is not told about
 * is a navigation GA does not have.
 */

import Script from 'next/script'
import { usePathname } from 'next/navigation'
import { useEffect, useRef } from 'react'

import {
  GA_MEASUREMENT_ID,
  configureGtag,
  gtagSrc,
  measurementId,
  sendPageView,
  setGaDisabled,
  shouldLoadGtag,
} from '@/lib/googleAnalytics'

export default function GoogleAnalytics() {
  const pathname = usePathname()
  const id = measurementId(GA_MEASUREMENT_ID)
  const loadable = shouldLoadGtag(pathname, GA_MEASUREMENT_ID)

  // Declared first, so it has run before the tag is configured and
  // before any page view is queued: on the commit that first reaches a
  // public page the tag must already be enabled, and on the commit
  // that leaves one it must be switched off before GA's own listeners
  // can fire against the new URL. Not gated on ``loadable`` — the
  // navigations that matter here are precisely the ones where it is
  // false.
  useEffect(() => {
    setGaDisabled(pathname, GA_MEASUREMENT_ID)
  }, [pathname])

  // ``js`` and ``config`` must reach ``dataLayer`` before any event, or
  // the first page view lands against an unconfigured tag. Declared
  // before the page-view effect so it runs first on the commit that
  // first reaches a public page, and guarded by a ref so returning to
  // a public page later cannot configure the tag twice.
  const configured = useRef(false)
  useEffect(() => {
    if (!loadable || configured.current) return
    configured.current = configureGtag(GA_MEASUREMENT_ID)
  }, [loadable])

  useEffect(() => {
    // Refuses on its own if the path is not trackable, which is why
    // this runs on every navigation rather than only on the ones that
    // render the loader. One rule, in one place.
    sendPageView(pathname, window.location.origin, GA_MEASUREMENT_ID)
  }, [pathname])

  if (!id || !loadable) return null

  // ``id`` rather than a second read of the environment: this is the
  // validated value, and it is the only thing interpolated into a URL.
  return <Script id="ga-loader" src={gtagSrc(id)} strategy="afterInteractive" />
}
