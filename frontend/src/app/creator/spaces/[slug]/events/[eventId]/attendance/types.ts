/**
 * Wire types for the attendance dashboard endpoint. Mirrors the
 * Pydantic response models in ``app/creator/attendance.py`` — keep in
 * sync when either side changes.
 */

export type AttendanceStatus = 'attended' | 'absent' | 'booked'
export type AttendanceSource = 'manual' | 'auto' | null

export interface AttendanceEvent {
  id: string
  title: string
  description: string | null
  starts_at: string
  ends_at: string | null
  attendance_format: 'online' | 'in_person' | 'hybrid'
  venue_name: string | null
  venue_locality: string | null
  venue_address: string | null
  location_url: string | null
  capacity: number | null
  thumbnail_url: string | null
  status: string
  is_published: boolean
  space_slug: string
  space_name: string
  attendance_completed_at: string | null
  attendance_completed_by: string | null
}

export interface AttendanceRow {
  booking_id: string
  user_id: string
  name: string | null
  email: string
  attendance_status: AttendanceStatus
  attendance_source: AttendanceSource
  attendance_marked_at: string | null
  booking_reference: string
  booked_at: string
  ticket_label: string
  payment_label: string
  booking_note: string | null
  pending_post_completion: boolean
  cancelled_after_completion: boolean
  in_finish_cohort: boolean
}

export interface AttendanceCounts {
  // Live view (currently-active bookings). Change with any booking or
  // cancellation activity.
  total_confirmed: number
  booked: number
  pending_post_completion: number
  capacity: number | null
  // Cohort view — the completed summary numbers. Derived durably
  // from server state. attended/absent are cohort-scoped (only count
  // members of the finish cohort). cohort_size is null until Finish.
  attended: number
  absent: number
  cohort_size: number | null
}

export interface AttendanceDashboard {
  event: AttendanceEvent
  counts: AttendanceCounts
  bookings: AttendanceRow[]
}

export interface AttendanceMutationResponse {
  booking_id: string
  attendance_status: AttendanceStatus
  attendance_source: AttendanceSource
  attendance_marked_at: string | null
  counts: AttendanceCounts
}

export interface AttendanceFinishResponse {
  attendance_completed_at: string
  attendance_completed_by: string
  counts: AttendanceCounts
  auto_marked_absent: number
}

export interface AttendanceReopenResponse {
  counts: AttendanceCounts
  restored_to_booked: number
}
