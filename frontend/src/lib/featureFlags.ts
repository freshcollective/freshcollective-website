/**
 * Feature-flag exposure to the Next.js layer.
 *
 * The backend is the source of truth for what a flag means — this
 * module just mirrors the on/off state into the frontend so nav and
 * pages can be gated symmetrically. When a flag is off, its route
 * 404s and its nav entries don't render.
 *
 * Two flags, one per surface — see each function for why they are
 * separate.
 *
 * The env var is read via ``process.env.NEXT_PUBLIC_*`` so Next.js
 * inlines it at build time; that means flipping the flag requires a
 * rebuild + redeploy on Vercel, which is the desired grain of
 * control for a whole-pillar toggle.
 *
 * Set ``NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED=true`` in the
 * environment (locally in ``frontend/.env``, in Vercel project env)
 * to turn the pillar on. Any other value — or omission — is treated
 * as off.
 */

export function isDiscoveryPillarEnabled(): boolean {
  return process.env.NEXT_PUBLIC_DISCOVERY_PILLAR_ENABLED === 'true'
}

/**
 * Ways to Connect, gated separately from Discover Places.
 *
 * The two shipped behind one flag because they were built as one
 * pillar. They are not ready at the same time: Discover Places is
 * backed by a real catalogue, while Ways to Connect is an honest
 * empty state waiting on a recommendation service. Turning the
 * pillar on to launch the first would have published the second as
 * a side effect.
 *
 * Deliberately a sibling function rather than a flag registry — two
 * booleans do not need a framework, and the one thing that matters
 * is that each surface names the flag it actually depends on.
 *
 * Same build-time semantics as its sibling: ``NEXT_PUBLIC_*`` is
 * inlined by Next.js, so changing it needs a rebuild, not a restart.
 * Any value other than ``'true'`` — including omission — is off.
 */
export function isWaysToConnectEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WAYS_TO_CONNECT_ENABLED === 'true'
}
