import { describe, it } from 'node:test'
import assert from 'node:assert/strict'

import {
  notificationDestination,
  notificationLabel,
  notificationTint,
} from './notifications.ts'
import type { NotificationItem } from '../types/platform.ts'

// Minimal builder — keeps each test focused on the field under test.
function build(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 'n_1',
    notification_type: 'event_registration',
    title: 'New event booking',
    message: 'Someone booked a spot.',
    url: null,
    is_read: false,
    created_at: '2026-08-09T00:00:00Z',
    email_sent_at: null,
    ...overrides,
  } as NotificationItem
}

describe('notificationDestination', () => {
  it('returns the stored url when present', () => {
    const n = build({
      url: '/creator/spaces/embody/events/ev_abc',
    })
    assert.equal(
      notificationDestination(n),
      '/creator/spaces/embody/events/ev_abc',
    )
  })

  it('returns the stored url even for booker confirmation', () => {
    const n = build({
      notification_type: 'booking_confirmed',
      url: '/spaces/embody/events/ev_abc',
    })
    assert.equal(notificationDestination(n), '/spaces/embody/events/ev_abc')
  })

  it('falls back to /dashboard for gathering notifications with no url', () => {
    // Legacy rows (created before the notif_url fix) still land somewhere
    // sensible instead of a dead click.
    const n = build({
      notification_type: 'event_registration',
      url: null,
    })
    assert.equal(notificationDestination(n), '/dashboard')
  })

  it('treats whitespace-only url as unset', () => {
    const n = build({ url: '   ' })
    assert.equal(notificationDestination(n), '/dashboard')
  })

  it('falls back to /creator-studio for plan notifications with no url', () => {
    const n = build({
      notification_type: 'creator_plan_granted_by_platform',
      url: null,
    })
    assert.equal(notificationDestination(n), '/creator-studio')
  })

  it('falls back to /notifications for unknown update types', () => {
    const n = build({
      notification_type: 'made_up_never_seen',
      url: null,
    })
    assert.equal(notificationDestination(n), '/notifications')
  })

  it('falls back to /notifications for community_care events (moderation family)', () => {
    const n = build({
      notification_type: 'community_care_case_opened',
      url: null,
    })
    assert.equal(notificationDestination(n), '/notifications')
  })
})

describe('notificationLabel', () => {
  it('returns the short human label for known types', () => {
    assert.equal(notificationLabel('event_registration'), 'Booking')
    assert.equal(notificationLabel('booking_confirmed'), 'Booking')
    assert.equal(notificationLabel('comment_reply'), 'Reply')
  })

  it('never leaks the raw type string for unknown types', () => {
    // The label should be human-friendly, not the internal identifier.
    const label = notificationLabel('some_new_backend_thing_v3')
    assert.notEqual(label, 'some_new_backend_thing_v3')
    assert.equal(label, 'Update')
  })
})

describe('notificationTint', () => {
  it('groups the two booking notification types under one tint', () => {
    // Creator-side + booker-side booking notifications should look the
    // same in the tray — same category, same colour.
    const a = notificationTint('event_registration')
    const b = notificationTint('booking_confirmed')
    assert.deepEqual(a, b)
  })
})

describe('the Communications Layer gathering notifications (FC-209)', () => {
  // Four types the comms layer sends were never in TYPE_MAP, so each
  // showed as a generic "Update" outside the Gatherings category. The
  // fifth is new. Grouped here because a member scanning the tray
  // should find all five under Gatherings.
  const GATHERING_TYPES = [
    'gathering_reminder_24h',
    'multi_booking_confirmed',
    'gathering_published',
    'series_published',
    'gathering_recurrence_published',
  ]

  for (const type of GATHERING_TYPES) {
    it(`${type} is a Gathering, not a generic update`, () => {
      assert.notEqual(notificationLabel(type), 'Update')
      // Same tint as a booking, which is the category's own.
      assert.deepEqual(
        notificationTint(type), notificationTint('booking_confirmed'),
      )
    })
  }

  it('a recurring schedule reads as dates, not as a series', () => {
    // The product distinction FC-209 exists to preserve: a recurrence
    // is a run of independent Gatherings, a Series is a package.
    assert.equal(notificationLabel('gathering_recurrence_published'), 'New dates')
    assert.equal(notificationLabel('series_published'), 'New series')
  })
})


/**
 * Stage 5A.4b — the membership notification that went nowhere.
 *
 * The in-app templates stored no ``url``, so ``notificationDestination``
 * fell through to the category default. The six membership types were
 * not in the type map either, so they resolved to ``update`` — whose
 * destination is ``/notifications``. Tapping one navigated to the page
 * the member was already looking at, which reads as nothing happening.
 */
describe('Collective membership notifications navigate', () => {
  const TYPES = [
    'collective_membership_purchased',
    'collective_membership_renewed',
    'collective_membership_payment_failed',
    'collective_membership_cancellation_scheduled',
    'collective_membership_ended',
    'collective_membership_reactivated',
  ]

  it('never sends a membership notification to /notifications', () => {
    // The exact symptom: a destination equal to the page it is on.
    for (const notification_type of TYPES) {
      const dest = notificationDestination(build({ notification_type }))
      assert.notEqual(dest, '/notifications', notification_type)
      assert.ok(dest && dest.length > 0, notification_type)
    }
  })

  it('falls back to the membership page when no url was stored', () => {
    // This is what makes the already-delivered notification work
    // without rewriting a production row.
    for (const notification_type of TYPES) {
      assert.equal(
        notificationDestination(build({ notification_type, url: null })),
        '/settings/membership',
        notification_type,
      )
    }
  })

  it('a stored url always wins over the fallback', () => {
    // New notifications carry the per-event destination from the
    // backend — the Collective for purchased and reactivated.
    assert.equal(
      notificationDestination(build({
        notification_type: 'collective_membership_purchased',
        url: 'https://freshcollective.au/spaces/toms-test-collective',
      })),
      'https://freshcollective.au/spaces/toms-test-collective',
    )
  })

  it('each type is labelled and tinted rather than reading as Update', () => {
    for (const notification_type of TYPES) {
      assert.equal(notificationLabel(notification_type), 'Membership', notification_type)
      const tint = notificationTint(notification_type)
      assert.ok(tint.bg && tint.fg && tint.icon, notification_type)
    }
  })

  it('no other notification type changed destination', () => {
    assert.equal(notificationDestination(build({
      notification_type: 'event_registration', url: null,
    })), '/dashboard')
    assert.equal(notificationDestination(build({
      notification_type: 'unknown_future_type', url: null,
    })), '/notifications')
  })
})
