-- ============================================================================
-- AD-CausalRisk baseline schema
-- Source of truth for the table list: docs/Design_Guide.md section 3 (15 tables).
-- Requirements: docs/Course_SRS_V3_2.md (FR-AUTH-01/02/03, FR-DATA-*, FR-QUALITY-*,
-- FR-ASSESS-*, FR-FOLLOW-*, FR-AUDIT-01).
--
-- PORTABILITY CONTRACT
-- This single migration must run on MySQL 8 (target database) and on
-- H2 2.3.232 in MODE=MySQL (test profile). MySQL-only clauses are therefore
-- deliberately NOT used: no ENGINE=, no DEFAULT CHARSET, no COLLATE, no COMMENT,
-- no UNSIGNED, no ON UPDATE CURRENT_TIMESTAMP, no JSON column type. MySQL 8
-- already defaults to utf8mb4 / utf8mb4_0900_ai_ci, so no character-set clause
-- is needed for Chinese aliases.
--
-- TIMESTAMPS
-- DATETIME has no implicit auto-update in either engine, so updated_at is always
-- written by the application (Hibernate / service layer), never by the database.
--
-- JSON PAYLOADS
-- Stored as TEXT, not as MySQL JSON, so one DDL serves both engines. MySQL TEXT
-- is capped at 65535 bytes: the AgentClient PR must widen
-- risk_assessment.agent_result_json if a full AgentResult can exceed that.
--
-- DELIBERATELY ABSENT: a numeric risk_score column.
-- BLOCKED results must carry no score (FR-WARN-02, AGENTS.md). A nullable score
-- column is exactly the field that later gets back-filled with 0 or an
-- interpolated value; the score lives only inside agent_result_json.
-- ============================================================================


-- ---------------------------------------------------------------------------
-- Identity and roles (FR-AUTH-01/02/03)
-- ---------------------------------------------------------------------------
CREATE TABLE sys_user (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  username      VARCHAR(50)  NOT NULL,
  password_hash VARCHAR(100) NOT NULL,
  status        VARCHAR(20)  NOT NULL,
  created_at    DATETIME     NOT NULL,
  CONSTRAINT pk_sys_user PRIMARY KEY (id),
  CONSTRAINT uq_sys_user_username UNIQUE (username),
  CONSTRAINT ck_sys_user_status CHECK (status IN ('ACTIVE', 'DISABLED'))
);

-- role_code values are the four contract roles (CurrentUser.roles enum).
-- Adding a role later is a migration, on purpose.
CREATE TABLE sys_role (
  id        BIGINT      NOT NULL AUTO_INCREMENT,
  role_code VARCHAR(20) NOT NULL,
  CONSTRAINT pk_sys_role PRIMARY KEY (id),
  CONSTRAINT uq_sys_role_code UNIQUE (role_code),
  CONSTRAINT ck_sys_role_code CHECK (role_code IN ('ADMIN', 'RESEARCHER', 'DOCTOR', 'PATIENT'))
);

-- Explicit many-to-many: one account may hold several roles (Design_Guide:
-- "四种角色，明确多角色处理规则"). CurrentUser.roles is the union of these rows.
CREATE TABLE user_role (
  user_id BIGINT NOT NULL,
  role_id BIGINT NOT NULL,
  CONSTRAINT pk_user_role PRIMARY KEY (user_id, role_id),
  CONSTRAINT fk_user_role_user FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT fk_user_role_role FOREIGN KEY (role_id) REFERENCES sys_role (id) ON DELETE RESTRICT
);


-- ---------------------------------------------------------------------------
-- Subject and object-level authorisation (FR-DATA-01, FR-EXPLAIN-02)
-- ---------------------------------------------------------------------------
-- subject_code keeps the DEMO-* business key; id is the numeric primary key that
-- Java returns to the browser and maps back to the DEMO code when calling Python.
CREATE TABLE subject (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  subject_code VARCHAR(50)  NOT NULL,
  alias        VARCHAR(100) NOT NULL,
  status       VARCHAR(20)  NOT NULL,
  data_version VARCHAR(100) NOT NULL,
  created_at   DATETIME     NOT NULL,
  CONSTRAINT pk_subject PRIMARY KEY (id),
  CONSTRAINT uq_subject_code UNIQUE (subject_code),
  CONSTRAINT ck_subject_status CHECK (status IN ('ACTIVE', 'ARCHIVED')),
  CONSTRAINT ck_subject_data_version CHECK (data_version LIKE 'demo-%')
);

