/**
 * Minimal JWT verification used by proxy.ts (server-side route protection only).
 * Never imported by client components.
 */
import { jwtVerify } from 'jose'

export const SESSION_COOKIE = 'fc_session'

function getSecret(): Uint8Array {
  const s = process.env.AUTH_SECRET
  if (!s) throw new Error('AUTH_SECRET is not set')
  return new TextEncoder().encode(s)
}

export async function verifySessionToken(token: string): Promise<boolean> {
  try {
    await jwtVerify(token, getSecret())
    return true
  } catch {
    return false
  }
}
