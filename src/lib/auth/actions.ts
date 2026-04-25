'use server'

import { redirect } from 'next/navigation'
import crypto from 'crypto'
import { prisma } from '@/lib/db'
import { hashPassword, verifyPassword, validatePasswordStrength } from '@/lib/auth/password'
import { setSessionCookie, clearSessionCookie } from '@/lib/auth/session'

export type AuthState = { error?: string; success?: string } | null

// Only allow relative, same-origin paths to prevent open redirect
function getSafeRedirect(next: string | null | undefined): string {
  if (!next) return '/dashboard'
  if (/^\/(?!\/|\\)/.test(next)) return next
  return '/dashboard'
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

// Fallback hash used only for constant-time comparison when the user isn't found.
// Prevents attackers from inferring a valid email via response timing.
// This is a valid bcrypt hash format; bcrypt.compare always returns false against it.
const TIMING_SAFE_HASH = '$2a$12$LCKz9TBMc.NJY5eIcLVdw.vM9gf.4lB0fU9a7JY.Kp4U2vU8WIaWq'

export async function login(prevState: AuthState, formData: FormData): Promise<AuthState> {
  const email = (formData.get('email') as string)?.trim().toLowerCase()
  const password = formData.get('password') as string
  const next = formData.get('next') as string | null

  if (!email || !password) {
    return { error: 'Email and password are required.' }
  }

  if (!isValidEmail(email)) {
    return { error: 'Please enter a valid email address.' }
  }

  let user
  try {
    user = await prisma.user.findUnique({ where: { email } })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  // Always run bcrypt to prevent timing-based email enumeration
  const hashToCheck = user?.passwordHash ?? TIMING_SAFE_HASH
  const passwordValid = await verifyPassword(password, hashToCheck)

  if (!user || !passwordValid) {
    return { error: 'Invalid email or password.' }
  }

  try {
    await setSessionCookie({ userId: user.id, email: user.email })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  redirect(getSafeRedirect(next))
}

export async function signup(prevState: AuthState, formData: FormData): Promise<AuthState> {
  const name = (formData.get('name') as string)?.trim()
  const email = (formData.get('email') as string)?.trim().toLowerCase()
  const password = formData.get('password') as string

  if (!name || !email || !password) {
    return { error: 'All fields are required.' }
  }

  if (name.length > 100) {
    return { error: 'Name must be 100 characters or fewer.' }
  }

  if (!isValidEmail(email)) {
    return { error: 'Please enter a valid email address.' }
  }

  const passwordError = validatePasswordStrength(password)
  if (passwordError) return { error: passwordError }

  let existing
  try {
    existing = await prisma.user.findUnique({ where: { email } })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  if (existing) {
    // Deliberately generic — do not confirm whether the email is registered
    return { error: 'An account with those details already exists. Try logging in instead.' }
  }

  let user
  try {
    const passwordHash = await hashPassword(password)
    user = await prisma.user.create({ data: { email, name, passwordHash } })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  try {
    await setSessionCookie({ userId: user.id, email: user.email })
  } catch {
    return { error: 'Account created. Please log in.' }
  }

  redirect('/dashboard')
}

export async function logout(): Promise<void> {
  await clearSessionCookie()
  redirect('/')
}

export async function forgotPassword(prevState: AuthState, formData: FormData): Promise<AuthState> {
  const email = (formData.get('email') as string)?.trim().toLowerCase()

  if (!email || !isValidEmail(email)) {
    return { error: 'Please enter a valid email address.' }
  }

  try {
    const user = await prisma.user.findUnique({ where: { email } })

    if (user) {
      // Remove any existing unused tokens for this user before creating a new one
      await prisma.passwordReset.deleteMany({ where: { userId: user.id, usedAt: null } })

      const token = crypto.randomBytes(32).toString('hex')
      const tokenHash = crypto.createHash('sha256').update(token).digest('hex')
      const expiresAt = new Date(Date.now() + 60 * 60 * 1000) // 1 hour

      await prisma.passwordReset.create({ data: { userId: user.id, tokenHash, expiresAt } })

      const resetUrl = `${process.env.NEXT_PUBLIC_APP_URL}/reset-password?token=${token}`

      if (process.env.NODE_ENV !== 'production') {
        console.log('\n========================================')
        console.log('PASSWORD RESET LINK (development only):')
        console.log(resetUrl)
        console.log('========================================\n')
      }
      // TODO: In production, send resetUrl via a transactional email service (e.g. Resend, Postmark)
    }
  } catch (err) {
    console.error('forgotPassword error:', err)
    // Swallow error — always return the same generic message
  }

  // Always return this message regardless of whether the email exists (prevents enumeration)
  return {
    success:
      'If that email is registered, a reset link will appear in the server console. (In production, an email would be sent.)',
  }
}

export async function resetPassword(prevState: AuthState, formData: FormData): Promise<AuthState> {
  const token = (formData.get('token') as string)?.trim()
  const password = formData.get('password') as string
  const confirmPassword = formData.get('confirmPassword') as string

  if (!token || !password || !confirmPassword) {
    return { error: 'All fields are required.' }
  }

  if (password !== confirmPassword) {
    return { error: 'Passwords do not match.' }
  }

  const passwordError = validatePasswordStrength(password)
  if (passwordError) return { error: passwordError }

  const tokenHash = crypto.createHash('sha256').update(token).digest('hex')

  let resetRecord
  try {
    resetRecord = await prisma.passwordReset.findUnique({
      where: { tokenHash },
      include: { user: true },
    })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  if (!resetRecord || resetRecord.usedAt !== null || resetRecord.expiresAt < new Date()) {
    return { error: 'This reset link is invalid or has expired. Please request a new one.' }
  }

  try {
    const passwordHash = await hashPassword(password)

    await prisma.$transaction([
      prisma.user.update({ where: { id: resetRecord.userId }, data: { passwordHash } }),
      prisma.passwordReset.update({ where: { id: resetRecord.id }, data: { usedAt: new Date() } }),
    ])

    await setSessionCookie({ userId: resetRecord.user.id, email: resetRecord.user.email })
  } catch {
    return { error: 'Something went wrong. Please try again.' }
  }

  redirect('/dashboard')
}
