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
