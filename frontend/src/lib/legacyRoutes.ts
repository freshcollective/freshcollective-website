/**
 * Preserved legacy URLs, ahead of the freshcollective.au cutover.
 *
 * The old Wix site is being retired, not migrated. Only two of its URLs
 * are preserved, because both are printed or linked somewhere we cannot
 * edit:
 *
 *   * ``/leadershipbodychart`` — the Human Design chart, referenced in
 *     material associated with the Natural Leader book.
 *   * ``/tnlbook123`` — the Natural Leader Book Companion, which book
 *     owners may have.
 *
 * Everything else retires through the ordinary 404. A homepage redirect
 * would assert an equivalence that does not exist.
 *
 * Nothing here hard-codes an origin. Both pages are relative, and their
 * metadata inherits whatever host serves the request, so the same build
 * is correct on the Render hostname today and on freshcollective.au
 * after cutover.
 */

// Relative with an explicit extension, matching ``securityHeaders.ts``:
// this module is unit-tested under Node's test runner, which does not
// resolve the ``@/`` tsconfig alias. ``allowImportingTsExtensions`` is
// enabled, and the Next bundler resolves it the same way.
import { checkEmbed, type EmbedProvider } from './embedAllowlist.ts'

/**
 * The Neutrino Human Design chart embed URL.
 *
 * Supplied by configuration rather than committed, because the widget
 * URL carries a ``key`` that identifies Lindsey's specific chart
 * configuration on the Neutrino platform. That key is not in this
 * repository and cannot be derived from anything in it, so there is
 * nothing to hard-code and guessing one would produce a page that
 * renders somebody else's chart or nothing at all.
 *
 * Expected shape:
 *   https://neutrinoplatform.com/widget-v2/iframe?type=chart&key=…
 *
 * Read server-side only. It is not a secret — it ends up in an iframe
 * src the browser can see — but keeping it off ``NEXT_PUBLIC_`` means
 * it is not baked into the client bundle at build time, so it can be
 * changed with a restart rather than a rebuild.
 */
export const NEUTRINO_CHART_EMBED_ENV = 'NEUTRINO_CHART_EMBED_URL'

/**
 * The one Neutrino path that is an embeddable widget.
 *
 * Enforced here as well as on the server, and that is not redundant:
 * every other embed URL in Fresh Collective is creator-pasted and
 * validated by ``embed_validator.py`` on save, so the server's path
 * rule is what protects it. This one never passes through the server at
 * all — it comes from configuration straight into an iframe — so
 * without this check a mistyped env var could frame
 * ``neutrinoplatform.com/app/…`` or the loader script on a public page.
 *
 * ``checkEmbed`` deliberately gates only the host (the server owns the
 * path rule for the creator flow), so the check belongs here rather
 * than by loosening or duplicating the shared validator.
 */
const NEUTRINO_WIDGET_PATH = '/widget-v2/iframe'

export type ChartEmbedResolution =
  | { configured: true; url: string; provider: EmbedProvider }
  | { configured: false; reason: 'unset' }
  | { configured: false; reason: 'rejected'; detail: string }

/**
 * Resolve the configured chart embed, validating it through the same
 * allowlist every creator-pasted embed goes through.
 *
 * Deliberately not trusted just because it came from configuration: a
 * mistyped env var is exactly how an arbitrary iframe would end up on a
 * public page, and ``checkEmbed`` already knows the rule (https only,
 * allowlisted host, and for Neutrino the exact widget path). Reusing it
 * means this route cannot drift from the embed security model, and no
 * allowlist change was needed — ``neutrinoplatform.com`` is already a
 * registered provider and already in CSP ``frame-src``.
 */
export function resolveChartEmbed(
  raw: string | undefined = process.env[NEUTRINO_CHART_EMBED_ENV],
): ChartEmbedResolution {
  const value = (raw ?? '').trim()
  if (!value) return { configured: false, reason: 'unset' }

  const checked = checkEmbed(value)
  if (!checked.ok) {
    return { configured: false, reason: 'rejected', detail: checked.reason }
  }

  // Host is allowlisted; now the path. Exact match, mirroring the
  // server's rule for the same host.
  let path: string
  try {
    path = new URL(checked.url).pathname
  } catch {
    return { configured: false, reason: 'rejected', detail: 'Not a valid URL.' }
  }
  const normalised = path !== '/' && path.endsWith('/') ? path.replace(/\/+$/, '') : path
  if (normalised !== NEUTRINO_WIDGET_PATH) {
    return {
      configured: false,
      reason: 'rejected',
      detail: `Expected the widget path ${NEUTRINO_WIDGET_PATH}, got ${path}.`,
    }
  }

  return { configured: true, url: checked.url, provider: checked.provider }
}
