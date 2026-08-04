/**
 * Pure copy + dev-detail logic for the "checkout is unavailable"
 * state on /checkout/creator.
 *
 * The backend returns only a stable reason code (and optionally a
 * missing environment-variable name for development). The frontend
 * owns the human-facing wording so no operator-authored text ever
 * leaks to a visitor.
 *
 * Extracted from ``CreatorCheckoutButton.tsx`` so the copy and the
 * dev-mode gate can be unit-tested without a React runtime.
 */

/** Structured 503 body shape the backend returns for both
 *  ``stripe_not_configured`` and ``price_id_not_configured``. */
export interface UnavailableDetail {
  reason: string
  missing_env_var?: string | null
  would_create?: Record<string, unknown>
}

export interface UnavailableCopy {
  heading: string
  body: string
}

/**
 * Fixed, calm, environment-limit copy. Same for every ``reason``
 * value the backend may return today — the goal is that a visitor
 * reads it as "this environment isn't set up", not "your purchase
 * failed" and definitely not "here is a raw operator instruction".
 *
 * Do NOT branch on ``reason`` for the *main* message; that keeps
 * the copy stable and audit-safe against a future backend that
 * introduces new reason codes.
 */
export function getUnavailableCopy(): UnavailableCopy {
  return {
    heading: "Payments aren't available in this environment yet.",
    body:
      "Stripe hasn't been configured, so checkout can't begin. " +
      'No payment has been created and nothing has been charged.',
  }
}

/**
 * Optional secondary line for development-only builds. Returns null
 * (i.e. render nothing) when:
 *   - we're in a production build; or
 *   - the backend didn't supply a diagnostic env-var name.
 *
 * Never returns backend-authored prose. The only allowed content
 * shape is ``"Missing <ENV_VAR_NAME>"`` where the variable name has
 * already been validated by the backend as a fixed identifier.
 *
 * ``nodeEnv`` is a parameter so tests can drive both branches
 * without an environment monkey-patch; the default reads
 * ``process.env.NODE_ENV`` which Next.js substitutes at build time.
 */
export function getDevOnlyDetail(
  missingEnvVar: string | null | undefined,
  nodeEnv: string | undefined = process.env.NODE_ENV,
): string | null {
  if (nodeEnv === 'production') return null
  if (!missingEnvVar) return null
  return `Missing ${missingEnvVar}`
}
