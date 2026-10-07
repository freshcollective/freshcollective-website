/**
 * One set of Sentry options, shared by the browser and the Node runtime.
 *
 * fc-web reports from two places — the member's browser and the Node
 * process rendering their pages — and they are two different SDKs with
 * one set of rules. Keeping the options here rather than duplicating
 * them in each init file means a privacy decision cannot end up applied
 * on one side only, which is the failure mode worth designing against:
 * it would look fine in every test that checks the strict side.
 *
 * Imports nothing from Sentry, so ``src/lib/sentryRuntime.test.ts`` can
 * assert on the real options object under ``node --test``, and the
 * module costs the client bundle nothing but the object itself.
 */

import type { Breadcrumb, ErrorEvent } from '@sentry/nextjs'

import type { LooseBreadcrumb, LooseEvent } from './sentryPrivacy.ts'
import { scrubBreadcrumb, scrubEvent, SENSITIVE_QUERY_PARAMS } from './sentryPrivacy.ts'

/**
 * The one DSN variable, read by both runtimes.
 *
 * ``NEXT_PUBLIC_SENTRY_DSN`` and nothing else. A DSN is a public
 * submission endpoint — it has to reach the browser to be any use
 * there — so a second server-only ``SENTRY_DSN`` holding the identical
 * value would buy no secrecy and would introduce the one thing worth
 * avoiding: two places to rotate, and no error if they disagree.
 *
 * Next inlines ``NEXT_PUBLIC_*`` into the client bundle at build time
 * and Render also supplies it to the running server, so one variable
 * genuinely covers both. The cost is that rotating it needs a rebuild
 * of fc-web rather than a restart — the same contract as the
 * ``NEXT_PUBLIC_*`` feature flags already declared in render.yaml.
 */
export function sentryDsn(): string {
  return (process.env.NEXT_PUBLIC_SENTRY_DSN ?? '').trim()
}

/**
 * Derived from ``NODE_ENV``, not declared.
 *
 * fc-web has no ``APP_ENV`` of its own and does not need one: Render
 * builds and starts it with ``NODE_ENV=production``, and a local
 * ``next dev`` is development by construction. A separate
 * ``SENTRY_ENVIRONMENT`` could only ever drift from this.
 */
export function sentryEnvironment(): string {
  return process.env.NODE_ENV === 'production' ? 'production' : 'development'
}

/**
 * The deploy's commit, or nothing.
 *
 * The server reads Render's ``RENDER_GIT_COMMIT`` directly. The browser
 * cannot — it is not a ``NEXT_PUBLIC_*`` variable, so it is absent from
 * the client bundle — which is why ``next.config.ts`` maps the same
 * value into ``NEXT_PUBLIC_RELEASE_COMMIT`` at build time. One source,
 * two readers, no second variable for anyone to set.
 *
 * Absent means ``undefined``, never a placeholder: "unknown" looks like
 * a version and groups every deploy together.
 */
export function sentryRelease(): string | undefined {
  const commit = (
    process.env.NEXT_PUBLIC_RELEASE_COMMIT ||
    process.env.RENDER_GIT_COMMIT ||
    ''
  ).trim()
  return commit || undefined
}

