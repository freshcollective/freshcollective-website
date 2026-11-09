/**
 * Google Analytics 4 — the plumbing, kept out of React.
 *
 * Three decisions live here and nowhere else: whether the Google tag
 * may load at all, whether the tag is switched on for the page now
 * being shown, and whether a particular page view may be sent. All
 * three defer to ``isTrackablePath`` in ``analytics.ts``, which is the
 * allow-list and the privacy boundary; this module adds the vendor
 * specifics and the ``window`` plumbing around it.
 *
 * The middle one is ``setGaDisabled``, and it is the one that is easy
 * to leave out. Refusing to send a page view only governs the hits we
 * send; GA4's enhanced measurement sends its own — scroll, click,
 * file_download, the video events — from its own listeners, each
 * stamped with the current URL. A tag loaded on a public page and
 * still running after a client-side navigation would report a private
 * path on the first scroll, without a page view being involved at
 * all. Google's ``window['ga-disable-<id>']`` opt-out is what closes
 * that, and it is set on every navigation.
 *
 * Written as plain functions over an injectable host object rather than
 * as hooks, so the refusals can be tested for what they do — a test
 * can hand in a fake ``window``, call ``sendPageView`` with
 * ``/dashboard``, and assert that nothing was queued. A rule that is
 * only exercised through a rendered component is a rule nobody can
 * prove.
 *
 * What GA is told, and what it is not
 * -----------------------------------
 *
 * ``send_page_view: false``. GA4's own "page changes based on browser
 * history events" setting is **off** in the GA admin, deliberately: it
 * fires on every History API push, which in an App Router application
 * means every navigation, including the ones into a member's dashboard
 * or a conversation. Left on, it would report the paths this app
 * exists to keep out of a dashboard, and it would do so without ever
 * consulting the allow-list. So the automatic page view is refused at
 * both ends — switched off in the admin, and switched off again in the
 * tag configuration here — and every page view is sent by hand from
 * ``GoogleAnalytics.tsx`` after ``isTrackablePath`` has agreed.
 *
 * ``allow_google_signals: false`` and
 * ``allow_ad_personalization_signals: false``. Fresh Collective runs no
 * advertising and has no business linking a member to Google's
 * cross-device graph. These also keep the CSP narrow: the advertising
 * origins Google's guidance lists for Ads features
 * (``*.google.com``, ``*.g.doubleclick.net``) are not granted in
 * ``securityHeaders.ts``, and with these two false nothing asks for
 * them.
 *
 * ``page_location`` is set explicitly, to origin + pathname. Left to
 * itself gtag reads ``document.location``, which carries the query
 * string — and a query string is where ``?token=`` lives. The
 * allow-list already strips queries before matching, so a page can be
 * trackable while its URL is not; sending a path we constructed rather
 * than one the browser handed us closes that gap at the transmission
 * point, where it cannot be reopened by a new route.
 *
 * With no measurement ID configured this module does nothing at all:
 * no script, no ``dataLayer``, no hit. That is how every local run and
 * every CI build behaves.
 */

import { isTrackablePath } from './analytics.ts'

/**
 * The measurement ID, from the environment.
 *
 * ``NEXT_PUBLIC_*`` is inlined by Next at build time, so changing it
 * takes effect on a rebuild and never on a restart — the same
 * semantics as the Sentry DSN and the feature flags. On Render it is
 * ``sync: false``: Dashboard-owned, never written down in
 * ``render.yaml``.
 */
export const GA_MEASUREMENT_ID = (
  process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID ?? ''
).trim()

/**
 * A Google tag ID, or ``null``.
 *
 * Validated rather than trusted, for the reason the Sentry DSN is: an
 * environment variable becomes part of a URL the browser fetches, and
 * the shape is easy to get wrong in a way nothing would report. A
 * placeholder left in a dashboard field, a pasted stream ID, a stray
 * quote — each yields ``null`` here, and ``null`` means no analytics
 * rather than a tag that loads and silently measures nothing.
 *
 * Both prefixes Google issues for ``gtag/js`` are accepted: ``G-`` is
 * a GA4 measurement ID, ``GT-`` the newer Google tag ID that the same
 * loader URL takes. Anything else is refused.
 */
export function measurementId(raw: string | undefined): string | null {
  const value = (raw ?? '').trim()
  return /^G(?:T)?-[A-Za-z0-9]{4,24}$/.test(value) ? value : null
}

/** The loader URL. One origin, pinned in the CSP's ``script-src``. */
export function gtagSrc(id: string): string {
  return `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`
}

/**
 * May the Google tag be loaded for this page?
 *
 * The first of the two gates, and the one that decides whether a
 * request to Google is made at all. A visitor who only ever opens
 * signed-in surfaces never fetches ``gtag/js``, so there is no tag to
 * misbehave and nothing for a third party to observe.
 *
 * Fails closed on every uncertainty: no ID, a malformed ID, no
 * pathname yet.
 */
export function shouldLoadGtag(
  pathname: string | null | undefined,
  rawId: string | undefined = GA_MEASUREMENT_ID,
): boolean {
  if (!measurementId(rawId)) return false
  if (!pathname) return false
  return isTrackablePath(pathname)
}

/**
 * The tag configuration — see the module note for why each is here.
 *
 * Exported so ``googleAnalytics.test.ts`` can assert the three values
 * rather than trusting a literal buried in a call.
 */
