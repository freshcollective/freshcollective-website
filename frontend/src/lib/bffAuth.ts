/**
 * SEC-010 Step 2 — BFF-authenticated client-IP claim.
 *
 * Extracted from the route handler as a pure function so it can be
 * unit-tested with the built-in Node test runner without pulling in
 * the Next.js request pipeline. The security boundary lives here.
 *
 * Invariants (locked by ``bffAuth.test.ts``):
 *
 *   * ``X-Fc-Bff-Auth`` and ``X-Fc-Client-IP`` are ALWAYS deleted
 *     from the outbound Headers first, so a browser-supplied copy of
 *     either can never survive to fc-api even if a future allowlist
 *     edit accidentally started forwarding them.
 *   * ``X-Fc-Bff-Auth`` is only set when ``INTERNAL_BFF_SECRET`` is
 *     configured. Local dev (no env var) → header absent → fc-api
 *     falls through to the public branch of its key function.
 *   * ``X-Fc-Client-IP`` is only set when the credential is set AND
 *     an inbound ``CF-Connecting-IP`` is present. The value comes
 *     exclusively from Cloudflare (fronting fc-web); Cloudflare
 *     rejects inbound copies from clients at its edge (403), so this
 *     header at fc-web ingress cannot have been spoofed by the caller.
 */

export function applyBffAuthHeaders(
  outbound: Headers,
  inboundCfConnectingIp: string | null,
  bffSecret: string | undefined,
): void {
  // Belt-and-braces — allowlist above the caller already excludes both
  // internal headers, but explicit delete makes it impossible for a
  // future allowlist regression to let browser-supplied values through.
  outbound.delete('x-fc-bff-auth')
  outbound.delete('x-fc-client-ip')

  if (!bffSecret) {
    // No credential configured (local dev or unset in production).
    // fc-api's key function treats the request as public-path.
    return
  }

  outbound.set('x-fc-bff-auth', bffSecret)
  if (inboundCfConnectingIp) {
    outbound.set('x-fc-client-ip', inboundCfConnectingIp)
  }
}