-- permission_type vocabulary is ours (not frozen by the OpenAPI contract):
--   VIEW         - read subject data (DOCTOR / RESEARCHER scope)
--   MANAGE       - create or modify subject, visits and features
--   SUMMARY_READ - read the patient-facing summary for this subject
CREATE TABLE subject_permission (
  id              BIGINT      NOT NULL AUTO_INCREMENT,
  subject_id      BIGINT      NOT NULL,
  user_id         BIGINT      NOT NULL,
  permission_type VARCHAR(30) NOT NULL,
  CONSTRAINT pk_subject_permission PRIMARY KEY (id),
  CONSTRAINT uq_subject_permission UNIQUE (subject_id, user_id, permission_type),
  CONSTRAINT fk_subject_permission_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT fk_subject_permission_user FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT ck_subject_permission_type CHECK (permission_type IN ('VIEW', 'MANAGE', 'SUMMARY_READ'))
);


-- ---------------------------------------------------------------------------
-- Visits and features (FR-DATA-01/02)
-- ---------------------------------------------------------------------------
-- visit_code is unique only within one subject. mmse / moca / cdr_sb stay NULL
-- when the source value is missing - a missing score is never stored as 0.
CREATE TABLE visit (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  subject_id BIGINT       NOT NULL,
  visit_code VARCHAR(50)  NOT NULL,
  visit_date DATE         NOT NULL,
  mmse       DECIMAL(4,1) NULL,
  moca       DECIMAL(4,1) NULL,
  cdr_sb     DECIMAL(4,1) NULL,
  CONSTRAINT pk_visit PRIMARY KEY (id),
  CONSTRAINT uq_visit_subject_code UNIQUE (subject_id, visit_code),
  CONSTRAINT fk_visit_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT ck_visit_mmse CHECK (mmse IS NULL OR (mmse >= 0 AND mmse <= 30)),
  CONSTRAINT ck_visit_moca CHECK (moca IS NULL OR (moca >= 0 AND moca <= 30)),
  CONSTRAINT ck_visit_cdr_sb CHECK (cdr_sb IS NULL OR (cdr_sb >= 0 AND cdr_sb <= 18))
);

-- There is intentionally NO unique constraint on
-- (subject_id, feature_name, recorded_at): docs/Integration_Contract.md requires
-- a same-day conflicting value to be observable so the workflow can return
-- BLOCKED. A unique constraint would make the conflict unstorable instead of
-- detectable. Duplicate/conflict handling is a service-layer rule for the
-- import PR; this index supports that lookup.
-- feature_name and unit mirror the frozen contract enums (FeatureResult).
CREATE TABLE subject_feature (
  id            BIGINT        NOT NULL AUTO_INCREMENT,
  subject_id    BIGINT        NOT NULL,
  feature_name  VARCHAR(50)   NOT NULL,
  feature_value DECIMAL(18,6) NULL,
  recorded_at   DATE          NOT NULL,
  unit          VARCHAR(20)   NOT NULL,
  CONSTRAINT pk_subject_feature PRIMARY KEY (id),
  CONSTRAINT fk_subject_feature_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT ck_subject_feature_name CHECK (feature_name IN ('APOE_E4_COUNT', 'MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R')),
  CONSTRAINT ck_subject_feature_unit CHECK (unit IN ('count', 'normalized'))
);
CREATE INDEX idx_subject_feature_lookup ON subject_feature (subject_id, feature_name, recorded_at);


