/**
 * Thin wrapper around fetch for backend API calls.
 * All calls include credentials so the fc_session cookie is sent and received.
 */

const API_URL =
  typeof window !== 'undefined'
    ? process.env.NEXT_PUBLIC_API_URL   // client-side
    : process.env.NEXT_PUBLIC_API_URL   // server-side (same value on localhost)

export function apiUrl(path: string): string {
  const base = (API_URL ?? 'http://localhost:8000').replace(/\/$/, '')
  return `${base}${path}`
}

export interface ApiError {
  detail: string | { msg: string; type: string }[]
}

export function extractErrorMessage(err: ApiError): string {
  if (typeof err.detail === 'string') return err.detail
  if (Array.isArray(err.detail)) {
    return err.detail.map((e) => e.msg).join(', ')
  }
  return 'Something went wrong. Please try again.'
}
