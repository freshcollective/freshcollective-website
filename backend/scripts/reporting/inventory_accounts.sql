-- Reporting classification inventory: ACCOUNTS — READ ONLY.
--
-- Separate from the Collective inventory by design. Most current member
-- accounts are test accounts, and a test account inside a production
-- Collective must not inflate genuine membership or engagement figures.
--
-- ``email_pattern`` is a *hint for a human*, never a classification.
-- Nothing is classified automatically and nothing here writes.

SELECT
    u.email,
    u.role,
    u.reporting_class                                          AS current_class,
    u.created_at::date                                         AS registered,
    u.email_verified_at IS NOT NULL                            AS verified,
    CASE
        WHEN u.email ILIKE '%@example.%'  THEN 'rfc-reserved domain'
        WHEN u.email ILIKE '%.test'       THEN 'reserved .test TLD'
        WHEN u.email ILIKE '%playwright%' THEN 'automated test account'
        WHEN u.email ILIKE '%+test%'      THEN 'plus-addressed test'
        WHEN u.email ILIKE '%test%'       THEN 'contains "test"'
        ELSE ''
    END                                                        AS email_pattern,
    (SELECT count(*) FROM space_memberships m
      WHERE m.user_id = u.id AND m.status = 'active')          AS active_memberships,
    (SELECT count(*) FROM payment_transactions t
      WHERE t.payer_user_id = u.id AND t.status = 'succeeded') AS purchases,
    (SELECT count(*) FROM community_posts p WHERE p.author_id = u.id)
      + (SELECT count(*) FROM post_comments c WHERE c.author_id = u.id)
      + (SELECT count(*) FROM event_bookings b
          WHERE b.user_id = u.id AND b.attendance_status = 'attended')
                                                               AS participation_acts
FROM users u
ORDER BY
    (u.email ILIKE '%@example.%' OR u.email ILIKE '%.test'
     OR u.email ILIKE '%playwright%' OR u.email ILIKE '%test%') DESC,
    participation_acts DESC,
    u.created_at;
