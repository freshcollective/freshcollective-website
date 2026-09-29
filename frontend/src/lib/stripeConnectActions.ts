/**
 * The Stripe Connect request sequences, separated from the React panel.
 *
 * Kept here so the ordering rules are unit-testable: which endpoints are
 * called, in which order, and which are *not* called. Those are the parts
 * that would break quietly — a component that creates a second account, or
 * reuses a link, still renders perfectly well.
 *
 * Every function takes its transport as an argument. The panel passes a
 * real ``fetch``-backed poster; tests pass a recorder.
 */

import type { CreatorStripeConnectStatus } from '@/types/platform'

/** Minimal transport: POST/GET a path, resolve parsed JSON, reject on failure. */
export interface ConnectTransport {
  post<T>(path: string): Promise<T>
  get<T>(path: string): Promise<T>
}

export const ACCOUNT_PATH = '/api/creator/stripe-connect/account'
export const LINK_PATH = '/api/creator/stripe-connect/onboarding-link'
export const STATUS_PATH = '/api/creator/stripe-connect/status'
export const REFRESH_PATH = '/api/creator/stripe-connect/refresh'

export interface AccountLinkResponse {
  url: string
  expires_in_seconds: number
}

export function loadStatus(
  t: ConnectTransport,
): Promise<CreatorStripeConnectStatus> {
  return t.get<CreatorStripeConnectStatus>(STATUS_PATH)
}

export function refreshStatus(
  t: ConnectTransport,
): Promise<CreatorStripeConnectStatus> {
  return t.post<CreatorStripeConnectStatus>(REFRESH_PATH)
}

/**
 * Mint a link and hand back its URL.
 *
 * Never stored, never cached, never reused: the backend mints a fresh one
 * per call because Stripe expires them five minutes after creation, so a
 * remembered URL is usually dead by the time anyone clicks it.
 */
export async function mintOnboardingUrl(t: ConnectTransport): Promise<string> {
  const { url } = await t.post<AccountLinkResponse>(LINK_PATH)
  if (!url) throw new Error('Stripe did not return a setup link.')
  return url
}

/**
 * First-time connect: create the account, then get a link for it.
 *
 * The order matters and the account call must come first — there is no
 * account to link to otherwise. It is safe to repeat: the endpoint is
 * idempotent per creator and mode, so a double submission returns the
 * existing account rather than creating a second one.
 */
export async function startConnect(t: ConnectTransport): Promise<string> {
  await t.post<CreatorStripeConnectStatus>(ACCOUNT_PATH)
  return mintOnboardingUrl(t)
}

/**
 * Resume an existing setup: link only.
 *
 * Deliberately skips ``/account``. The account already exists, and calling
 * it again would be a pointless round trip on the path a creator retries
 * most often.
 */
export function continueConnect(t: ConnectTransport): Promise<string> {
  return mintOnboardingUrl(t)
}

/**
 * Which sequence a given state needs.
 *
 * Reads the backend's own state rather than inferring from whether an
 * account id happens to be present.
 */
export function sequenceFor(
  state: CreatorStripeConnectStatus['state'],
): 'start' | 'continue' | 'none' {
  if (state === 'not_started') return 'start'
  if (state === 'onboarding' || state === 'action_required' || state === 'transfers_only') {
    return 'continue'
  }
  return 'none'
}
