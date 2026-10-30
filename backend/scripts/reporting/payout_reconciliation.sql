-- Payout reconciliation — read-only.
--
-- Why this exists
-- ---------------
-- World Insights reported $1,560 of outstanding creator payouts while
-- Stripe showed five completed payouts totalling $1,564.28 into the
-- platform's bank account. Those are different quantities and the near
-- match is a coincidence worth proving rather than assuming, so this
-- script takes the dashboard figure apart and shows what it is made of.
--
-- Every statement is a SELECT. Nothing here writes, marks, transfers or
-- reconciles anything, and no bank or Connect account identifier is
-- returned — only whether one is present.
--
-- How to run it
-- -------------
--   psql "$DATABASE_URL" -f scripts/reporting/payout_reconciliation.sql
--
-- Run it from the fc-api Render Shell, where DATABASE_URL already points
-- at production. Reading it first is encouraged: the questions are in
-- the headings.

\pset pager off
\timing off

-- The whole session is read-only, so a typo cannot write.
SET default_transaction_read_only = on;
BEGIN;

\echo
\echo '=== A. What the dashboard figure is actually made of ==='
\echo '--- outstanding_payouts_cents = SUM(net_creator - refunded_creator)'
\echo '--- over EVERY row with payout_status = pending, with no other filter.'

SELECT
  pt.transaction_type,
  pt.status,
  pt.stripe_mode,
  pt.payout_model,
  COUNT(*)                                                      AS rows,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0   AS counted_dollars
FROM payment_transactions pt
WHERE pt.payout_status = 'pending'
GROUP BY 1, 2, 3, 4
ORDER BY counted_dollars DESC;

\echo
\echo '--- The single number the Money page shows:'
SELECT
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0 AS dashboard_dollars
FROM payment_transactions pt
WHERE pt.payout_status = 'pending';

\echo
\echo '=== B. The same question, asked the way admin asks it ==='
\echo '--- The long-standing admin "Pending Payouts" total also requires a'
\echo '--- settled status, a member transaction type, a creator, and the'
\echo '--- deployment Stripe mode. If A and B differ, A is counting rows'
\echo '--- that are not a creator payout obligation.'

SELECT
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0 AS admin_equivalent_dollars,
  COUNT(*)                                                     AS rows
FROM payment_transactions pt
WHERE pt.payout_status = 'pending'
  AND pt.status IN ('succeeded', 'partially_refunded', 'refunded')
  AND pt.transaction_type IN (
        'member_pathway_purchase',
        'member_collective_purchase',
        'member_pathway_subscription',
        'member_collective_subscription',
        'gathering_ticket_purchase',
        'member_series_pass_purchase',
        'member_payment_option_purchase'
      )
  AND pt.creator_user_id IS NOT NULL
  AND pt.net_creator_amount_cents IS NOT NULL
  AND pt.stripe_mode = 'live';

\echo
\echo '=== C. Rows counted as owed whose payment never succeeded ==='
\echo '--- A ledger row is created when the Checkout Session opens, with'
\echo '--- payout_status = pending already set. Expiry and failure webhooks'
\echo '--- normally reset it, but the Gathering-ticket release path does not.'
\echo '--- Anything listed here is money no member ever paid.'

SELECT
  pt.status,
  pt.transaction_type,
  COUNT(*)                                                      AS rows,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0   AS wrongly_counted_dollars,
  MIN(pt.created_at)                                            AS earliest,
  MAX(pt.created_at)                                            AS latest
FROM payment_transactions pt
WHERE pt.payout_status = 'pending'
  AND pt.status NOT IN ('succeeded', 'partially_refunded', 'refunded')
GROUP BY 1, 2
ORDER BY wrongly_counted_dollars DESC;

\echo
\echo '=== D. Who the money is owed to, and for what ==='
\echo '--- Settled member purchases only, so this is the genuine'
\echo '--- obligation. Platform-owned Collectives have no creator share'
\echo '--- and never appear.'

