import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    root: __dirname,
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
