import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    root: __dirname,
  },

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
