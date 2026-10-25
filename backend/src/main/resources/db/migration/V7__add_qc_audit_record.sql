-- ============================================================================
-- Manual QC audit records (FR-QUALITY-01 extension: human review of raw data)
--
-- This table sits BETWEEN automatic quality_check rows (Python PASS/WARN/BLOCKED)
-- and assessment_review rows (doctor sign-off on a risk_assessment result).
-- It records the data-owner's manual audit of a specific subject/visit/feature
-- when raw clinical data looks suspicious or an automated check raised a flag.
--
-- PORTABILITY: same rules as V1 baseline - no MySQL-only clauses (no ENGINE,
-- no DEFAULT CHARSET, no COMMENT, no JSON column type). abnormal_items is
-- stored as TEXT holding a JSON array so one DDL serves MySQL 8 and H2 tests.
--
-- FOREIGN KEYS:
--   fk_qc_audit_subject      -> subject(id)       ON DELETE RESTRICT
--   fk_qc_audit_visit        -> visit(id)         ON DELETE RESTRICT (nullable)
--   fk_qc_audit_auditor      -> sys_user(id)      ON DELETE RESTRICT
--   fk_qc_audit_quality_check-> quality_check(id) ON DELETE SET NULL (nullable)
--
-- TIMESTAMP contract: created_at is set by INSERT; updated_at is rewritten
-- by the application whenever status/comment changes (not by the DB).
-- ============================================================================

CREATE TABLE qc_audit_record (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  subject_id      BIGINT       NOT NULL,
  visit_id        BIGINT       NULL,
  target_type     VARCHAR(20)  NOT NULL,
  source_type     VARCHAR(30)  NOT NULL,
  status          VARCHAR(20)  NOT NULL,
  abnormal_items  TEXT         NULL,
  audit_comment   VARCHAR(2000) NULL,
  auditor_id      BIGINT       NOT NULL,
  audited_at      DATETIME     NULL,
  quality_check_id BIGINT     NULL,
  created_at      DATETIME     NOT NULL,
  updated_at      DATETIME     NOT NULL,
  CONSTRAINT pk_qc_audit_record PRIMARY KEY (id),
  CONSTRAINT fk_qc_audit_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT fk_qc_audit_visit FOREIGN KEY (visit_id) REFERENCES visit (id) ON DELETE RESTRICT,
  CONSTRAINT fk_qc_audit_auditor FOREIGN KEY (auditor_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT fk_qc_audit_quality_check FOREIGN KEY (quality_check_id) REFERENCES quality_check (id) ON DELETE SET NULL,
  CONSTRAINT ck_qc_audit_target_type CHECK (target_type IN ('SUBJECT', 'VISIT', 'FEATURE')),
  CONSTRAINT ck_qc_audit_source_type CHECK (source_type IN ('AUTO_QC_TRIGGER', 'MANUAL_REVIEW', 'IMPORT_PREVIEW')),
  CONSTRAINT ck_qc_audit_status CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'))
);

-- Common lookup: show pending audits per subject, ordered by creation time.
CREATE INDEX idx_qc_audit_subject_status ON qc_audit_record (subject_id, status, created_at);

-- Common lookup: all audits for a specific visit.
CREATE INDEX idx_qc_audit_visit ON qc_audit_record (visit_id);