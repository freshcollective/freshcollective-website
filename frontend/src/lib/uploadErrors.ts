/**
 * What an upload says when the request never finished.
 *
 * ``fetch`` rejects — rather than resolving with a failed status — when
 * the request never completed at all: the connection dropped, the tab
 * lost its network, the server went away mid-body. Two upload handlers
 * wrapped that in ``try``/``finally`` with no ``catch``, so the throw
 * escaped as an unhandled rejection (Sentry FC-WEB-6) and the member
 * was left reading whatever the half-finished UI happened to show.
 *
 * That is a different situation from a response that arrived and said
 * no. A 400 or a 413 carries the server's own reason and is already
 * handled; this is the case where there is no reason to report, only
 * the fact that nothing was confirmed.
 *
 * Deliberately not an automatic retry. The connection can fail after
 * the server has taken the whole file, so retrying on the member's
 * behalf risks a silent duplicate. The member asks again if they want
 * to — and the wording invites exactly that, without promising the
 * first attempt failed to arrive.
 */

/**
 * Shown when an upload request never completed.
 *
 * Says what happened, what to do, and nothing else. No status code, no
 * exception text, no endpoint: a dropped connection tells the member
 * nothing useful about our internals, and the raw error can carry a
 * host or a stack.
 */
export const UPLOAD_NETWORK_ERROR =
  "We couldn't complete the upload. Please check your connection and "
  + 'try again.'
