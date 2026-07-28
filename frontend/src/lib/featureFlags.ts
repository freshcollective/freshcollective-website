/**
 * Feature-flag exposure to the Next.js layer.
 *
 * The backend is the source of truth for what a flag means — this
 * module just mirrors the on/off state into the frontend so nav and
 * pages can be gated symmetrically. When Discovery is off, the
 * placeholder routes 404 and the nav entries don't render.
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