-- ---------------------------------------------------------------------------
-- Import jobs and quality checks (FR-DATA-03/04/05, FR-QUALITY-01/02/03)
-- ---------------------------------------------------------------------------
-- created_at and error_report_json are internal columns; the contract's ImportJob
-- has no timestamp and carries its error rows in the response, which must survive
-- a Java restart (SRS stage 3). Error rows are never inserted into subject data.
CREATE TABLE data_import_job (
  id                BIGINT       NOT NULL AUTO_INCREMENT,
  created_by        BIGINT       NOT NULL,
  status            VARCHAR(20)  NOT NULL,
  data_version      VARCHAR(100) NOT NULL,
  total_rows        INT          NOT NULL,
  valid_rows        INT          NOT NULL,
  invalid_rows      INT          NOT NULL,
  error_report_json TEXT         NULL,
  created_at        DATETIME     NOT NULL,
  CONSTRAINT pk_data_import_job PRIMARY KEY (id),
  CONSTRAINT fk_data_import_job_user FOREIGN KEY (created_by) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT ck_data_import_job_status CHECK (status IN ('PREVIEW_READY', 'BLOCKED', 'COMMITTED', 'FAILED')),
  CONSTRAINT ck_data_import_job_counts CHECK (total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0),
  CONSTRAINT ck_data_import_job_data_version CHECK (data_version LIKE 'demo-%')
);

-- issues holds a JSON array of readable issue strings (TEXT, not JSON).
CREATE TABLE quality_check (
  id             BIGINT      NOT NULL AUTO_INCREMENT,
  subject_id     BIGINT      NOT NULL,
  quality_status VARCHAR(20) NOT NULL,
  issues         TEXT        NOT NULL,
  checked_at     DATETIME    NOT NULL,
  rule_version   VARCHAR(50) NOT NULL,
  CONSTRAINT pk_quality_check PRIMARY KEY (id),
  CONSTRAINT fk_quality_check_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT ck_quality_check_status CHECK (quality_status IN ('PASS', 'WARN', 'BLOCKED'))
);
CREATE INDEX idx_quality_check_subject_time ON quality_check (subject_id, checked_at);


-- ---------------------------------------------------------------------------
-- Assessment tasks, idempotency and results (FR-ASSESS-01/02, FR-AGENT-01/02)
-- ---------------------------------------------------------------------------
-- run_id is the Python replay key. It is UNIQUE because a retry must reuse the
-- original runId (Integration_Contract.md) instead of creating a second task;
-- PENDING tasks have run_id NULL and are unaffected by the unique constraint.
-- Java task idempotency is the separate idempotency_record table below.
CREATE TABLE assessment_task (
  id             BIGINT      NOT NULL AUTO_INCREMENT,
  subject_id     BIGINT      NOT NULL,
  status         VARCHAR(20) NOT NULL,
  run_id         VARCHAR(80) NULL,
  request_digest VARCHAR(64) NOT NULL,
  created_at     DATETIME    NOT NULL,
  updated_at     DATETIME    NOT NULL,
  CONSTRAINT pk_assessment_task PRIMARY KEY (id),
  CONSTRAINT fk_assessment_task_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT ck_assessment_task_status CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'BLOCKED', 'FAILED', 'CANCELLED')),
  CONSTRAINT uq_assessment_task_run_id UNIQUE (run_id)
);
CREATE INDEX idx_assessment_task_subject_status ON assessment_task (subject_id, status);

