-- ============================================================================
-- Preserve the score values exactly as they were submitted.
--
-- V3 widened the columns to DECIMAL(5,2), which still rounds a submitted value: 27.555 is
-- stored as 27.56 and the original observation is lost. For research and clinical data the
-- input must not be altered, so the raw value now has its own column and the DECIMAL columns
-- are demoted to derived/display columns.
--
-- SEMANTICS AFTER THIS MIGRATION
--   raw_mmse / raw_moca / raw_cdr_sb  - authoritative, the value exactly as submitted,
--                                       stored as text so no scale is imposed. The API returns
--                                       these.
--   mmse / moca / cdr_sb              - derived: round(raw, 2). Kept for charts, list views
--                                       and any SQL that needs a real number. Never the source
--                                       of truth for scoring.
--
-- PORTABILITY
-- ADD COLUMN and a plain UPDATE assignment work on both MySQL 8 and H2 2.x in MODE=MySQL
-- (verified on H2 2.3.232). The backfill deliberately does NOT use CAST: MySQL does not
-- accept CAST(... AS VARCHAR) and H2 does not accept CAST(... AS CHAR) the same way, whereas
-- assigning a DECIMAL to a VARCHAR column converts implicitly on both engines.
--
-- BACKFILL IS BEST EFFORT AND IRREVERSIBLE
-- Rows written before this migration were already rounded by V1/V2 (scale 1) or V3 (scale 2),
-- so the backfill copies the rounded value. That recovers "the value the database still has",
-- NOT the original submission. Those rows are shown with the rounded number from now on; the
-- original is gone and this migration cannot reconstruct it.
-- ============================================================================
ALTER TABLE visit ADD COLUMN raw_mmse VARCHAR(64) NULL;
ALTER TABLE visit ADD COLUMN raw_moca VARCHAR(64) NULL;
ALTER TABLE visit ADD COLUMN raw_cdr_sb VARCHAR(64) NULL;

UPDATE visit SET raw_mmse = mmse, raw_moca = moca, raw_cdr_sb = cdr_sb;