/**
 * The integrations this phase wants, named.
 *
 * An allowlist rather than a denylist, and that is a measured decision
 * rather than a preference. ``@sentry/nextjs``'s server ``init``
 * resolves **fifty-odd** default integrations, nearly all of them
 * auto-instrumentation: Postgres, Mongo, Prisma, Redis, Kafka, Express,
 * and — with the brief explicitly ruling AI instrumentation out —
 * OpenAI, Anthropic_AI, LangChain, LangGraph, VercelAI, Mistral, Groq,
 * Google_GenAI and more. They produce no data with tracing off, but
 * each one patches modules at startup, and a denylist written against
 * that list would be out of date by the next minor release.
 *
 * So the question this answers is "what does error monitoring need",
 * and the list is short:
 *
 *   caught by           GlobalHandlers, BrowserApiErrors,
 *                       OnUncaughtException, OnUnhandledRejection,
 *                       ChildProcess, WorkerThreads, NodeSystemError
 *   described by        ContextLines, Context, Modules, CultureContext,
 *                       HttpContext, RequestData, LinkedErrors,
 *                       NextjsClientStackFrameNormalization
 *   given a trail by    Breadcrumbs, Console, Http, NodeFetch
 *   filtered by         EventFilters, Dedupe, FunctionToString
 *
 * The cost of an allowlist, met once already: this list was written
 * against the **server**'s resolved integrations, and the browser's
 * differs. ``NextjsClientStackFrameNormalization`` is browser-only, is
 * pure error monitoring — it rewrites stack-frame filenames to
 * ``app:///_next/…`` and marks framework chunks ``in_app: false`` —
 * and was excluded by oversight rather than by decision.
 * ``sentryBrowserPipeline.test.ts`` now pins the browser's resolved set
 * the way the server's has been pinned all along, so the next such
 * difference fails a test.
 *
 * ``Http`` and ``NodeFetch`` are tracing instrumentations in name, but
 * with tracing off what they contribute is the breadcrumb that says
 * which call to fc-api failed just before the error — which is often
 * the whole answer.
 *
 * The cost of an allowlist is losing a future enhancement until someone
 * adds it here. The cost of a denylist is shipping a product we said we
 * would not ship. ``sentryPipeline.test.ts`` asserts the resolved set
 * against this list, so an SDK upgrade that adds a default fails a test
 * rather than arriving in production.
 */
export const ERROR_MONITORING_INTEGRATIONS: readonly string[] = [
  'Breadcrumbs',
  'BrowserApiErrors',
  'ChildProcess',
  'Console',
  'Context',
  'ContextLines',
  'CultureContext',
  'Dedupe',
  'EventFilters',
  'FunctionToString',
  'GlobalHandlers',
  'Http',
  'HttpContext',
  'LinkedErrors',
  'Modules',
  // Browser-only, from @sentry/nextjs itself: stack-frame filenames
  // normalised to ``app:///_next/…``, framework chunks marked not-ours.
  // Collects nothing and sends nothing of its own.
  'NextjsClientStackFrameNormalization',
  'NodeFetch',
  'NodeSystemError',
  'OnUncaughtException',
  'OnUnhandledRejection',
  'RequestData',
  'WorkerThreads',
]

/**
 * Integrations the SDK installs regardless of the filter.
 *
 * ``SpanStreaming`` is added by the client itself, after the
 * ``integrations`` callback has had its say — filtering it out does not
 * remove it. It is the transport for streamed spans, and with
 * ``tracesSampleRate: 0`` there are none: measured, not assumed, by the
 * test that starts a span and asserts no envelope follows.
 *
 * Named here so the allowlist test can permit exactly this and nothing
 * else, instead of being loosened to a contains-check that would hide
 * the next addition.
 */
export const SDK_FORCED_INTEGRATIONS: readonly string[] = ['SpanStreaming']

export function isErrorMonitoringIntegration(name: string): boolean {
  return ERROR_MONITORING_INTEGRATIONS.includes(name)
}

export function keepOnlyErrorMonitoring<T extends { name: string }>(
  integrations: T[],
): T[] {
  return integrations.filter((i) => isErrorMonitoringIntegration(i.name))
}

/**
 * What the SDK is allowed to collect, stated field by field.
 *
 * **This block is the single most important thing in the frontend
 * integration, and the reason it is not simply ``sendDefaultPii:
 * false``.** That option does not exist in SDK v11 — it was replaced by
 * ``dataCollection``, and every field of ``dataCollection`` defaults to
 * *collecting*: ``userInfo: true``, ``cookies: true``, ``httpHeaders:
 * true``, every ``httpBodies`` target, and ``stackFrameVariables:
 * true``. An SDK initialised without this block would send member
 * cookies, the session header, request bodies and the local variables
 * of whatever function threw — in a minified bundle, under names
 * nothing could denylist.
 *
 * So every field is set explicitly, including the ones whose
 * restrictive value happens to be the one we want, because an omitted
 * field here does not mean "default" — it means "collect it".
 */
