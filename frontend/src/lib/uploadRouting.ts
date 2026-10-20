/**
 * Which proxied requests are Offering file uploads (Offerings B5).
 *
 * Lives here rather than inside the BFF route handler for the reason
 * ``bffAuth.ts`` does: the route module imports ``next/server`` and
 * cannot be loaded by the plain ``node --test`` suite, so any rule worth
 * asserting has to be a pure function somewhere importable.
 *
 * The rule exists because these two endpoints need a different timeout
 * from every other proxied call. fc-api does not reply until the file
 * has been spooled to disk and transferred to R2 as a bounded multipart
 * upload, and on the largest allowed file that does not reliably finish
 * inside the proxy's 30-second default — which would show a creator a
 * network error for an upload that actually succeeded.
 *
 * It is deliberately narrow. Every other endpoint keeps the shorter
 * budget, so a genuinely stuck backend still gives up quickly instead of
 * holding browser connections open.
 */

/** ``…/files/{id}/replace`` — the only other endpoint carrying a file. */
const REPLACE_PATH = /\/files\/[^/]+\/replace$/

/** Paths that take the longer upload timeout. ``joined`` excludes ``/api/``. */
export function isOfferingFileUpload(method: string, joined: string): boolean {
  if (method.toUpperCase() !== 'POST') return false
  if (!joined.startsWith('creator/spaces/')) return false
  if (!joined.includes('/offerings/')) return false
  // Exactly two endpoints carry a file body. Matching loosely on
  // ``/files/`` would also catch ``…/files/reorder``, which is a small
  // JSON call — and giving that the 120-second budget would mean a stuck
  // backend held a browser connection four times longer for no reason.
  // Caught by the test for precisely that path.
  return joined.endsWith('/files') || REPLACE_PATH.test(joined)
}
