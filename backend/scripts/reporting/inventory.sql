-- Reporting classification inventory — READ ONLY.
--
-- Run in the Render fc-api Shell with:
--   python -c "import os,psycopg2,sys;c=psycopg2.connect(os.environ['DATABASE_URL']);cur=c.cursor();cur.execute(open('scripts/reporting/inventory.sql').read());[print(r) for r in cur.fetchall()]"
--
-- Or paste either query below into any read-only SQL client.
--
-- Nothing here writes. Collectives and accounts are listed separately and
-- on purpose: a test account inside a genuine Collective must be
-- classifiable as a test account without the Collective ceasing to be
-- production. Classifications are never inferred from names.

-- ── 1. Collectives ─────────────────────────────────────────────────────
SELECT
    s.slug,
    s.name,
    s.status,
    s.reporting_class                                              AS current_class,
    s.created_at::date                                             AS created,
    u.email                                                        AS owner_email,
    s.auto_grant_role IS NOT NULL                                  AS auto_managed,
    (SELECT count(*) FROM space_memberships m
      WHERE m.space_id = s.id AND m.status = 'active')             AS active_members,
    (SELECT count(*) FROM payment_transactions t
      WHERE t.space_id = s.id AND t.status = 'succeeded')           AS succeeded_payments,
    (SELECT count(*) FROM community_posts p
      WHERE p.space_id = s.id)                                     AS posts,
    (SELECT count(*) FROM events e  WHERE e.space_id = s.id)       AS gatherings,
    (SELECT count(*) FROM pathways w WHERE w.space_id = s.id)      AS pathways
FROM spaces s
LEFT JOIN users u ON u.id = s.creator_id
ORDER BY active_members DESC, s.created_at;
