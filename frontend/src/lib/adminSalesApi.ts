/**
 * Admin sales pipeline API client.
 * All calls include credentials so the fc_session cookie is forwarded.
 * Money is stored/sent as integer cents; use formatCents() for display.
 */

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '')

// ── Enum types ────────────────────────────────────────────────────────────────

export type BillingInterval = 'monthly' | 'quarterly' | 'annual'
export type LeadStatus =
  | 'prospect'
  | 'free_user'
  | 'trialing'
  | 'active'
  | 'paused'
  | 'cancelled'
  | 'past_due'
  | 'lost'
export type PipelineStage =
  | 'new_lead'
  | 'contacted'
  | 'qualified'
  | 'invited'
  | 'trial_or_free_user'
  | 'sales_conversation'
  | 'checkout_sent'
  | 'won'
  | 'lost'
  | 'nurture'
export type InterestLevel = 'low' | 'medium' | 'high' | 'very_high'
export type ActivityType =
  | 'note'
  | 'call'
  | 'email'
  | 'message'
  | 'meeting'
  | 'follow_up'
  | 'other'
export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'paused'
  | 'cancelled'
  | 'past_due'

export const LEAD_STATUSES: LeadStatus[] = [
  'prospect', 'free_user', 'trialing', 'active', 'paused', 'cancelled', 'past_due', 'lost',
]
export const PIPELINE_STAGES: PipelineStage[] = [
  'new_lead', 'contacted', 'qualified', 'invited', 'trial_or_free_user',
  'sales_conversation', 'checkout_sent', 'won', 'lost', 'nurture',
]
export const INTEREST_LEVELS: InterestLevel[] = ['low', 'medium', 'high', 'very_high']
export const ACTIVITY_TYPES: ActivityType[] = [
  'note', 'call', 'email', 'message', 'meeting', 'follow_up', 'other',
]
export const SUBSCRIPTION_STATUSES: SubscriptionStatus[] = [
  'trialing', 'active', 'paused', 'cancelled', 'past_due',
]
export const BILLING_INTERVALS: BillingInterval[] = ['monthly', 'quarterly', 'annual']

// ── Response shapes ───────────────────────────────────────────────────────────

