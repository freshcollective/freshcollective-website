# Fresh Collective Permissions Matrix

**Document version:** 1.1
**Last updated:** 2026-07-13
**Status:** Canonical. Alongside the Atlas and Design Language, this document is one of Fresh Collective's foundational architecture references.

---

## Purpose

Fresh Collective needs a single source of truth for **who can do what**.

This document defines:

- The four account types (Member, Creator, Platform Admin, Platform Owner) and how they relate to the three creator plans (Free, Plus, Pro).
- The full capability matrix across those account types.
- The distinction between account role, creator plan, and per-collective role (creator / moderator / learner).
- Ownership and billing rules for creator-owned vs. platform-owned collectives.
- A snapshot of the current implementation and the gaps between it and the intended model.

Whenever a new feature, role, or plan is proposed, it must be added to this matrix **before or alongside implementation**. This document should be updated in the same change.

---

## Guiding Principles

1. **Platform Owner is not a premium creator plan.** It is a distinct account type that sits alongside the Creator plans, not on top of them.
2. **Platform permissions are never inferred from email addresses.** Ownership is granted by role/flag, not by identity.
3. **Access is determined through explicit roles and capabilities.** No implicit trust.
4. **Creator-plan limits apply only to creator-owned collectives.** Platform-owned collectives are governed by platform rules, not by any creator plan.
5. **Platform-owned collectives are not subject to creator subscription limits or transaction fees.**
6. **Cornerstones are reserved for official Fresh Collective collectives.** Only Platform Owner (and, where explicitly agreed, Platform Admin) may assign them.
7. **Atlas Locations are available to ordinary creators.** Every published creator collective must live in an Atlas Location.
8. **Admin Portal access and Platform Owner status are conceptually separate**, even if the current owner is also the only admin. The document establishes the future distinction; the current implementation collapses them and is called out as a gap.
9. **Frontend hiding is not security.** Any capability gated in the UI must also be enforced by the backend API. If it isn't, it's a bug — file it and fix it.
10. **Every new feature is added to this matrix before or alongside implementation.**

---

## Account Types

Account type is the user's global role. It is distinct from:

- The **creator plan** they may be subscribed to (only applies to Creator accounts).
- Their **per-collective role** (`creator`, `moderator`, `learner`) which controls what they may do inside one collective.

The canonical account types:

### 1. MEMBER

- Default account type for anyone who signs up.
- May join and participate in collectives.
- Has no Creator Studio or Admin Portal access.
- May become a Creator by taking on that account type without ceasing to be a member.

### 2. CREATOR

- May create and manage their own collectives.
- Subject to a creator plan (Free / Plus / Pro).
- May choose Atlas Locations for their collectives.
- **May not** choose Cornerstone Locations.
- Subject to the Fresh Collective transaction fee attached to their plan.
- Is also a Member with respect to any collective they don't manage.

### 3. PLATFORM_ADMIN

- Distinct from Platform Owner.
- May access agreed platform administration functions (the Admin Portal, moderation, feature-flagging, viewing platform-wide data — exact scope to be defined per capability).
- Does **not** automatically own the platform.
- Does **not** automatically receive Platform Owner billing privileges.
- May or may not also hold a Creator account; if they do, standard creator plan rules apply to their own creator-owned collectives.
- The exact boundaries between "administration" and "ownership" are marked as **to be defined** where the product has not yet decided.

### 4. PLATFORM_OWNER

- The account that owns Fresh Collective itself.
- Has full Admin Portal access.
- Has no creator plan and no subscription.
- Bypasses all creator plan limits (unlimited collectives, pathways, storage, etc.).
- Pays no Fresh Collective transaction fee on member sales.
- May create unlimited official Fresh Collective collectives.
- May use Cornerstone Locations.
- Is the only account type that can create Cornerstones and assign them to official collectives.
- Platform Owner status must be represented by an explicit role/flag, **never** inferred from an email address.

### Members vs. Creators — practical clarification

