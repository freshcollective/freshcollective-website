'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'

/**
 * PathwayAutoRevalidate — mounts silently and reissues `router.refresh()`
 * at the moment the next time-based step lock is due to open, without
 * polling and without a background job.
 *
 * The server is the authority: this component only decides *when* to
 * ask the server again. It never computes access itself.
 *
 * How it survives the awkward parts of browser timing:
 *
 *   1. `setTimeout` becomes unreliable past ~24 days (browsers clamp
 *      to a 32-bit int). We cap each tick at 2 hours and reschedule
 *      when the tick fires — so a lock 5 days out simply produces a
 *      2-hour timer that re-arms itself repeatedly.
 *
 *   2. Backgrounded tabs may pause or throttle timers. On `focus` or
 *      `visibilitychange → visible` we recompare the current time
 *      with the nearest known unlock and, if it has already passed,
 *      fire an immediate refresh. A tab that slept through the
 *      unlock will therefore catch up the moment the member returns.
 *
 * When `router.refresh()` runs, the parent server component re-renders
 * with fresh data. That means a step that just unlocked is now `OPEN`
 * without any manual reload.
 */

const MAX_TIMER_MS = 2 * 60 * 60 * 1000 // 2 hours per tick

interface Props {
  /** ISO-string list of every upcoming `unlocks_at` on this pathway.
   *  Pathway-level; we don't try to be per-step here. Null / past
   *  values are ignored. */
  upcomingUnlocks: (string | null | undefined)[]
}

export default function PathwayAutoRevalidate({ upcomingUnlocks }: Props) {
  const router = useRouter()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Freeze the input into a comparable key so the effect re-runs when
  // the set of upcoming unlocks changes (e.g. after a refresh replaces
  // the list). Empty string ⇒ nothing to schedule.
  const key = (upcomingUnlocks || [])
    .filter((s): s is string => typeof s === 'string' && !!s)
    .sort()
    .join('|')

  useEffect(() => {
    // Compute the soonest future unlock at effect-time. If none, do
    // nothing — we still register the focus/visibility listeners
    // because a lock might have been added elsewhere by the server
    // while we were away.
    const soonestFuture = (): number | null => {
      const now = Date.now()
      const times = (upcomingUnlocks || [])
        .map((s) => (s ? Date.parse(s) : NaN))
        .filter((t) => Number.isFinite(t) && t > now) as number[]
      if (times.length === 0) return null
      return Math.min(...times)
    }

    const clear = () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }

    const schedule = () => {
      clear()
      const target = soonestFuture()
      if (target === null) return
      const wait = Math.max(1000, Math.min(MAX_TIMER_MS, target - Date.now()))
      timerRef.current = setTimeout(() => {
        if (Date.now() >= target) {
          // Unlock time has arrived — server-authoritative refresh.
          router.refresh()
        } else {
          // We only slept a 2-hour chunk; wait some more.
          schedule()
        }
      }, wait)
    }

    // If a lock time already passed before we mounted (e.g. the page
    // came out of the browser's back/forward cache after the moment),
    // catch up immediately.
    const catchUpIfDue = () => {
      const now = Date.now()
      const passed = (upcomingUnlocks || [])
        .some((s) => s && Number.isFinite(Date.parse(s)) && Date.parse(s) <= now)
      if (passed) {
        router.refresh()
      } else {
        schedule()
      }
    }

    const onFocus = () => catchUpIfDue()
    const onVisibility = () => {
      if (document.visibilityState === 'visible') catchUpIfDue()
    }

    catchUpIfDue()
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      clear()
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // key intentionally drives re-run so that a new set of unlock
    // timestamps (typically after a refresh replaced the payload)
    // resets the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return null
}
