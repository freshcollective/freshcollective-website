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

  // Release identity for the browser bundle.
  //
  // The Node runtime reads Render's ``RENDER_GIT_COMMIT`` directly, but
  // the browser cannot: only ``NEXT_PUBLIC_*`` variables and the keys
  // listed here are inlined into the client bundle. Mapping the one
  // Render already provides is what lets a browser issue say which
  // deploy it came from without anyone having to set — and keep in step
  // — a second variable.
  //
  // Absent (a local build) yields an empty string, which
  // ``sentryRelease()`` reads as "no release". Never a placeholder:
  // "unknown" looks like a version and groups every deploy together.
  env: {
    NEXT_PUBLIC_RELEASE_COMMIT: process.env.RENDER_GIT_COMMIT ?? '',
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
        source: '/spaces/winters-playground',
        destination: '/spaces/embody',
        permanent: true,
      },
      {
        source: '/spaces/winters-playground/:path*',
        destination: '/spaces/embody/:path*',
        permanent: true,
      },

      // ── Legacy Wix URLs, ahead of the freshcollective.au cutover ──
      //
      // Only routes with a genuine successor appear here. The rest of
      // the old Wix site is deliberately retired and absent: a 404 is
      // the honest answer for a page that no longer exists, and
      // redirecting it to the homepage would claim an equivalence that
      // isn't there. See ``src/app/not-found.tsx``.
      //
      // ``permanent: true`` emits a 308, Next's canonical permanent
      // redirect. Query strings are carried over by the framework
      // without an explicit rule, so ``/embody?utm_source=book``
      // arrives at ``/spaces/embody/about?utm_source=book``.
      //
      // Lands on the About page rather than the Collective root. This
      // is the legacy public Wix URL, so whoever follows it is as
      // likely to be a stranger as a member, and About is the page that
      // reads correctly for both. The Collective root resolves to About
      // for a signed-out visitor anyway — pointing here just makes it
      // one hop instead of two, and keeps the landing stable if the
      // root's member-aware routing ever sends members elsewhere.
      {
        source: '/embody',
        destination: '/spaces/embody/about',
        permanent: true,
      },
    ]
  },
};

export default nextConfig;
