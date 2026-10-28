/**
 * Labels shared by the public navigation surfaces.
 *
 * ``PublicHeader`` and ``MobileNav`` each carry their own copy of
 * ``peerNavItems``, and neither can import from the other —
 * ``PublicHeader`` renders ``MobileNav``, so the dependency only runs
 * one way. A neutral module is the only place all three surfaces plus
 * the footer can agree.
 */

/**
 * The signup button, everywhere a visitor meets it in navigation.
 *
 * "Join" on its own read as an invitation to join something in
 * particular — a Collective — when the button goes to Fresh
 * Collective account registration. The mobile drawer had said the
 * whole thing for a while and the desktop header and footer had not;
 * this is what stops the three drifting apart again.
 *
 * Not for the contextual signup links inside a purchase or an
 * invitation. Those say "Create account to continue", which is right:
 * that visitor has already found a Collective, and telling them to
 * join Fresh Collective would describe the wrong step.
 */
export const PUBLIC_JOIN_LABEL = 'Join Fresh Collective'