export const GTAG_CONFIG: Readonly<Record<string, boolean>> = {
  send_page_view: false,
  allow_google_signals: false,
  allow_ad_personalization_signals: false,
}

/** The ``page_view`` parameters: a path, and never a query string. */
export function pageViewParams(
  pathname: string,
  origin: string,
): { page_path: string; page_location: string } {
  const path = pathname.split('?')[0].split('#')[0]
  return {
    page_path: path,
    page_location: `${origin.replace(/\/+$/, '')}${path}`,
  }
}

/** The subset of ``window`` the Google tag uses. */
export interface GtagHost {
  dataLayer?: unknown[]
  gtag?: (...args: unknown[]) => void
  /** ``ga-disable-<measurement id>`` — see ``setGaDisabled``. */
  [flag: `ga-disable-${string}`]: unknown
}

/**
 * Ensure ``window.gtag`` exists, and return it.
 *
 * The canonical snippet, written here instead of in an inline
 * ``<script>``. ``gtag`` is only a queue: it pushes its ``arguments``
 * onto ``dataLayer``, and ``gtag/js`` drains that queue in order once
 * it loads. Defining it from the module rather than from markup means
 * the queue is ready before the loader arrives — so a page view
 * queued during hydration is not lost — and it means this file needs
 * no ``'unsafe-inline'`` of its own to work.
 *
 * Idempotent: if the real ``gtag`` is already installed, it is left
 * alone.
 */
export function ensureGtag(host: GtagHost): (...args: unknown[]) => void {
  host.dataLayer ??= []
  if (typeof host.gtag !== 'function') {
    host.gtag = function gtag() {
      // ``arguments``, not an array: this is the shape gtag/js reads.
      // Read from ``host`` on each call rather than captured once, so
      // a later reassignment of ``dataLayer`` cannot strand the queue.
      // eslint-disable-next-line prefer-rest-params
      ;(host.dataLayer ??= []).push(arguments)
    }
  }
  return host.gtag
}

/** The window property name Google reads to switch a tag off. */
export function gaDisableFlag(id: string): string {
  return `ga-disable-${id}`
}

/**
 * Switch the whole tag off, or on, for the page now being shown.
 *
 * The guard that ``sendPageView`` cannot provide. Refusing to send a
 * page view stops *our* hit; it does nothing about the hits the tag
 * sends by itself. GA4's enhanced measurement is on by default and
 * fires ``scroll``, ``click``, ``file_download``, ``form_start`` and
 * the video events from its own listeners, each stamped with
 * ``page_location`` read from ``document.location`` at the moment it
 * fires. So a visitor who loads the homepage and then navigates to a
 * conversation has a live tag on a private path, and the first scroll
 * reports it — no page view required, and nothing in this codebase in
 * the way.
 *
 * ``window['ga-disable-<id>'] = true`` is Google's documented opt-out
 * and it is absolute: the tag stops transmitting entirely for that
 * measurement ID, autonomous events included. It is read at send
 * time rather than at load time, which is what makes it the right
 * tool here — it can be flipped on a client-side navigation, and
 * flipped back.
 *
 * Set on every navigation and on first load, from the one rule:
 * disabled is simply "this path is not trackable". A path the
 * allow-list has never heard of disables the tag, so the fail-closed
 * property survives into the one place that was still open.
 *
 * Returns the value written, or ``null`` if there was no configured ID
 * to key the flag on.
 */
export function setGaDisabled(
  pathname: string | null | undefined,
  rawId: string | undefined = GA_MEASUREMENT_ID,
  host: GtagHost = globalThis as GtagHost,
): boolean | null {
  const id = measurementId(rawId)
  if (!id) return null
  const disabled = !pathname || !isTrackablePath(pathname)
  host[gaDisableFlag(id) as `ga-disable-${string}`] = disabled
  return disabled
}

/**
 * Queue ``js`` and ``config`` for the tag. Returns whether it did.
 *
 * Call before the first page view; ordering within ``dataLayer`` is
 * what makes a page view land against a configured measurement ID.
 */
export function configureGtag(
  rawId: string | undefined = GA_MEASUREMENT_ID,
  host: GtagHost = globalThis as GtagHost,
  now: Date = new Date(),
): boolean {
  const id = measurementId(rawId)
  if (!id) return false
  const gtag = ensureGtag(host)
  gtag('js', now)
  gtag('config', id, { ...GTAG_CONFIG })
  return true
}

/**
 * Send one ``page_view`` — if this page is allowed to be reported.
 *
 * The second gate, and the one that matters on a client-side
 * navigation: the tag may already be loaded from a public page when
 * the visitor moves to their dashboard, and nothing about a loaded tag
 * stops it being told things. This is what stops it. Returns whether a
 * hit was queued, so the refusal is observable in a test.
 *
 * Note the order of the checks: the allow-list is consulted before
 * anything touches ``dataLayer``, so a refused path leaves no trace at
 * all rather than an empty event.
 */
export function sendPageView(
  pathname: string | null | undefined,
  origin: string,
  rawId: string | undefined = GA_MEASUREMENT_ID,
  host: GtagHost = globalThis as GtagHost,
): boolean {
  if (!measurementId(rawId)) return false
  if (!pathname || !isTrackablePath(pathname)) return false
  const gtag = ensureGtag(host)
  gtag('event', 'page_view', pageViewParams(pathname, origin))
  return true
}