export const SENTRY_DATA_COLLECTION = {
  /** No ``user.*`` enrichment: no address, no username, no IP. */
  userInfo: false,
  /** The session cookie lives on this origin. */
  cookies: false,
  /** Neither direction. Nothing in a header is worth the risk here. */
  httpHeaders: { request: false, response: false },
  /** No bodies: a reset POST is a token, a Conversation POST is prose. */
  httpBodies: [],
  /**
   * Query parameters are *filtered*, not dropped. ``?tab=settings`` is
   * real debugging context and ``/reset-password`` without its query
   * is still the page that broke — so the credential-bearing names go
   * and the rest stay. ``scrubEvent`` is the second, independent layer
   * over the same names.
   */
  urlQueryParams: { deny: [...SENSITIVE_QUERY_PARAMS] },
  /** No GraphQL in this app; stated so a future integration cannot opt in. */
  graphQL: { document: false, variables: false },
  /** No AI instrumentation in this phase. */
  genAI: { inputs: false, outputs: false },
  /** fc-web talks to fc-api, not to a database — stated anyway. */
  databaseQueryData: false,
  queues: false,
  /** Frame locals. The one default most likely to carry a raw token. */
  stackFrameVariables: false,
  /**
   * Our own source lines around a frame — not member data, and the
   * difference between a readable stack and a line number. Kept at the
   * SDK default deliberately rather than by omission.
   */
  frameContextLines: 5,
}

/**
 * The two privacy hooks, adapted to the SDK's types.
 *
 * ``sentryPrivacy`` describes events structurally and imports nothing,
 * which is what lets it run in both runtimes and be tested without an
 * SDK or a DOM. The SDK's own ``ErrorEvent`` and ``Breadcrumb`` are
 * stricter than those shapes in ways that have no bearing on scrubbing
 * — an index signature, a narrower ``Exception`` — so the two casts
 * live here, at the one boundary, rather than being worked around
 * inside the scrubber.
 *
 * Type-only imports above: erased at build, so the client bundle and
 * the ``node --test`` runner both see a module with no SDK dependency.
 */
const beforeSend = (event: ErrorEvent): ErrorEvent | null =>
  scrubEvent(event as unknown as LooseEvent) as unknown as ErrorEvent | null

const beforeBreadcrumb = (crumb: Breadcrumb): Breadcrumb | null =>
  scrubBreadcrumb(crumb as unknown as LooseBreadcrumb) as unknown as Breadcrumb | null

/**
 * Options both runtimes share.
 *
 * The four ``beforeSend*`` hooks that return ``null`` are how "error
 * monitoring only" becomes structural instead of configured: even if
 * something in the SDK or in a future dependency starts a transaction,
 * emits a log or records a metric, the envelope is dropped in-process.
 * ``tracesSampleRate: 0`` says the same thing one layer earlier.
 */
export const SHARED_SENTRY_OPTIONS = {
  environment: sentryEnvironment(),
  release: sentryRelease(),
  dataCollection: SENTRY_DATA_COLLECTION,

  // --- errors only -----------------------------------------------------
  //
  // Three independent layers, because one of them is a number someone
  // could plausibly change:
  //
  //   tracesSampleRate  nothing is sampled, so no span is recorded
  //   ignoreSpans       and if one were, every span matches this and is
  //                     dropped before it can be sent
  //   beforeSendLog     the logs and metrics products, refused at the
  //   beforeSendMetric  envelope
  //
  // ``beforeSendTransaction`` is deliberately absent: v11 streams spans
  // by default and ignores that hook — it also logs a warning on every
  // boot saying so, which is how this was found.
  tracesSampleRate: 0,
  ignoreSpans: [/.*/],
  beforeSendLog: () => null,
  beforeSendMetric: () => null,

  // --- privacy ---------------------------------------------------------
  beforeSend,
  beforeBreadcrumb,

  /**
   * Breadcrumbs are the most useful thing a browser issue carries and
   * the most likely place for something unintended, so the trail is
   * kept short on purpose. Fifty navigations ago is not diagnostic.
   */
  maxBreadcrumbs: 30,
}
