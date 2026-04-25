import { SignJWT, jwtVerify } from 'jose'
import { cookies } from 'next/headers'
import type { NextRequest } from 'next/server'

export const SESSION_COOKIE = 'fc_session'
const SEVEN_DAYS_SECONDS = 60 * 60 * 24 * 7

export interface SessionPayload {
  userId: string
  email: string
}

function getSecret(): Uint8Array {
  const secret = process.env.AUTH_SECRET
  if (!secret) throw new Error('AUTH_SECRET environment variable is not set')
  if (secret.length < 32) throw new Error('AUTH_SECRET must be at least 32 characters')
  return new TextEncoder().encode(secret)
}

export async function createSessionToken(payload: SessionPayload): Promise<string> {
  return new SignJWT({ userId: payload.userId, email: payload.email })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt()
    .setExpirationTime('7d')
    .sign(getSecret())
}

export async function verifySessionToken(token: string): Promise<SessionPayload | null> {
  try {
    const { payload } = await jwtVerify(token, getSecret())
    if (typeof payload.userId !== 'string' || typeof payload.email !== 'string') return null
    return { userId: payload.userId, email: payload.email }
  } catch {
    return null
  }
}

/** Read session in Server Components, Server Actions, and Route Handlers */
export async function getSession(): Promise<SessionPayload | null> {
  const cookieStore = await cookies()
  const token = cookieStore.get(SESSION_COOKIE)?.value
  if (!token) return null
  return verifySessionToken(token)
}

/** Read session inside Next.js middleware (uses request cookies, not next/headers) */
export async function getSessionFromRequest(request: NextRequest): Promise<SessionPayload | null> {
  const token = request.cookies.get(SESSION_COOKIE)?.value
  if (!token) return null
  return verifySessionToken(token)
}

/** Set the session cookie — only valid in Server Actions or Route Handlers */
export async function setSessionCookie(payload: SessionPayload): Promise<void> {
  const token = await createSessionToken(payload)
  const cookieStore = await cookies()
  cookieStore.set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: SEVEN_DAYS_SECONDS,
    path: '/',
  })
}

/** Clear the session cookie — only valid in Server Actions or Route Handlers */
export async function clearSessionCookie(): Promise<void> {
  const cookieStore = await cookies()
  cookieStore.delete(SESSION_COOKIE)
}
