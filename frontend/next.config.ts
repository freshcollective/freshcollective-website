import type { NextConfig } from "next";

// SEC-011 Stage A — the actual header definitions live in
// ``src/lib/securityHeaders.ts`` so ``src/lib/csp.test.ts`` can
// import them without pulling ``next.config.ts`` into ESM (this
// file uses ``__dirname`` which isn't defined under Node's
// experimental-strip-types ESM loader).
// Explicit ``.ts`` extension matches the other Node-native test
// imports elsewhere in the codebase.
import { SECURITY_HEADERS } from "./src/lib/securityHeaders.ts";

/**
 * SEC-011 Stage A — browser security headers.
 *
 * Ownership split (deliberate):
 *   * fc-web (this file) owns every DOCUMENT-level browser security
 *     header: CSP, Permissions-Policy, X-Frame-Options,
 *     Referrer-Policy, X-Content-Type-Options, HSTS.
 *   * fc-api (`backend/app/main.py`) owns only the transport/content
 *     headers that make sense on JSON responses: HSTS, XCTO,
 *     Referrer-Policy. CSP is DELIBERATELY not applied to JSON APIs
 *     — browsers don't parse it on non-document responses.
 *
 * CSP is served as Content-Security-Policy-Report-Only in Stage A.
 * Enforcement flips in a separate Stage C commit after a manual
 * observation window with DevTools Console open (see SEC-011
 * investigation §5 / §12).
 */

const nextConfig: NextConfig = {
  turbopack: {
    root: __dirname,
  },

  // Remove ``X-Powered-By: Next.js`` — framework fingerprint has no
  // legitimate reader and is a small info-leak.
  poweredByHeader: false,

  // Shorten the Client Router Cache dwell time for dynamic pages.
  //
  // Every collective-scoped page (pathway steps, About pages, editor
  // views) is server-authenticated + reads live per-space data, so the
  // default 30-second in-memory cache of previously-rendered layouts
  // creates a stale-content window when writers navigate creator
  // studio → member page after saving. Setting ``dynamic: 0``
  // invalidates the dynamic-route cache on every navigation so a
  // freshly-saved alt text (or any other block edit) is visible on
  // the member page without waiting or forcing a hard reload. Static
  // pages keep the full 5-minute cache.
  experimental: {
    staleTimes: {
      dynamic: 0,
      static: 300,
    },
  },

  async headers() {
    return [
      {
        // Apply the security headers to every route — HTML, static
        // assets, API BFF responses alike. Modern browsers ignore
        // headers they don't understand on non-document responses, so
        // this is safe. The CSP-Report-Only header is only parsed by
        // browsers rendering documents.
        source: "/:path*",
        headers: SECURITY_HEADERS.map(({ key, value }) => ({ key, value })),
      },
    ];
  },

  async redirects() {
    return [
      // Legacy slug redirects — slugs were renamed; keep old URLs working.
      {
        source: '/spaces/fresh-collective',
        destination: '/spaces/the-natural-leader-hub',
        permanent: true,
      },
      {
        source: '/spaces/fresh-collective/:path*',
        destination: '/spaces/the-natural-leader-hub/:path*',
        permanent: true,
      },
      {
        source: '/spaces/winters-playground',
        destination: '/spaces/embody',
        permanent: true,
      },
      {
        source: '/spaces/winters-playground/:path*',
        destination: '/spaces/embody/:path*',
        permanent: true,
      },
    ]
  },
};

export default nextConfig;
