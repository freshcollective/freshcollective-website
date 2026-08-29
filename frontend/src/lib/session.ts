/**
 * Session cookie constant shared by the middleware and server helpers.
 *
 * Signature verification lives on the backend only. fc-web deliberately
 * does not hold the JWT signing key — see SEC-002 and the least-privilege
 * decision recorded in the SEC-002 implementation report. The middleware
 * checks for cookie presence for routing purposes; ``requireAuthenticatedUser``
 * is the authoritative check and confirms the session with the backend
 * via ``/api/auth/me``.
 */

export const SESSION_COOKIE = 'fc_session'
