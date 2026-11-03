/**
 * Sending somebody to sign in, and bringing them back.
 *
 * One definition of "is this a safe place to return to", because the
 * question now has several askers: the Collective layout, the
 * conversation page, and `resolveAuthAction`.
 *
 * On trusting `x-pathname`
 * ------------------------
 * `proxy.ts` sets that header from `request.nextUrl.pathname` with
 * `Headers.set`, which *replaces* anything the client sent — so the
 * value is internally generated, not forwarded. The matcher covers
 * every page route, so it is always present in practice.
 *
 * It is validated here anyway. The cost is a regex; the cost of being
 * wrong is an open redirect, and "the middleware always runs" is the
 * kind of assumption that holds until somebody narrows a matcher.
 */

/** The fallback when there is no usable path to return to. */
export const DEFAULT_RETURN_PATH = '/dashboard'

/**
 * Whether a `next` value may be followed.
 *
 * Mirrors `LoginForm.getSafeRedirect`: a single leading slash, so a
 * relative path only. Rejects `//host` and `/\host`, which some
 * parsers read as a host and which are the usual way an open redirect
 * is smuggled through a "relative path" check.
 */
export function isSafeReturnPath(next: string | null | undefined): boolean {
  if (!next) return false
  return /^\/(?!\/|\\)/.test(next)
}

/**
 * The login URL that returns somebody to `pathname`.
 *
 * An unsafe or absent path falls back rather than throwing: the point
 * of this call is always to get somebody signed in, and losing their
 * original destination is a smaller harm than an error page.
 */
export function loginReturnFor(
  pathname: string | null | undefined,
  options: { loginPath?: string; fallback?: string } = {},
): string {
  const loginPath = options.loginPath ?? '/login'
  const fallback = options.fallback ?? DEFAULT_RETURN_PATH
  const destination = isSafeReturnPath(pathname) ? pathname! : fallback
  return `${loginPath}?next=${encodeURIComponent(destination)}`
}
