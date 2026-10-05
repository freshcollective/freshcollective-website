\echo '=== 1. intents carrying a Render host, by state ==='
SELECT state,
       count(*) AS intents,
       min(created_at)::date AS oldest,
       max(created_at)::date AS newest
FROM communication_intents
WHERE (strpos(coalesce(payload_body_html, ''), 'onrender.com') > 0
    OR strpos(coalesce(payload_body_text, ''), 'onrender.com') > 0
    OR strpos(coalesce(payload_subject, ''), 'onrender.com') > 0
    OR strpos(CAST(coalesce(template_context, '{}') AS text), 'onrender.com') > 0)
GROUP BY state
ORDER BY state;

\echo ''
\echo '=== 2. the ones that have NOT been sent yet (these would still go out wrong) ==='
SELECT id, state, topic_key, scheduled_for, created_at
FROM communication_intents
WHERE state IN ('queued', 'dispatching')
  AND (strpos(coalesce(payload_body_html, ''), 'onrender.com') > 0
    OR strpos(coalesce(payload_body_text, ''), 'onrender.com') > 0
    OR strpos(CAST(coalesce(template_context, '{}') AS text), 'onrender.com') > 0)
ORDER BY created_at
LIMIT 50;

\echo ''
\echo '=== 3. events whose stored payload carries one (re-routing would reuse it) ==='
SELECT event_type, count(*) AS events, min(occurred_at)::date AS oldest
FROM communication_events
WHERE strpos(CAST(coalesce(payload, '{}') AS text), 'onrender.com') > 0
GROUP BY event_type ORDER BY 2 DESC;

\echo ''
\echo '=== 4. in-app notifications storing an absolute Render link ==='
SELECT count(*) AS notifications FROM notifications
WHERE strpos(coalesce(url, ''), 'onrender.com') > 0;
