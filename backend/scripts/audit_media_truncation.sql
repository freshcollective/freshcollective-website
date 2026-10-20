-- Read-only audit: which Media Library assets may have been truncated?
--
--   psql "$DATABASE_URL" -f scripts/audit_media_truncation.sql
--
-- Every statement is a SELECT. Nothing writes, locks, deletes or alters
-- a row, and no file content is read — this works purely from stored
-- metadata. Content verification is a separate, optional step; see
-- `scripts/verify_media_truncation.py`.
--
-- What was wrong
-- --------------
-- Next.js capped proxied request bodies at 10 MiB (10,485,760 bytes) and
-- silently ended the stream past that, while still returning HTTP 200.
-- Any upload crossing /api/* was affected, so a creator uploading a
-- 25 MB PDF had a ~10 MB fragment stored and was told it worked.
--
-- The signature
-- -------------
-- The cap applied to the whole multipart body, which carries a few
-- hundred bytes of framing around the file. A truncated file therefore
-- lands just *under* 10 MiB — clustered in a narrow band rather than at
-- one exact value, because the framing length varies with the filename.
--
-- Measured totals at the upstream during the investigation:
--     10,485,760   10,477,693   10,469,501
--
-- So: file_size_bytes between 10,400,000 and 10,485,760 is a CANDIDATE.
-- It is not proof — a genuine 10.4 MB file looks identical in metadata.
-- Section 4 explains how to tell them apart.

\echo ''
\echo '== 1. How exposed are we at all? ============================='
\echo '   Assets at or above the old cap could not have been stored'
\echo '   intact through the browser upload path.'
SELECT
    COUNT(*)                                                  AS total_assets,
    COUNT(*) FILTER (WHERE file_size_bytes >= 10400000)       AS at_or_near_cap,
    COUNT(*) FILTER (WHERE file_size_bytes >  10485760)       AS above_cap_impossible,
    MAX(file_size_bytes)                                      AS largest_asset
FROM creator_media_assets;
\echo '   NOTE: a non-zero "above_cap_impossible" means some assets did'
\echo '   NOT come through the browser proxy (server-side import, direct'
\echo '   upload, or a seed script) — those were never at risk.'


\echo ''
\echo '== 2. Candidate records ======================================'
\echo '   The narrow band just under 10 MiB. Review these.'
SELECT
    a.id,
    a.space_id,
    s.slug                AS collective,
    a.original_filename,
    a.media_type,
    a.extension,
    a.file_size_bytes,
    (10485760 - a.file_size_bytes) AS bytes_below_cap,
    a.created_at,
    a.storage_path
FROM creator_media_assets a
LEFT JOIN spaces s ON s.id = a.space_id
WHERE a.file_size_bytes BETWEEN 10400000 AND 10485760
ORDER BY a.created_at DESC;


\echo ''
\echo '== 3. Same check for the other two affected routes ==========='
\echo '   Collective resources and Pathway step resources shared the'
\echo '   same upload path and the same cap.'
SELECT 'space_resources' AS table_name, r.id, r.title,
       r.file_size AS file_size_bytes, r.created_at
FROM space_resources r
WHERE r.file_size BETWEEN 10400000 AND 10485760
UNION ALL
SELECT 'step_resources', sr.id, sr.title, sr.file_size, sr.created_at
FROM step_resources sr
WHERE sr.file_size BETWEEN 10400000 AND 10485760
ORDER BY created_at DESC;


\echo ''
\echo '== 4. Who to contact, if anything is confirmed ==============='
\echo '   Grouped by Collective so one message can cover one creator.'
SELECT
    s.slug                       AS collective,
    s.name                       AS collective_name,
    u.email                      AS uploaded_by,
    COUNT(*)                     AS candidate_assets,
    MIN(a.created_at)            AS earliest,
    MAX(a.created_at)            AS latest
FROM creator_media_assets a
LEFT JOIN spaces s ON s.id = a.space_id
LEFT JOIN users  u ON u.id = a.uploaded_by_user_id
WHERE a.file_size_bytes BETWEEN 10400000 AND 10485760
GROUP BY s.slug, s.name, u.email
ORDER BY candidate_assets DESC;


\echo ''
\echo '== 5. Context: the size distribution ========================='
\echo '   If nothing sits near 10 MiB at all, the exposure is zero and'
\echo '   no content verification is needed.'
SELECT
    CASE
        WHEN file_size_bytes <  1048576  THEN 'a. under 1 MB'
        WHEN file_size_bytes <  5242880  THEN 'b. 1-5 MB'
        WHEN file_size_bytes <  9437184  THEN 'c. 5-9 MB'
        WHEN file_size_bytes < 10400000  THEN 'd. 9-9.9 MB'
        WHEN file_size_bytes <= 10485760 THEN 'e. 9.9-10 MiB  <-- CANDIDATES'
        ELSE                                  'f. above 10 MiB (not proxied)'
    END                      AS size_band,
    COUNT(*)                 AS assets
FROM creator_media_assets
GROUP BY size_band
ORDER BY size_band;
\echo ''
