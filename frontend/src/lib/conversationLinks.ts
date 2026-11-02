/**
 * The one definition of a conversation's address.
 *
 * The notification email builds this path on the backend and the page
 * that serves it is here, so the two can disagree silently — which is
 * the shape of the bug the View Conversation button had. Keeping the
 * path in one named function on this side means the sign-in return
 * URL and the page's own links cannot drift from each other, and the
 * backend has a single string to match in its tests.
 */

/** Where a single conversation lives. */
export function conversationPath(slug: string, postId: string): string {
  return `/spaces/${slug}/community/${postId}`
}

/** Where a channel's feed lives. */
export function channelPath(slug: string, channelSlug?: string): string {
  const base = `/spaces/${slug}/community`
  return channelSlug ? `${base}?channel=${encodeURIComponent(channelSlug)}` : base
}

/**
 * The sign-in URL that returns somebody to where they were going.
 *
 * ``/login?next=<path>`` is the platform's existing mechanism —
 * ``LoginForm`` validates the target is a relative path before
 * following it, so an absolute URL cannot be smuggled through here.
 */
export function loginReturnPath(destination: string): string {
  return `/login?next=${encodeURIComponent(destination)}`
}

/**
 * Whether a ``next`` value is safe to return somebody to.
 *
 * Mirrors ``LoginForm.getSafeRedirect``: relative paths only, and not
 * the protocol-relative ``//host`` or a backslash variant that some
 * parsers treat as a host.
 */
export function isSafeReturnPath(next: string | null | undefined): boolean {
  if (!next) return false
  return /^\/(?!\/|\\)/.test(next)
}