export interface Plan {
  id: string
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Price {
  id: string
  plan_id: string
  currency: string
  amount_cents: number
  amount_display: string
  billing_interval: BillingInterval
  effective_from: string
  effective_to: string | null
  is_active: boolean
  created_at: string
}

export interface Lead {
  id: string
  first_name: string | null
  last_name: string | null
  email: string
  phone: string | null
  source: string | null
  status: LeadStatus
  current_stage: PipelineStage
  interest_level: InterestLevel | null
  notes_summary: string | null
  converted_user_id: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface Activity {
  id: string
  lead_id: string
  opportunity_id: string | null
  activity_type: ActivityType
  title: string
  body: string | null
  occurred_at: string
  created_by_user_id: string | null
  created_at: string
}

export interface Opportunity {
  id: string
  lead_id: string
  plan_id: string | null
  price_id: string | null
  stage: PipelineStage
  estimated_value_cents: number | null
  probability: number | null
  expected_close_date: string | null
  won_at: string | null
  lost_at: string | null
  lost_reason: string | null
  created_at: string
  updated_at: string
}

export interface SalesTask {
  id: string
  lead_id: string
  opportunity_id: string | null
  title: string
  description: string | null
  due_at: string | null
  completed_at: string | null
  assigned_to_user_id: string | null
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export interface Subscription {
  id: string
  user_id: string
  plan_id: string
  price_id: string
  status: SubscriptionStatus
  started_at: string
  current_period_start: string | null
  current_period_end: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  payment_provider: string | null
  payment_provider_subscription_id: string | null
  created_at: string
  updated_at: string
}

export interface SalesSummary {
  total_leads: number
  leads_by_stage: { stage: string; count: number }[]
  open_opportunities: number
  won_opportunities: number
  lost_opportunities: number
  opportunities_by_stage: { stage: string; count: number }[]
  pipeline_value_cents: number
  pipeline_value_display: string
  active_subscriptions: number
  mrr_cents: number
  mrr_display: string
  open_tasks: number
  overdue_tasks: number
  upcoming_tasks: { id: string; title: string; lead_id: string; due_at: string | null }[]
}

// ── Request payload shapes ────────────────────────────────────────────────────

export interface PlanCreate {
  name: string
  description?: string
  is_active?: boolean
}

export interface PriceCreate {
  plan_id: string
  currency?: string
  amount_cents: number
  billing_interval?: BillingInterval
}

export interface LeadCreate {
  email: string
  first_name?: string
  last_name?: string
  phone?: string
  source?: string
  status?: LeadStatus
  current_stage?: PipelineStage
  interest_level?: InterestLevel
  notes_summary?: string
}

export interface LeadUpdate {
  email?: string
  first_name?: string
  last_name?: string
  phone?: string
  source?: string
  status?: LeadStatus
  current_stage?: PipelineStage
  interest_level?: InterestLevel
  notes_summary?: string
  converted_user_id?: string
}

export interface ActivityCreate {
  title: string
  activity_type?: ActivityType
  body?: string
  opportunity_id?: string
}

export interface OpportunityCreate {
  lead_id: string
  plan_id?: string
  price_id?: string
  stage?: PipelineStage
  estimated_value_cents?: number
  probability?: number
  expected_close_date?: string
}

export interface OpportunityUpdate {
  plan_id?: string
  price_id?: string
  stage?: PipelineStage
  estimated_value_cents?: number
  probability?: number
  expected_close_date?: string
  lost_reason?: string
}

export interface StageUpdate {
  stage: PipelineStage
  lost_reason?: string
}

export interface TaskCreate {
  lead_id: string
  opportunity_id?: string
  title: string
  description?: string
  due_at?: string
  assigned_to_user_id?: string
}

export interface TaskUpdate {
  title?: string
  description?: string
  due_at?: string
  assigned_to_user_id?: string
}

export interface SubscriptionCreate {
  user_id: string
  plan_id: string
  price_id: string
  status?: SubscriptionStatus
  started_at?: string
  current_period_start?: string
  current_period_end?: string
}

export interface SubscriptionUpdate {
  status?: SubscriptionStatus
  current_period_start?: string
  current_period_end?: string
  cancelled_at?: string
  cancel_reason?: string
  payment_provider?: string
  payment_provider_subscription_id?: string
}

// ── Error class ───────────────────────────────────────────────────────────────

export class AdminApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'AdminApiError'
  }
}

// ── Fetch helper ──────────────────────────────────────────────────────────────

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })

  if (res.status === 204) return undefined as unknown as T

  let body: unknown
  try { body = await res.json() } catch { body = null }

  if (!res.ok) {
    const raw = body as { detail?: unknown } | null
    let msg = `HTTP ${res.status}`
    if (raw?.detail) {
      msg = Array.isArray(raw.detail)
        ? (raw.detail as { msg: string }[]).map((e) => e.msg).join(', ')
        : String(raw.detail)
    }
    throw new AdminApiError(res.status, msg)
  }

  return body as T
}

