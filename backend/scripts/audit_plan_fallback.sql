-- Read-only audit: who is affected by the creator-plan fallback change?
--
-- Release verification for commit 9795cc4. Run against production with a
-- read-only connection. Every statement here is a SELECT; nothing writes,
-- locks or modifies a row.
--
--   psql "$DATABASE_URL" -f scripts/audit_plan_fallback.sql
--
-- Background
-- ----------
-- `resolve_creator_plan` consults a subscription row first. A row whose
-- status is active / trialing / past_due decides the answer outright, and
-- the fallback is never reached. Only creators with no such row fall
-- through to "the cheapest active plan", which used to be ambiguous
-- whenever several plans cost the same.
--
-- Question 1 tells you whether the ambiguity exists in production at all.
-- Question 2 tells you how many creators it could have reached.
-- Question 3 shows what each answer would be, old versus new.


\echo ''
\echo '== 1. Is there a tie at the cheapest price? =================='
\echo '   (More than one row here is the condition that made the old'
\echo '    fallback arbitrary. Expect community + founding-creator,'
\echo '    and organisation if it has a row.)'
SELECT
    slug,
    monthly_price_cents,
    is_active,
    created_at
FROM creator_plans
WHERE is_active
  AND monthly_price_cents = (
      SELECT MIN(monthly_price_cents) FROM creator_plans WHERE is_active
  )
ORDER BY slug;


\echo ''
\echo '== 2. How many creators resolve through the fallback? ========'
\echo '   (Creators with NO current subscription. These are the only'
\echo '    accounts whose resolved plan can change.)'
SELECT
    COUNT(*) AS creators_without_current_subscription
FROM users u
WHERE u.role = 'creator'
  AND NOT EXISTS (
      SELECT 1
      FROM creator_subscriptions s
      WHERE s.user_id = u.id
        AND s.status IN ('active', 'trialing', 'past_due')
  );


\echo ''
\echo '== 3. Old answer vs new answer =============================='
\echo '   old_answer  = ORDER BY monthly_price_cents  (no tiebreak)'
\echo '   new_answer  = cheapest PURCHASABLE plan, slug as final tiebreak'
\echo '   If these differ, the fallback was returning the wrong plan.'
\echo '   Note: the old ordering is not stable, so re-run a few times.'
WITH cheapest AS (
    SELECT MIN(monthly_price_cents) AS price
    FROM creator_plans WHERE is_active
),
old_answer AS (
    SELECT slug FROM creator_plans
    WHERE is_active
    ORDER BY monthly_price_cents
    LIMIT 1
),
new_answer AS (
    SELECT slug FROM creator_plans
    WHERE is_active
      AND monthly_price_cents = (SELECT price FROM cheapest)
      -- Purchasable set, mirroring plan_config.is_purchasable. Founding
      -- Creator and Organisation are assigned by hand and must never be
      -- a fallback destination.
      AND slug NOT IN ('founding-creator', 'organisation')
    ORDER BY slug
    LIMIT 1
)
SELECT
    (SELECT slug FROM old_answer) AS old_answer,
    (SELECT slug FROM new_answer) AS new_answer,
    ((SELECT slug FROM old_answer) IS DISTINCT FROM (SELECT slug FROM new_answer))
        AS answers_differ;


\echo ''
\echo '== 4. Legitimate assignments that must NOT change ============'
\echo '   Every creator WITH a current subscription keeps their plan.'
\echo '   This is a census, not a check — nothing here is at risk.'
SELECT
    p.slug                         AS plan,
    s.status,
    s.source,
    COUNT(*)                       AS creators,
    COUNT(*) FILTER (WHERE s.ends_at IS NOT NULL) AS finite_grants
FROM creator_subscriptions s
JOIN creator_plans p ON p.id = s.creator_plan_id
WHERE s.status IN ('active', 'trialing', 'past_due')
GROUP BY p.slug, s.status, s.source
ORDER BY p.slug, s.status, s.source;


\echo ''
\echo '== 5. Complimentary grants still running ====================='
\echo '   Manual grants with a finite term. These resolve from their'
\echo '   subscription row, so the fallback change cannot touch them.'
SELECT
    p.slug      AS plan,
    s.status,
    s.ends_at,
    (s.ends_at < NOW()) AS term_has_passed
FROM creator_subscriptions s
JOIN creator_plans p ON p.id = s.creator_plan_id
WHERE s.source = 'manual_grant'
  AND s.status IN ('active', 'trialing', 'past_due')
ORDER BY s.ends_at NULLS LAST;


\echo ''
\echo '== 6. Would the grant-expiry sweep have halted? =============='
\echo '   community_is_the_fallback() returned false whenever the tie'
\echo '   resolved to another plan, which stops the whole sweep.'
\echo '   TRUE here means the sweep is safe to run.'
SELECT
    (SELECT slug FROM creator_plans
      WHERE is_active
        AND monthly_price_cents = (
            SELECT MIN(monthly_price_cents) FROM creator_plans WHERE is_active)
        AND slug NOT IN ('founding-creator', 'organisation')
      ORDER BY slug LIMIT 1) = 'community' AS sweep_will_run;
\echo ''
