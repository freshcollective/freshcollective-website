/**
 * Build-time Sentry options: private source maps, and nothing else.
 *
 * Phase 4B. Phases 1–3 deliberately avoided ``withSentryConfig`` — it
 * was measured as unnecessary for initialising the SDK, and a build
 * wrapper that is not needed is surface that is not warranted.
 * Uploading source maps is the one thing it genuinely owns.
 *
 * In its own module, rather than inline in ``next.config.ts``, for the
 * reason ``securityHeaders.ts`` already exists: ``next.config.ts`` uses
 * ``__dirname`` and cannot be imported under Node's
 * ``--experimental-strip-types`` loader, so anything that needs
 * asserting has to live outside it. What needs asserting here is that
 * the release the upload is filed under is the same string every event
 * carries.
 *
 * What this buys
 * --------------
 * A production browser stack frame currently reads
 * ``09ae.el~njpln.js:1:48213``. With maps uploaded it reads
 * ``src/app/creator-studio/offers/page.tsx:38``.
 *
 * How the maps stay private
 * -------------------------
 * This is the part that matters, and it is the SDK's behaviour rather
 * than our promise — traced through ``handleRunAfterProductionCompile``
 * in the installed package, then measured against a real build:
 *
 *   1. Turbopack generates client source maps during the build (142 of
 *      them, measured).
 *   2. After compilation, ``runAfterProductionCompile`` uploads them.
 *   3. ``deleteSourcemapsAfterUpload`` deletes every ``*.map`` under
 *      ``.next/static``.
 *   4. The SDK strips the ``//# sourceMappingURL=`` comments from the
 *      emitted JS, so a browser never asks for a file that has gone.
 *
 * All four happen inside ``next build``, so the image Render starts
 * contains no client maps at all: a chunk returns 200 and its ``.map``
 * returns 404. ``sentrySourceMaps.test.ts`` asserts that against the
 * built output rather than trusting this comment.
 *
 * ``.next/server`` maps are uploaded and deliberately *not* deleted.
 * Next never serves that directory, and keeping them is what makes a
 * server-component stack readable too.
 */

import type { SentryBuildOptions } from '@sentry/nextjs/config'

/** The Sentry project these maps belong to. */
export const SENTRY_PROJECT = 'fc-web'

/**
 * The release the upload is filed under.
 *
 * Read at call time rather than at module load so a test can set the
 * variable and see the effect — and so this is unambiguously the same
 * read that ``sentryRelease()`` performs for events.
 */
export function sentryUploadRelease(): string | undefined {
  return (process.env.RENDER_GIT_COMMIT || '').trim() || undefined
}

/**
 * Everything ``withSentryConfig`` is given, and nothing more.
 *
 * Every option here is either required for the upload or is turning off
 * something the SDK would otherwise switch on. There is nothing
 * optional in this object.
 */
export function sentryBuildOptions(): SentryBuildOptions {
  return {
    /**
     * A stable fact about the product, so it belongs in source rather
     * than in a variable someone could mistype — the same reasoning as
     * ``R2_BUCKET_PRIVATE`` in render.yaml.
     */
    project: SENTRY_PROJECT,

    /**
     * Not a secret, but not knowable from this repository either: the
     * DSN carries the numeric org id, not the slug. So it is
     * operator-supplied, and absent locally.
     */
    org: process.env.SENTRY_ORG,

    /**
     * ``SENTRY_AUTH_TOKEN`` is deliberately *not* read here. The
     * bundler plugin reads it from the build environment itself, which
     * means the one real secret in this phase is never named as a read
     * anywhere in our source — the strongest form of "it cannot reach
     * the browser". It is needed at build time only: nothing at runtime
     * uses it, and revoking it after a deploy stops future uploads and
     * affects nothing else. Measured: with a bad token the build still
     * exits 0 and logs the failure, so a rotated token degrades
     * symbolication and never availability.
     */

    /**
     * The release, pinned to the same string every event carries.
     *
     * Left to itself the plugin resolves a release from
     * ``SENTRY_RELEASE`` or by shelling out to git — which on Render
     * would *probably* produce this same commit, and probably is not
     * good enough to hang symbolication on. Events take their release
     * from ``RENDER_GIT_COMMIT`` (see ``sentryRelease()``), so the
     * upload is given exactly that: full SHA, one naming scheme.
     *
     * Absent locally, which leaves the plugin's own detection in place
     * — harmless, because without an auth token nothing is uploaded.
     */
    release: { name: sentryUploadRelease() },

    /**
     * Stated rather than inherited. The SDK defaults this to ``true``
     * for Turbopack builds and this phase depends on it being true, so
     * it is written where someone reading the config can see it.
     */
    sourcemaps: { deleteSourcemapsAfterUpload: true },

    /**
     * Build-time instrumentation of server dependencies exists to
     * create spans. Tracing is off, so it would patch modules to
     * produce nothing.
     */
    buildTimeInstrumentation: false,

    /**
     * The route manifest gives transactions parameterised names — a
     * tracing feature — and injecting it would put the full route list,
     * admin and creator routes included, into the public client bundle.
     * Off keeps this build's output as it was before Phase 4B.
     */
    routeManifestInjection: false,

    /** Nothing about our build needs reporting to Sentry. */
    telemetry: false,

    /**
     * The SDK otherwise prints "ACTION REQUIRED: export an
     * `onRouterTransitionStart` hook" on every build. That hook
     * instruments *navigations* — tracing — which this phase does not
     * enable, so the message is noise that would outlive anyone's
     * memory of why it is safe to ignore.
     */
    suppressOnRouterTransitionStartWarning: true,
  }
}

/**
 * The one thing ``withSentryConfig`` does that has to be undone.
 *
 * It sets ``experimental.clientTraceMetadata = ['baggage',
 * 'sentry-trace']`` unconditionally, with no option to decline. That is
 * not inert: measured against a real served build, every HTML response
 * then carries
 *
 *     <meta name="sentry-trace" content="…-…-0">
 *     <meta name="baggage" content="sentry-environment=production,…">
 *
 * which is pageload-tracing plumbing this phase does not enable, and
 * output that did not exist before it. Removing the key restores the
 * previous HTML exactly. Nothing error-related reads it.
 */
export function withoutTraceMetadata<
  T extends { experimental?: Record<string, unknown> },
>(config: T): T {
  if (config.experimental) delete config.experimental.clientTraceMetadata
  return config
}
