/**
 * Routes that more than one surface needs to name.
 *
 * Small on purpose. This is not a routing abstraction — Next's file
 * system is already that — it is a home for the handful of paths that
 * get written out by hand in several places and then drift.
 *
 * `DASHBOARD_PATH` exists because exactly that happened: the member
 * dashboard is titled "Your World" and lives at `/dashboard`, and a
 * purchase confirmation shipped linking to `/your-world`, which has
 * never been a route. The name a thing is called and the path it lives
 * at are different facts, and writing the first where the second
 * belongs is an easy mistake to make twice.
 */

/** The member dashboard — titled "Your World". */
export const DASHBOARD_PATH = '/dashboard'