function qs(params: Record<string, string | boolean | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ── salesApi ──────────────────────────────────────────────────────────────────

export const salesApi = {
  // Plans
  listPlans: () => req<Plan[]>('/api/admin/sales/plans'),
  createPlan: (data: PlanCreate) =>
    req<Plan>('/api/admin/sales/plans', { method: 'POST', body: JSON.stringify(data) }),

  // Prices
  listPrices: (planId?: string) =>
    req<Price[]>(`/api/admin/sales/prices${planId ? `?plan_id=${planId}` : ''}`),
  createPrice: (data: PriceCreate) =>
    req<Price>('/api/admin/sales/prices', { method: 'POST', body: JSON.stringify(data) }),
  deactivatePrice: (id: string) =>
    req<Price>(`/api/admin/sales/prices/${id}/deactivate`, { method: 'PATCH' }),

  // Leads
  listLeads: (params?: { status?: string; stage?: string; include_deleted?: boolean }) =>
    req<Lead[]>(`/api/admin/sales/leads${qs({ ...params })}`),
  createLead: (data: LeadCreate) =>
    req<Lead>('/api/admin/sales/leads', { method: 'POST', body: JSON.stringify(data) }),
  getLead: (id: string) => req<Lead>(`/api/admin/sales/leads/${id}`),
  updateLead: (id: string, data: LeadUpdate) =>
    req<Lead>(`/api/admin/sales/leads/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteLead: (id: string) =>
    req<void>(`/api/admin/sales/leads/${id}`, { method: 'DELETE' }),

  // Activities
  listActivities: (leadId: string) =>
    req<Activity[]>(`/api/admin/sales/leads/${leadId}/activities`),
  createActivity: (leadId: string, data: ActivityCreate) =>
    req<Activity>(`/api/admin/sales/leads/${leadId}/activities`, {
      method: 'POST', body: JSON.stringify(data),
    }),

  // Opportunities
  listOpportunities: (params?: { lead_id?: string; stage?: string }) =>
    req<Opportunity[]>(`/api/admin/sales/opportunities${qs({ ...params })}`),
  createOpportunity: (data: OpportunityCreate) =>
    req<Opportunity>('/api/admin/sales/opportunities', {
      method: 'POST', body: JSON.stringify(data),
    }),
  getOpportunity: (id: string) => req<Opportunity>(`/api/admin/sales/opportunities/${id}`),
  updateOpportunity: (id: string, data: OpportunityUpdate) =>
    req<Opportunity>(`/api/admin/sales/opportunities/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),
  moveOpportunityStage: (id: string, data: StageUpdate) =>
    req<Opportunity>(`/api/admin/sales/opportunities/${id}/stage`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),

  // Tasks
  listTasks: (params?: { lead_id?: string; completed?: boolean }) =>
    req<SalesTask[]>(`/api/admin/sales/tasks${qs({ ...params })}`),
  createTask: (data: TaskCreate) =>
    req<SalesTask>('/api/admin/sales/tasks', { method: 'POST', body: JSON.stringify(data) }),
  updateTask: (id: string, data: TaskUpdate) =>
    req<SalesTask>(`/api/admin/sales/tasks/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),
  completeTask: (id: string) =>
    req<SalesTask>(`/api/admin/sales/tasks/${id}/complete`, { method: 'PATCH' }),

  // Subscriptions
  listSubscriptions: (params?: { user_id?: string; status?: string }) =>
    req<Subscription[]>(`/api/admin/sales/subscriptions${qs({ ...params })}`),
  createSubscription: (data: SubscriptionCreate) =>
    req<Subscription>('/api/admin/sales/subscriptions', {
      method: 'POST', body: JSON.stringify(data),
    }),
  updateSubscription: (id: string, data: SubscriptionUpdate) =>
    req<Subscription>(`/api/admin/sales/subscriptions/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),

  // Summary
  getSummary: () => req<SalesSummary>('/api/admin/sales/summary'),
}

// ── Admin user type (from /api/admin/users) ───────────────────────────────────

export interface AdminUser {
  id: string
  email: string
  name: string | null
  role: string
  created_at: string
}

export const adminApi = {
  listUsers: () => req<AdminUser[]>('/api/admin/users'),
}

// ── Display helpers ───────────────────────────────────────────────────────────

export function formatCents(cents: number, currency = 'AUD'): string {
  return `${currency} $${(cents / 100).toFixed(2)}`
}

export function labelStage(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-AU', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function leadLabel(lead: { first_name: string | null; last_name: string | null; email: string }): string {
  const name = [lead.first_name, lead.last_name].filter(Boolean).join(' ')
  return name ? `${name} — ${lead.email}` : lead.email
}

export function userLabel(user: { name: string | null; email: string }): string {
  return user.name ? `${user.name} — ${user.email}` : user.email
}