SELECT
  s.name                                                        AS collective,
  u.name                                                        AS creator,
  CASE WHEN s.creator_id IS NULL THEN 'platform-owned' ELSE 'creator-owned' END AS ownership,
  pt.payout_model,
  pt.stripe_mode,
  COUNT(*)                                                      AS payments,
  SUM(pt.gross_amount_cents) / 100.0                            AS gross_dollars,
  SUM(pt.platform_fee_cents) / 100.0                            AS platform_fee_dollars,
  SUM(COALESCE(pt.processing_fee_cents, 0)) / 100.0             AS stripe_fee_dollars,
  COUNT(*) - COUNT(pt.processing_fee_cents)                     AS stripe_fee_unknown,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0  AS owed_dollars,
  MIN(COALESCE(pt.settled_at, pt.created_at))                   AS first_payment,
  MAX(COALESCE(pt.settled_at, pt.created_at))                   AS last_payment
FROM payment_transactions pt
LEFT JOIN spaces s ON s.id = pt.space_id
LEFT JOIN users  u ON u.id = pt.creator_user_id
WHERE pt.payout_status = 'pending'
  AND pt.status IN ('succeeded', 'partially_refunded', 'refunded')
GROUP BY 1, 2, 3, 4, 5
ORDER BY owed_dollars DESC;

\echo
\echo '=== E. What the revenue metrics can see, and what they cannot ==='
\echo '--- Gross sales, creator earnings, platform fee, processing costs,'
\echo '--- refunds and contribution all run through one type filter. The'
\echo '--- outstanding figure runs through none. This shows the gap.'

SELECT
  pt.transaction_type,
  CASE WHEN pt.transaction_type IN (
        'member_pathway_purchase',
        'member_collective_purchase',
        'member_pathway_subscription',
        'member_collective_subscription',
        'gathering_ticket_purchase'
      ) THEN 'counted in revenue metrics'
       ELSE 'INVISIBLE to revenue metrics' END                  AS visibility,
  COUNT(*)                                                      AS payments,
  SUM(pt.gross_amount_cents) / 100.0                            AS gross_dollars,
  SUM(pt.platform_fee_cents) / 100.0                            AS platform_fee_dollars,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)) / 100.0         AS creator_earnings_dollars
FROM payment_transactions pt
WHERE pt.status IN ('succeeded', 'partially_refunded', 'refunded')
  AND pt.transaction_type NOT IN ('creator_subscription_payment', 'refund', 'adjustment')
GROUP BY 1, 2
ORDER BY gross_dollars DESC;

\echo
\echo '=== F. Reconciling against the Stripe bank payouts ==='
\echo '--- Stripe pays the platform gross-minus-Stripe-fee on its own'
\echo '--- schedule. Creator earnings are gross-minus-platform-fee. The two'
\echo '--- are different subtractions over the same charges, which is why'
\echo '--- they land close together without being the same quantity.'

SELECT
  to_char(date_trunc('week', COALESCE(pt.settled_at, pt.created_at)), 'YYYY-MM-DD') AS week_beginning,
  COUNT(*)                                                      AS payments,
  SUM(pt.gross_amount_cents) / 100.0                            AS members_paid,
  SUM(COALESCE(pt.processing_fee_cents, 0)) / 100.0             AS stripe_fees,
  (SUM(pt.gross_amount_cents)
     - SUM(COALESCE(pt.processing_fee_cents, 0))
     - SUM(COALESCE(pt.refunded_amount_cents, 0))) / 100.0      AS expected_into_bank,
  SUM(pt.platform_fee_cents) / 100.0                            AS platform_kept,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0  AS creator_share
FROM payment_transactions pt
WHERE pt.status IN ('succeeded', 'partially_refunded', 'refunded')
  AND pt.transaction_type NOT IN ('creator_subscription_payment', 'refund', 'adjustment')
  AND pt.stripe_mode = 'live'
GROUP BY 1
ORDER BY 1;

\echo
\echo '=== G. Refunds and adjustments touching the balance ==='