-- Scoped by user + operation + key, as required by FR-ASSESS-01.
CREATE TABLE idempotency_record (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  user_id         BIGINT       NOT NULL,
  operation       VARCHAR(100) NOT NULL,
  idempotency_key VARCHAR(100) NOT NULL,
  request_digest  VARCHAR(64)  NOT NULL,
  result_id       BIGINT       NULL,
  CONSTRAINT pk_idempotency_record PRIMARY KEY (id),
  CONSTRAINT fk_idempotency_record_user FOREIGN KEY (user_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT uq_idempotency_record UNIQUE (user_id, operation, idempotency_key)
);

-- agent_result_json keeps the complete AgentResult (versions, graph, explanations,
-- limitations). data_version / model_version / workflow_version / quality_status
-- are extracted at save time so reports and audits can query them directly.
-- One assessment per task.
CREATE TABLE risk_assessment (
  id                BIGINT       NOT NULL AUTO_INCREMENT,
  subject_id        BIGINT       NOT NULL,
  task_id           BIGINT       NOT NULL,
  agent_result_json TEXT         NOT NULL,
  review_status     VARCHAR(20)  NOT NULL,
  created_at        DATETIME     NOT NULL,
  data_version      VARCHAR(100) NOT NULL,
  model_version     VARCHAR(100) NOT NULL,
  workflow_version  VARCHAR(100) NOT NULL,
  quality_status    VARCHAR(20)  NOT NULL,
  CONSTRAINT pk_risk_assessment PRIMARY KEY (id),
  CONSTRAINT fk_risk_assessment_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT fk_risk_assessment_task FOREIGN KEY (task_id) REFERENCES assessment_task (id) ON DELETE RESTRICT,
  CONSTRAINT uq_risk_assessment_task UNIQUE (task_id),
  CONSTRAINT ck_risk_assessment_review_status CHECK (review_status IN ('PENDING', 'ACKNOWLEDGED', 'NEEDS_DATA', 'REJECTED')),
  CONSTRAINT ck_risk_assessment_quality_status CHECK (quality_status IN ('PASS', 'WARN', 'BLOCKED'))
);


-- ---------------------------------------------------------------------------
-- Human review and follow-up (FR-FOLLOW-01/02)
-- ---------------------------------------------------------------------------
CREATE TABLE assessment_review (
  id            BIGINT        NOT NULL AUTO_INCREMENT,
  assessment_id BIGINT        NOT NULL,
  reviewer_id   BIGINT        NOT NULL,
  decision      VARCHAR(20)   NOT NULL,
  comment       VARCHAR(2000) NOT NULL,
  reviewed_at   DATETIME      NOT NULL,
  CONSTRAINT pk_assessment_review PRIMARY KEY (id),
  CONSTRAINT fk_assessment_review_assessment FOREIGN KEY (assessment_id) REFERENCES risk_assessment (id) ON DELETE RESTRICT,
  CONSTRAINT fk_assessment_review_reviewer FOREIGN KEY (reviewer_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT ck_assessment_review_decision CHECK (decision IN ('ACKNOWLEDGED', 'NEEDS_DATA', 'REJECTED'))
);

CREATE TABLE follow_up_plan (
  id           BIGINT        NOT NULL AUTO_INCREMENT,
  subject_id   BIGINT        NOT NULL,
  scheduled_at DATETIME      NOT NULL,
  purpose      VARCHAR(1000) NOT NULL,
  status       VARCHAR(20)   NOT NULL,
  owner_id     BIGINT        NOT NULL,
  CONSTRAINT pk_follow_up_plan PRIMARY KEY (id),
  CONSTRAINT fk_follow_up_plan_subject FOREIGN KEY (subject_id) REFERENCES subject (id) ON DELETE RESTRICT,
  CONSTRAINT fk_follow_up_plan_owner FOREIGN KEY (owner_id) REFERENCES sys_user (id) ON DELETE RESTRICT,
  CONSTRAINT ck_follow_up_plan_status CHECK (status IN ('PLANNED', 'COMPLETED', 'CANCELLED'))
);
CREATE INDEX idx_follow_up_plan_subject_time ON follow_up_plan (subject_id, scheduled_at);


-- ---------------------------------------------------------------------------
-- Audit log (FR-AUDIT-01)
-- ---------------------------------------------------------------------------
-- actor_id is nullable on purpose: a failed login for an unknown username has no
-- user row, but the refusal must still be auditable.
-- occurred_at is this table's name for the contract's AuditEvent.timestamp
-- field; 'timestamp' is a data-type keyword in both engines.
CREATE TABLE audit_log (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  actor_id    BIGINT       NULL,
  event_type  VARCHAR(50)  NOT NULL,
  trace_id    VARCHAR(64)  NOT NULL,
  summary     VARCHAR(500) NOT NULL,
  occurred_at DATETIME     NOT NULL,
  CONSTRAINT pk_audit_log PRIMARY KEY (id),
  CONSTRAINT fk_audit_log_actor FOREIGN KEY (actor_id) REFERENCES sys_user (id) ON DELETE RESTRICT
);
CREATE INDEX idx_audit_log_time ON audit_log (occurred_at);
CREATE INDEX idx_audit_log_actor_time ON audit_log (actor_id, occurred_at);
