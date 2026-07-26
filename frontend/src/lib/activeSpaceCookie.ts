/**
 * The cookie that records which of a Creator's collectives is currently
 * "active" — the one the sidebar identifies at the top of Creator Studio
 * and the one Creator Studio pages resolve when the URL does not itself
 * name a slug.
 *
 * Extracted from ``serverApi.ts`` so files that cannot import from
 * ``next/headers`` (notably the proxy middleware) can share the same
 * constant. Both ``@/lib/serverApi`` and ``@/lib/activeSpaceCookie``
 * export the same value.
 */
export const ACTIVE_SPACE_COOKIE = 'fc_creator_space'