SELECT
  pt.transaction_type,
  pt.status,
  pt.payout_status,
  COUNT(*)                                                      AS rows,
  SUM(COALESCE(pt.refunded_amount_cents, 0)) / 100.0            AS refunded_to_members,
  SUM(COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0    AS reversed_from_creator,
  SUM(COALESCE(pt.refunded_platform_fee_cents, 0)) / 100.0      AS reversed_from_platform,
  MAX(pt.last_refunded_at)                                      AS most_recent_refund
FROM payment_transactions pt
WHERE COALESCE(pt.refunded_amount_cents, 0) > 0
   OR pt.transaction_type IN ('refund', 'adjustment')
GROUP BY 1, 2, 3
ORDER BY refunded_to_members DESC;

\echo
\echo '=== H. Payouts already recorded, and by what arrangement ==='
\echo '--- payout_status = paid is only ever written by a recorded payout'
\echo '--- batch. If this is empty, no creator payout has been recorded,'
\echo '--- whatever has moved through the bank.'

SELECT
  pt.payout_model,
  pt.payout_status,
  COUNT(*)                                                      AS rows,
  COUNT(DISTINCT pt.payout_batch_id)                            AS batches,
  SUM(COALESCE(pt.net_creator_amount_cents, 0)
      - COALESCE(pt.refunded_creator_amount_cents, 0)) / 100.0  AS dollars,
  MIN(pt.payout_marked_at)                                      AS first_marked,
  MAX(pt.payout_marked_at)                                      AS last_marked
FROM payment_transactions pt
GROUP BY 1, 2
ORDER BY 1, 2;

\echo
\echo '--- Connect rows: the transfer status is the authority for these,'
\echo '--- not payout_status. Account identifiers are withheld.'

SELECT
  pt.connect_transfer_status,
  COUNT(*)                                                      AS rows,
  COUNT(pt.connect_destination_account_id)                      AS rows_with_a_destination,
  SUM(COALESCE(pt.transfer_amount_cents, 0)) / 100.0            AS transfer_dollars,
  SUM(COALESCE(pt.connect_unrecovered_amount_cents, 0)) / 100.0 AS unrecovered_dollars
FROM payment_transactions pt
WHERE pt.payout_model = 'connect'
GROUP BY 1
ORDER BY rows DESC;

\echo
\echo '=== I. Creator payout batches on record ==='

SELECT
  b.id,
  b.status,
  b.created_at,
  b.transaction_count,
  b.total_amount_cents / 100.0 AS dollars
FROM creator_payout_batches b
ORDER BY b.created_at DESC
LIMIT 20;

\echo
\echo '=== J. Which Stripe account the five payouts came from ==='
\echo '--- creator_bank_payouts records payouts from a CONNECTED account to'
\echo '--- a creator bank. Payouts from the Fresh Collective platform'
\echo '--- account to the platform bank are not recorded anywhere, which'
\echo '--- is how a bank payout can exist with no ledger trace. If this is'
\echo '--- empty, the five Paid payouts are platform payouts.'

SELECT
  u.name                       AS creator,
  p.stripe_mode,
  p.status,
  COUNT(*)                     AS payouts,
  SUM(p.amount_cents) / 100.0  AS dollars,
  MIN(p.arrival_date)          AS earliest_arrival,
  MAX(p.arrival_date)          AS latest_arrival,
  MAX(p.synced_at)             AS last_synced
FROM creator_bank_payouts p
LEFT JOIN users u ON u.id = p.creator_user_id
GROUP BY 1, 2, 3
ORDER BY dollars DESC;

\echo
\echo '=== K. Connect readiness, without revealing account identifiers ==='

SELECT
  u.name                                              AS creator,
  a.stripe_mode,
  a.stripe_account_id IS NOT NULL                     AS account_exists_at_stripe,
  a.payouts_status,
  a.payouts_enabled,
  a.connect_payouts_enabled_at IS NOT NULL            AS fc_routing_enabled
FROM creator_stripe_accounts a
LEFT JOIN users u ON u.id = a.creator_user_id
ORDER BY 1, 2;

ROLLBACK;
\echo
\echo 'Done. Nothing was written (the transaction was rolled back).'