A user may simultaneously be a Member (of collectives they've joined) and a Creator (of collectives they manage). The **account role** controls management capabilities across the platform; **memberships** control participation inside specific collectives. These two axes are orthogonal.

---

## Creator Plans

Creator plans govern only Creator accounts. They do not apply to Members (who have nothing to bill), Platform Admins (who administer, not create — though see the billing rules below if they also hold a Creator account), or Platform Owners (who have no plan).

The canonical plan lineup (v1.1):

1. **COMMUNITY** — Free. Contribute freely.
2. **CREATOR** — $19 AUD/month. Begin creating commercially.
3. **PRO** — $79 AUD/month. Grow a serious collective business.
4. **ORGANISATION** — Talk to us. Tailored support for larger teams and organisations.

**Progression narrative:** Contribute freely → begin creating commercially → grow into a serious collective business → expand into an organisation.

Community, Creator and Pro are self-service creator plans stored in the `creator_plans` database table. **Organisation is not a self-service subscription** — it is a lead pathway with no automatic provisioning, no subscription product, and no billing logic. The pricing UI renders it as a card with a "Talk to us" CTA that links to the existing `/for-creators` marketing page as an interim lead surface.

Every self-service creator has exactly one active plan at a time. Numeric allowances that are not yet decided (e.g. Pro's pooled member count, transaction-fee percentages, storage quantities) are represented as `None` / null in the plan configuration and displayed as **"To be defined"** in the UI. They are captured in Known Gaps below.

The canonical plan configuration lives in `backend/app/creator/plan_config.py` as a set of frozen `PlanCapability` dataclass records. Enforcement guards read from that module in `backend/app/creator/plan_guards.py`. Both are the single source of truth for the app.

---

## Ownership Rules

Fresh Collective distinguishes four ownership/participation concepts. They must not be conflated.

### 1. Platform-owned collective

- Owned by Fresh Collective itself.
- Created and managed by Platform Owner.
- Uses Cornerstone Locations (in most cases).
- Not subject to any creator plan limits.
- Not charged a Fresh Collective transaction fee on member sales.
- Creator payouts are not applicable — the platform is both operator and payee.

### 2. Creator-owned collective

- Owned by a specific Creator account (the collective's `creator_id`).
- Governed by the owning creator's plan (limits, fees).
- Uses an Atlas Location.
- The owning creator controls content and member experience within platform rules.
- The owning creator is the payee for creator payouts.

### 3. Collective membership

- A user's participation in a collective as a `learner`.
- Grants participation (view content, join gatherings, comment, react) but **not** management.
- Membership is orthogonal to account type.

### 4. Collective moderation

- A `moderator` on a specific collective helps manage that collective (moderating content, welcoming members, etc.).
- Does **not** own the collective and does **not** inherit billing privileges.
- Assigned by the owning creator.

### Key rule

Platform administration does **not** automatically transfer ownership of creator-owned content. A Platform Admin may moderate, suspend, or intervene in a creator-owned collective per platform policy, but the collective remains owned by its creator for billing, payout, and identity purposes.

---

## Billing Rules

### Platform Owner
- No creator plan.
- No subscription.
- Unlimited usage across all dimensions.
- **0%** Fresh Collective transaction fee.
- Creator payouts are **not applicable** for platform-owned collectives — 100% of member sales flow to Fresh Collective directly.

### Creators
- Assigned a creator plan (Free by default; Plus and Pro when available).
- Plan governs numeric limits (collectives, pathways, storage, etc.) and the platform transaction fee percentage.
- Member payment processing and creator payouts follow the creator billing model — payments run through Fresh Collective's Stripe account in Phase 1, with automatic Stripe Connect payouts planned for later phases.

### Members
- Do not have creator billing.
- May purchase collective or pathway access from creators; those payments flow through the creator billing model above.

### Platform Admin
- Billing treatment depends on whether they also own creator-owned collectives.
- Admin access alone does **not** waive creator fees on any creator-owned collectives they happen to run.
- Detailed behaviour (e.g. can a Platform Admin also be granted the "no transaction fee" concession for their own creator collectives?) is **to be defined**.

---

## Capability Matrix

Values:

- **Yes** — capability granted.
- **No** — capability not granted.
- **Plan dependent** — behaviour varies by creator plan; see creator plan design (to be defined).
- **Limited** — granted but with restrictions (e.g. only within collectives they manage).
- **Admin scope** — granted within the agreed Platform Admin scope; specific boundaries to be defined.
- **Owner only** — reserved for Platform Owner even if Platform Admin can access adjacent surfaces.
- **To be defined** — decision not yet made; explicitly deferred.

Where a capability is contingent on holding a per-collective role (creator / moderator), that constraint is called out in Notes.

### Member Experience

| Capability | Member | Community | Creator | Pro | Organisation | Platform Admin | Platform Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| Create an account | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Everyone starts as a Member; other roles are granted subsequently. |
| Join a free collective | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Requires published collective. |
| Purchase access to a paid collective | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Purchases treated identically regardless of account type. |
| View member dashboard | Yes | Yes | Yes | Yes | Yes | Yes | Yes | |
| Enter joined collectives | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Only collectives the user has joined. |
| Participate in community discussions | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Subject to per-collective rules. |
| Comment and react | Yes | Yes | Yes | Yes | Yes | Yes | Yes | |
| Attend gatherings | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Requires membership; paid gatherings require purchase. |
| Access purchased pathways | Yes | Yes | Yes | Yes | Yes | Yes | Yes | |
| Access resources | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Per-collective visibility rules apply. |
| Edit own profile | Yes | Yes | Yes | Yes | Yes | Yes | Yes | |
| Appear in member directory | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Per-collective visibility rules apply. |
| Leave a collective | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Cancels active membership. |

### Creator Studio

| Capability | Member | Community | Creator | Pro | Organisation | Platform Admin | Platform Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| Access Creator Studio | No | Yes | Yes | Yes | Yes | Yes | Yes | Platform Owner uses Creator Studio to manage official collectives. Organisation is provisioned manually. |
| Create a collective | No | Yes (approved, 1 max) | Yes (1 max) | Yes (5 max) | Tailored | To be defined | Yes | Community collectives require approval before publish (workflow TBD). Platform Owner unlimited. |
| Manage an existing collective | No | Limited | Limited | Limited | Limited | Admin scope | Yes | Limited = collectives the user owns or moderates. |
| Publish a collective | No | After approval | Yes | Yes | Yes | Admin scope | Yes | Community requires approval workflow (see Known Gaps). |
| Archive or close a collective | No | Yes | Yes | Yes | Yes | Admin scope | Yes | Own collectives only for creators. |
| Create pathways | No | Yes (non-commercial) | Yes | Yes | Yes | To be defined | Yes | Community pathways cannot be paid. |
| Create pathway steps | No | Yes | Yes | Yes | Yes | Admin scope | Yes | Within pathways they manage. |
| Upload resources | No | Yes (limited storage) | Yes | Yes | Yes | To be defined | Yes | Concrete storage quotas per plan are TBD. |
| Create community posts | No | Yes | Yes | Yes | Yes | Admin scope | Yes | Within collectives they manage. |
| Moderate own collective | No | Yes | Yes | Yes | Yes | Admin scope | Yes | |
| Schedule gatherings | No | Yes | Yes | Yes | Yes | Admin scope | Yes | |
| Invite members | No | Yes | Yes | Yes | Yes | Admin scope | Yes | |
| Manage members | No | Yes | Yes | Yes | Yes | Admin scope | Yes | Own collectives only for creators. |
| Assign collective moderators (caretakers) | No | No (self only) | No (self only) | Yes (multiple) | Yes | Admin scope | Yes | Community/Creator = one caretaker (the owner). Pro allows additional caretakers; exact number TBD. |
| View collective analytics | No | Basic | Standard | Advanced | Advanced | Admin scope | Yes | Analytics tier follows `PlanCapability.analytics_level`. |
| Export collective data | No | No | Plan dependent | Yes | Yes | Admin scope | Yes | Exact export scope per plan TBD. |
| Configure payments | No | No | Yes | Yes | Yes | To be defined | Yes | Community cannot enable paid offers. Phase 1 uses platform Stripe. |
| Enable paid memberships / pathways / gatherings | No | No | Yes | Yes | Yes | To be defined | Yes | `paid_offers_enabled` — enforced at the API. |
| Receive creator payouts | No | No | Yes | Yes | Yes | To be defined | Not applicable | Platform-owned collectives have no payout — 100% flows to FC. Community has no revenue to pay out. |
| Customise collective identity | No | Yes | Yes | Yes | Yes | Admin scope | Yes | Atmosphere, colour palette, statement, welcome message. |
| Choose an Atlas Location | No | Limited (3 approved) | Yes (full) | Yes (full) | Yes (full) | Admin scope | Yes | Community sees only the three configured Atlas Location keys. |
| Choose a Cornerstone Location | No | No | No | No | No | To be defined | Yes | Owner-only in current implementation; Admin scope pending decision. |
| Change a collective's Location | No | Yes (within subset) | Yes | Yes | Yes | Admin scope | Yes | Community may only switch to another approved Atlas Location. |
| Access automations | No | No | No | Yes | Yes | To be defined | Yes | Exact automation catalogue TBD. |

### Plan-based Limits (Creator accounts)

| Capability | Member | Community | Creator | Pro | Organisation | Platform Admin | Platform Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| Maximum active collectives | Not applicable | 1 | 1 | 5 | Tailored | To be defined | Unlimited | Enforced at the API by `guard_active_collective_limit`. |
| Maximum members per collective | Not applicable | 100 | 500 | Pooled (TBD) | Tailored | To be defined | Unlimited | Pro uses a pooled allowance across all collectives; the pooled number is TBD. Enforcement NOT yet implemented. |
| Maximum caretakers per collective | Not applicable | 1 | 1 | Multiple (TBD) | Tailored | To be defined | Unlimited | Community/Creator = owner only. Pro caretaker count TBD. Enforcement NOT yet implemented. |
| Maximum pathways | Not applicable | To be defined | To be defined | To be defined | Tailored | To be defined | Unlimited | Pathway count limit TBD. Enforcement NOT yet implemented. |
| Maximum storage | Not applicable | To be defined | To be defined | To be defined | Tailored | To be defined | Unlimited | Storage quotas TBD. Enforcement NOT yet implemented. |
| Paid offer capability | No | No | Yes | Yes | Yes | To be defined | Yes | Enforced at the API by `guard_paid_offers_enabled`. |
| Platform transaction fee | Not applicable | Not applicable | Higher tier (TBD %) | Lower tier (TBD %) | Tailored (TBD %) | To be defined | 0% | Fee % on Creator and Pro is TBD pending product decision. Community has no paid offers. |
| Custom branding | Not applicable | Basic (defaults) | Yes | Yes | Yes | To be defined | Yes | Community uses the default Atlas visuals; identity personalisation is still available (palette, atmosphere, statement). |
| Advanced analytics | Not applicable | No | No | Yes | Yes | Admin scope | Yes | Follows `analytics_level`. |
| Automations | Not applicable | No | No | Yes | Yes | To be defined | Yes | Exact automation set TBD. |
| Priority support | Not applicable | No | No | Yes | Yes (tailored) | To be defined | Yes | Support tier per plan is TBD; direction is Pro/Org receive priority. |
| Team or collaborator access | Not applicable | No | No | Yes | Yes | To be defined | Yes | Additional Creator Studio seats; seat count TBD. |
| Approval workflow required before publish | Not applicable | Yes | No | No | No | Not applicable | No | Community-only. Approval workflow itself is NOT yet built (Known Gaps). |
| Commercial use permitted | Not applicable | No | Yes | Yes | Yes | To be defined | Yes | Community is a non-commercial contribution pathway. |
| Self-service subscription | Not applicable | Yes | Yes | Yes | No | Not applicable | Not applicable | Organisation is a lead pathway; no self-service checkout. |

### Admin Portal

| Capability | Member | Community | Creator | Pro | Organisation | Platform Admin | Platform Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| Access Admin Portal | No | No | No | No | No | Yes | Yes | Both admin roles gain access; owner has full scope. |
| View platform overview | No | No | No | No | No | Yes | Yes | |
| View all users | No | No | No | No | No | Yes | Yes | |
| View all creators | No | No | No | No | No | Yes | Yes | |
| View all collectives | No | No | No | No | No | Yes | Yes | |
| Suspend users | No | No | No | No | No | Admin scope | Yes | Boundaries to be defined. |
| Suspend collectives | No | No | No | No | No | Admin scope | Yes | Boundaries to be defined. |
| Manage access and invitations | No | No | No | No | No | Admin scope | Yes | |
| View sales overview | No | No | No | No | No | Admin scope | Yes | Whether admins see revenue is a policy question. |
| View platform revenue | No | No | No | No | No | To be defined | Owner only | Financial visibility likely owner-scoped. |
| View platform payments | No | No | No | No | No | Admin scope | Yes | |
| Manage creator billing | No | No | No | No | No | To be defined | Owner only | Adjusting fees/plans for individual creators. |
| Manage creator plans | No | No | No | No | No | To be defined | Owner only | Editing plan definitions themselves. |
| Manage The Atlas | No | No | No | No | No | Yes | Yes | Admin currently has full Atlas management. |
| Create Atlas Locations | No | No | No | No | No | Yes | Yes | |
| Edit Atlas Locations | No | No | No | No | No | Yes | Yes | |
| Upload Location artwork | No | No | No | No | No | Yes | Yes | |
| Approve Community collectives | No | No | No | No | No | To be defined | Yes | Approval workflow NOT yet built (Known Gaps). |
| Configure Community Location subset | No | No | No | No | No | To be defined | Yes | Currently edited via `COMMUNITY_ATLAS_LOCATION_KEYS` in code; moving to Admin UI is a future task. |
| Create Cornerstones | No | No | No | No | No | To be defined | Yes | Should this be Admin scope or Owner only? To be decided. |
| Assign Cornerstones to official collectives | No | No | No | No | No | To be defined | Yes | Currently allowed for any admin; may narrow to Owner. |
| Feature collectives | No | No | No | No | No | Yes | Yes | |
| Moderate platform-wide content | No | No | No | No | No | Yes | Yes | |
| View audit logs | No | No | No | No | No | To be defined | Yes | Not yet built. |
| Change platform settings | No | No | No | No | No | To be defined | Owner only | Global feature flags, branding, etc. |
| Manage Platform Admin access | No | No | No | No | No | No | Owner only | Only Owner grants Admin. |
| Transfer platform ownership | No | No | No | No | No | No | Owner only | Reserved for Owner. |
| Provision Organisation accounts manually | No | No | No | No | No | To be defined | Yes | Organisation onboarding is a manual process; provisioning UI TBD. |

### Platform-Owned Collectives

| Capability | Member | Community | Creator | Pro | Organisation | Platform Admin | Platform Owner | Notes |
|---|---|---|---|---|---|---|---|---|
| Create official Fresh Collective collectives | No | No | No | No | No | To be defined | Yes | Owner-only in current implementation. |
| Unlimited official collectives | Not applicable | Not applicable | Not applicable | Not applicable | Not applicable | To be defined | Yes | No plan limit applies. |
| No creator subscription | Yes (no plan by design) | No | No | No | Not applicable (manual) | To be defined | Yes | Owner has no plan at all. |
| No Fresh Collective transaction fee | Not applicable | Not applicable | No | No | Tailored | To be defined | Yes | Owner-owned collectives are 0% fee. |
| Use Cornerstones | No | No | No | No | No | To be defined | Yes | Reserved for FC's own collectives. |
| Manage official member payments | No | No | No | No | No | Admin scope | Yes | Uses platform Stripe directly. |
| Bypass creator plan limits | Not applicable | No | No | No | Not applicable | To be defined | Yes | Owner sits outside plan system. |

---

## Implementation Notes

### How to check permissions correctly

1. **Backend is authoritative.** Every permission gate must be enforced on the backend API. The frontend hides UI to avoid confusing users; it does not enforce access.
2. **Never check email.** Ownership and admin status must come from a role/flag on the User record.
3. **Prefer role helpers to raw string comparisons.** A helper (e.g. `is_platform_owner(user)`) makes the intent explicit and centralises the definition. Raw `user.role == "admin"` scatter is a smell.
4. **Separate the two role axes.** Account role (`Member` / `Creator` / `Platform Admin` / `Platform Owner`) controls what a user can do platform-wide. Per-collective role (`creator` / `moderator` / `learner`) controls what a user can do inside one collective. These are independent — do not conflate.
5. **Plan limits apply only to Creator accounts.** Any endpoint that enforces a plan limit (max collectives, max pathways, storage) must short-circuit for Platform Owner and (per the future model) apply differently for Platform Admin who also holds creator collectives.
6. **Route protection.**
   - `/admin/*` — Platform Admin OR Platform Owner.
   - `/creator-studio/*`, `/creator/*` — Creator OR Platform Admin (for oversight) OR Platform Owner.
   - `/build-your-collective`, `/build-your-place` — Creator OR Platform Owner (Platform Admin scope to be defined).
   - Member-facing routes (`/dashboard`, `/spaces/*`, `/world`) — any authenticated user.
7. **Billing branches.** `/api/creator/billing` returns Platform Owner shape (no plan, no subscription, unlimited usage) for owner accounts. Creator accounts receive the plan/subscription/plan-lineup shape. Never merge the two responses.

### Names in the codebase

The **matrix names** (MEMBER / CREATOR / PLATFORM_ADMIN / PLATFORM_OWNER) are the canonical concepts. The **database values** currently in use (`'user'`, `'creator'`, `'admin'`) are legacy strings that will be migrated toward the canonical names as part of the plan-design work. Until then, treat the current values as an implementation detail with a mapping documented in the appendix below.

---

## Known Gaps and Future Decisions

Items marked "to be defined" throughout the matrix collect here. Each needs an explicit product decision before implementation.

### Platform Admin scope

- Does Platform Admin get to create Cornerstones, or only Platform Owner?
- Does Platform Admin see platform revenue, or is that Owner-only?
- Can Platform Admin manage creator billing (fee overrides, plan assignment) or only Owner?
- If a Platform Admin also runs their own creator collectives, does admin status waive the transaction fee on those collectives? Default answer: **no**. To be confirmed.
- Boundaries around suspending users and collectives — which admin actions require Owner co-sign?

### Creator plan design (open items after v1.1)

Decided in v1.1:
- Plan lineup: Community (Free) / Creator ($19) / Pro ($79) / Organisation (Talk to us).
- Community: 1 collective, 100 members, 1 caretaker, three approved Atlas Locations, no paid offers, requires approval, non-commercial.
- Creator: 1 collective, 500 members, 1 caretaker, full Atlas, paid offers, commercial.
- Pro: 5 collectives, pooled member allowance, multiple caretakers, full Atlas, paid offers, automations, advanced analytics, commercial.
- Organisation: tailored, no self-service, no subscription, lead pathway.

Still to be defined:
- **Creator transaction-fee percentage** (the "higher" tier).
- **Pro transaction-fee percentage** (the "lower" tier).
- **Pro pooled member allowance** — the aggregate member count across up to 5 collectives.
- **Pro caretaker allowance** — how many caretakers per collective.
- **Storage quantities** for Community / Creator / Pro (currently all `None` in `plan_config.py`).
- **Pathway count limits** if any per plan.
- **Exact automation catalogue** available at Pro/Organisation.
- **Community approval workflow** — no approval system exists yet; every collective can be published as soon as it's created. The `approval_required` flag on the Community plan is a declarative marker only until an approval queue is built.
- **Community inactivity / archive threshold** — how long a Community collective may remain inactive before being archived.
- **Trial and upgrade/downgrade flows** — currently plan changes are managed by Fresh Collective directly; no self-service upgrade path exists.
- **Enterprise provisioning workflow** — Organisation onboarding is entirely manual; no admin UI or self-service surface has been built.
- **Community Atlas Location subset** — the three Atlas Location keys are currently unpopulated in `COMMUNITY_ATLAS_LOCATION_KEYS` (empty tuple). Product must choose the three keys; enforcement falls back to full Atlas until they are set.

### Ownership model

- Mechanism for transferring platform ownership (single-owner today; multi-owner or role handoff in future?).
- Mechanism for transferring a creator-owned collective to a different creator or to the platform.

### Data and reporting

- Audit log surface and scope.
- Export capabilities per plan tier and admin role.

---

## Appendix: Current Implementation Alignment

Snapshot as of 2026-07-13. This audit compares the intended matrix above to the current code and marks each area as **aligned**, **partially aligned**, **not implemented**, or **legacy code remains**. No code is changed as part of drafting this document — the migration checklist at the end summarises the work required.

### Legend

- **Aligned** — current behaviour matches the intended matrix.
- **Partially aligned** — behaviour is correct in most cases but has gaps or conflations.
- **Not implemented** — the capability described does not exist in code yet.
- **Legacy code remains** — old code still exists that contradicts the intended model, even if newer code is aligned.

### 1. User role model — **Partially aligned**

- `User.role` is a `String(20)` with CHECK constraint `role IN ('user', 'creator', 'admin')`, default `'user'`. See `backend/app/models/user.py`.
- The canonical names in this matrix (MEMBER / CREATOR / PLATFORM_ADMIN / PLATFORM_OWNER) do not exist in the database. There is no `PLATFORM_OWNER` role separate from `admin`, and no `PLATFORM_ADMIN` role at all — every admin is treated as owner.
- Frontend surfaces the role as `'Member'` in some places (e.g. `admin/users/page.tsx`) even though the stored value is `'user'` — cosmetic mapping.
- **Gap:** the two-way split (Platform Admin vs. Platform Owner) is not represented anywhere in the schema.

### 2. Platform Owner billing branch — **Aligned**

- `GET /api/creator/billing` (`backend/app/creator/routes.py`) returns `current_plan = None`, `subscription = None`, `available_plans = []`, `is_platform_owner = True` when `current_user.role == "admin"`.
- Frontend `/creator-studio/billing/page.tsx` renders a distinct Platform Owner UI (no plan card, no fee calculator, no upgrade prompts, no "N of M collectives" copy).
- The billing schema (`CreatorBillingResponse`) treats `current_plan` and `subscription` as `Optional`, reflecting that Platform Owner is a distinct account type.

### 3. Creator plan resolution — **Aligned (v1.1)**

- The canonical plan lineup Community / Creator / Pro is now stored in `creator_plans` (migration 068).
- Organisation is not a DB row — it is synthesised in `GET /api/creator/billing` from `plan_config.ORGANISATION` and returned in `available_plans` for display, with `is_purchasable = false`.
- The capability record for each plan (paid offers, location scope, analytics level, etc.) lives in `backend/app/creator/plan_config.py` and is merged into `CreatorPlanOut` by `_creator_plan_out`.
- Existing subscriptions on old slugs `creator-basic` / `creator-plus` were renamed to `creator` / `pro` in-place by migration 068 (same plan IDs, no subscription-row disruption). Platform Owner subscriptions were cancelled by the migration.
- Creators without an active subscription still fall back to the cheapest active DB plan (Community, price 0).

### 4. Collective creation limits — **Aligned (v1.1)**

- `guard_active_collective_limit` in `backend/app/creator/plan_guards.py` now enforces the plan's `active_collective_limit` at both `POST /api/creator/spaces` and `POST /api/creator/build-your-collective/open`. Platform Owner bypasses the guard.
- The sidebar UI continues to show the "at limit" state; it now mirrors the API rather than being the only line of defence.
- Dead code (`CreateCollectiveFlow.tsx`, `CreateCollectiveForm.tsx`, `MAX_COLLECTIVES_FOR_FOUNDING_CREATOR`) has been removed. The `create-collective/page.tsx` and `create/page.tsx` redirect stubs remain because they are still linked from the sidebar's `dimmed` fallback in `CreatorStudioSidebar.tsx`.

### 5. Creator Studio access — **Aligned**

- `get_creator_user` in `backend/app/auth/dependencies.py` requires `role IN ('creator', 'admin')`.
- `frontend/src/app/creator-studio/layout.tsx` and `.../creator/layout.tsx` redirect users whose role is not in `['creator', 'admin']`.
- Consistent with the matrix: both Creator and Admin (currently Owner) have Studio access. Platform Admin future scope will be additive within this same gate.

### 6. Admin Portal access — **Aligned (but conflates Admin and Owner)**

- `get_admin_user` requires `role == "admin"`.
- `frontend/src/app/admin/layout.tsx` redirects users whose role is not `'admin'`.
- **Gap:** Platform Admin and Platform Owner both resolve to `role == 'admin'` in current code. Every capability in the "Admin Portal" section of the matrix that distinguishes Admin scope from Owner-only is currently granted to whoever is `admin`. When the distinction is introduced, this gate will split into two.

### 7. Cornerstone Location access — **Aligned to current model**

- Enforcement now goes through `guard_location_allowed` in `plan_guards.py`. Cornerstones are refused for every creator plan; Platform Owner is bypassed.
- Called from `_validate_identity_keys` and `update_identity` in `backend/app/creator/build_your_collective.py`.
- `GET /options` uses `allowed_atlas_location_query` (Community subset if configured; full Atlas otherwise) and appends Cornerstones only for Platform Owner.
- **Note:** Because `admin` currently collapses Platform Admin and Platform Owner, any Platform Admin today can assign Cornerstones. The matrix marks this as "To be defined" for Admin scope. When the roles split, this rule must be re-evaluated.

### 8. Atlas Location access — **Aligned**

- All active Atlas Locations are returned to every creator via `/api/creator/build-your-collective/options`.
- Validation at open/patch permits any `ATLAS` Location for creators.
- Admin management surface (`/admin/atlas`) creates, edits, and reorders both Cornerstones and Atlas Locations.

### 9. Platform-owned collective logic — **Partially aligned**

- A "platform-owned collective" in current code is defined implicitly: a collective whose `creator_id` belongs to a user with `role == 'admin'`.
- There is no explicit `is_platform_owned` flag on `Space`.
- Cornerstone Locations act as a proxy signal for platform-ownership in some UI, but the model would be cleaner with an explicit flag or a link to a "Fresh Collective" owner entity.
- Billing endpoint correctly treats admin-owned collectives as fee-exempt at the plan level, but individual payment/checkout code paths need audit to confirm the 0% fee actually applies at charge time (see item 10).

### 10. Transaction-fee logic — **Not fully audited**

- The Creator Billing page correctly displays 0% for Platform Owner.
- Whether the actual charge path (Stripe checkout / payment processing) computes fees from the collective owner's plan and correctly returns 0% for admin-owned collectives has **not been end-to-end verified** in this audit. Flagged for the plan-design task.

### 11. Creator payout logic — **Not implemented**

- Automatic creator payouts via Stripe Connect are documented as "coming later" in the billing UI. No payout mechanism exists today.
- The intended rule — Platform Owner receives no payout because there is no separate payee — will need to be encoded when payouts ship.

### 12. Frontend route protection — **Aligned**

- `/admin/*` gate: role check in `admin/layout.tsx`.
- `/creator-studio/*` and `/creator/*` gates: role check in the respective layouts.
- Member-facing routes: authenticated-session check via `SESSION_COOKIE` / `verifySessionToken`.
- No route relies on email for gating.
- **Note:** all UI gates match the current (collapsed Admin/Owner) model; they will need to be split when Platform Admin becomes distinct.

### 13. Backend API enforcement — **Aligned (v1.1) for the three guards below; other limits still open**

Enforced at the API in v1.1:
- **Active collective limit** — `guard_active_collective_limit`.
- **Location scope** (Community subset, Atlas-only, Cornerstone bypass) — `guard_location_allowed`.
- **Paid-offer capability** (Community rejects paid pricing) — `guard_paid_offers_enabled`.

Not yet enforced (flagged in Known Gaps → Creator plan design):
- Member count per collective / pooled member count.
- Caretaker count per collective.
- Pathway count.
- Storage quotas.
- Automations feature flag.

### Current-code role mapping (reference)

| Matrix name | Current DB value | Notes |
|---|---|---|
| MEMBER | `'user'` | Legacy string; display often shows "Member". |
| CREATOR | `'creator'` | |
| PLATFORM_ADMIN | (none) | Not yet distinct from Platform Owner. |
| PLATFORM_OWNER | `'admin'` | Currently collapsed with Platform Admin. |

---

## Migration Checklist

The items below sequence the work needed to make the implementation match the intended matrix. **This task does not perform any of these changes.** The list is captured here so the plan-design task can pull from it.

Ordered by dependency, cheapest → most invasive:

1. **Introduce an `is_platform_owner(user)` helper** in the backend and a matching `isPlatformOwner(user)` helper in the frontend. Replace scattered `user.role == "admin"` billing/limit checks with the helper. This is a pure refactor; no behaviour change.
2. **Enforce creator plan limits at the API.** Add a `check_creator_plan_capacity` guard used by `POST /api/creator/spaces`, `POST /api/creator/build-your-collective/open`, and future pathway/storage endpoints. Platform Owner short-circuits the check.
3. **Delete the dead `MAX_COLLECTIVES_FOR_FOUNDING_CREATOR` frontend constant** and the unreachable pages that use it (`create-collective/`, `create/`). Confirmed not routed today; still a landmine.
4. **Audit and confirm the actual payment/checkout path** applies the correct transaction fee for each collective owner type. Platform-owned collectives must resolve to 0% at charge time, not only in the billing display.
5. **Define Platform Admin scope.** Product decision: for each "to be defined" Admin scope cell in the matrix, choose Yes / Admin scope / Owner only. Update this document with the decisions.
6. **Split the `admin` role in the database.** Introduce `PLATFORM_OWNER` and `PLATFORM_ADMIN` (whether as separate role strings, a boolean flag, or a small role table) and migrate the existing single `admin` account to `PLATFORM_OWNER`. Update `get_admin_user` to accept either; introduce `get_platform_owner_user` for owner-only surfaces.
7. **Split the frontend `admin` gate** to distinguish Admin from Owner where the matrix requires it (Cornerstone creation, revenue view, plan management, ownership transfer).
8. **Encode platform-ownership on the `Space` model** — either an explicit `is_platform_owned` boolean or a `platform_owner_id` reference — so the billing/payout logic no longer has to infer it from the owner's role.
9. **Encode plan attributes properly for Free / Plus / Pro** once the plan-design task defines numeric limits and features. Migrate existing rows in `creator_plans` accordingly.
10. **Implement creator payouts** (Stripe Connect) with the rule that platform-owned collectives have no payout entity.

---

## Change Log

- **1.1 (2026-07-13)** — Canonical creator plan lineup adopted: Community (Free) / Creator ($19) / Pro ($79) / Organisation (Talk to us). Retired Creator Free / Plus / Pro naming. Locked in the decided values for max collectives (Community 1 / Creator 1 / Pro 5), members per collective (Community 100 / Creator 500), paid-offer capability, location scope (Community subset / others full Atlas), commercial use, approval requirement, self-service flag, and analytics tier. Left transaction-fee %, Pro pooled member allowance, Pro caretaker allowance, storage quotas, exact automation catalogue, Community approval workflow, and Community inactivity threshold as "To be defined". Backend enforcement added for active collective limit, location scope, and paid-offer capability. Organisation added as a lead-pathway card with no self-service checkout.
- **1.0 (2026-07-13)** — Initial version. Defines four account types, three creator plans, capability matrix across all major surfaces, ownership and billing rules, current-implementation audit, and migration checklist.
