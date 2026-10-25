package com.adcausalrisk.backend.qc.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/**
 * A manual quality-control audit record from the {@code qc_audit_record} table.
 *
 * <p>This table fills the gap between two existing review layers:
 * <ul>
 *   <li>{@code quality_check} — fully automated (Python rule engine), result is
 *       PASS / WARN / BLOCKED and never touches human judgement.</li>
 *   <li>{@code assessment_review} — a doctor signs off on a finished risk
 *       assessment; the target is an {@code risk_assessment} row, not raw data.</li>
 * </ul>
 * This entity records the <i>data-owner's</i> manual audit of raw subject/visit/
 * feature-level clinical data — for example when an import flagged a row, a
 * quality_check came back BLOCKED, or a researcher spotted something suspicious
 * while browsing.
 *
 * <p><b>JPA contract (mirrors the DDL in migration V7):</b>
 * <ul>
 *   <li>{@code ddl-auto: validate} — every column name, nullable flag and enum
 *       value below must match {@code V7__add_qc_audit_record.sql} exactly.</li>
 *   <li>No {@code @ManyToOne} navigations — the project models foreign keys as
 *       bare {@code Long} fields everywhere ({@link com.adcausalrisk.backend.visit.entity.Visit},
 *       {@link com.adcausalrisk.backend.subject.entity.Subject}). The database
 *       enforces referential integrity via FK constraints; services check that
 *       the referenced row exists before inserting.</li>
 *   <li>{@code abnormalItems} is {@code TEXT} in the DDL (stores a JSON array)
 *       and maps to {@code String} here — callers serialize/deserialize with
 *       Jackson. MySQL 8's native JSON type is deliberately avoided so the same
 *       DDL runs on H2 in tests.</li>
 *   <li>{@code auditedAt} is nullable: a row is created in {@code PENDING}
 *       state first, and only gets a timestamp when the auditor submits a
 *       decision. {@code createdAt} / {@code updatedAt} are always set by the
 *       application layer.</li>
 * </ul>
 */
@Entity
@Table(name = "qc_audit_record")
public class QcAuditRecord {

    /** What kind of data is being audited. */
    public enum TargetType {
        /** The whole subject row (alias, data_version, top-level status). */
        SUBJECT,
        /** A single visit row (mmse/moca/cdr_sb scores and visit_date). */
        VISIT,
        /** A single feature observation row. */
        FEATURE
    }

    /** Why this audit was triggered. */
    public enum SourceType {
        /** Created automatically when a {@code quality_check} row ends up BLOCKED or WARN. */
        AUTO_QC_TRIGGER,
        /** A researcher or data manager manually flagged something while browsing. */
        MANUAL_REVIEW,
        /** Created during CSV import preview when the import job found invalid rows. */
        IMPORT_PREVIEW
    }

    /** Lifecycle of the audit decision. */
    public enum Status {
        /** Row created, no auditor decision yet. {@code auditedAt} is null. */
        PENDING,
        /** Data is acceptable as-is or the flagged row has been corrected. */
        APPROVED,
        /** Data is wrong and must be re-collected / deleted / quarantined. */
        REJECTED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    /** Owning subject. Never null — every audit targets exactly one subject. */
    @Column(name = "subject_id", nullable = false)
    private Long subjectId;

    /**
     * Specific visit being audited. Null when {@code targetType} is SUBJECT-level
     * (e.g. alias change or data_version issue) or when multiple visits are
     * affected but the audit is filed at subject granularity.
     */
    @Column(name = "visit_id")
    private Long visitId;

    @Enumerated(EnumType.STRING)
    @Column(name = "target_type", nullable = false, length = 20)
    private TargetType targetType;

    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", nullable = false, length = 30)
    private SourceType sourceType;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private Status status;

    /**
     * Human-readable list of specific anomalies, stored as a JSON array string.
     * Example: {@code ["mmse score 35 exceeds valid range 0-30", "visit_date after today"]}.
     * Null if the auditor marked everything OK.
     */
    @Column(name = "abnormal_items", columnDefinition = "TEXT")
    private String abnormalItems;

    /** Free-form auditor note explaining the decision or describing follow-up needed. */
    @Column(name = "audit_comment", length = 2000)
    private String auditComment;

    /** The {@code sys_user} who made the decision (or who created the PENDING row). */
    @Column(name = "auditor_id", nullable = false)
    private Long auditorId;

    /** Null until a decision is submitted. */
    @Column(name = "audited_at")
    private Instant auditedAt;

    /**
     * Optional link back to the automatic quality_check row that triggered this
     * manual review. Null for {@code MANUAL_REVIEW} audits.
     */
    @Column(name = "quality_check_id")
    private Long qualityCheckId;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected QcAuditRecord() {
        // for JPA
    }

    /**
     * Constructor used when creating a new PENDING audit row with known anomalies.
     * {@code status} defaults to {@link Status#PENDING} and {@code auditedAt}
     * stays null until {@link #submitDecision} is called.
     *
     * @param abnormalItems JSON array string (or null) listing the specific anomaly texts.
     */
    public QcAuditRecord(Long subjectId,
                         Long visitId,
                         TargetType targetType,
                         SourceType sourceType,
                         Long auditorId,
                         Long qualityCheckId,
                         String abnormalItems,
                         Instant createdAt) {
        this.subjectId = subjectId;
        this.visitId = visitId;
        this.targetType = targetType;
        this.sourceType = sourceType;
        this.status = Status.PENDING;
        this.auditorId = auditorId;
        this.qualityCheckId = qualityCheckId;
        this.abnormalItems = abnormalItems;
        this.createdAt = createdAt;
        this.updatedAt = createdAt;
    }

    /**
     * Transition from PENDING to APPROVED or REJECTED.
     * Writes {@code status}, {@code abnormalItems}, {@code auditComment},
     * {@code auditedAt}, {@code auditorId} and bumps {@code updatedAt} atomically —
     * callers cannot leave a row in a half-updated state.
     *
     * @param auditorId the person making the decision (overwrites the PENDING creator).
     */
    public void submitDecision(Status newStatus,
                               String abnormalItems,
                               String auditComment,
                               Long auditorId,
                               Instant auditedAt) {
        if (newStatus == Status.PENDING) {
            throw new IllegalArgumentException("submitDecision requires APPROVED or REJECTED, not PENDING");
        }
        if (this.status != Status.PENDING) {
            throw new IllegalStateException("Audit record " + id + " is already " + this.status
                    + "; cannot be re-decided");
        }
        this.status = newStatus;
        this.abnormalItems = abnormalItems;
        this.auditComment = auditComment;
        this.auditorId = auditorId;
        this.auditedAt = auditedAt;
        this.updatedAt = auditedAt;
    }

    /**
     * Update the auditor's comment on an already-decided row (e.g. add a follow-up note).
     * Leaves status and timestamps alone except {@code updatedAt}.
     */
    public void updateComment(String newComment, Instant updatedAt) {
        this.auditComment = newComment;
        this.updatedAt = updatedAt;
    }

    public Long getId() {
        return id;
    }

    public Long getSubjectId() {
        return subjectId;
    }

    public Long getVisitId() {
        return visitId;
    }

    public TargetType getTargetType() {
        return targetType;
    }

    public SourceType getSourceType() {
        return sourceType;
    }

    public Status getStatus() {
        return status;
    }

    public String getAbnormalItems() {
        return abnormalItems;
    }

    public String getAuditComment() {
        return auditComment;
    }

    public Long getAuditorId() {
        return auditorId;
    }

    public Instant getAuditedAt() {
        return auditedAt;
    }

    public Long getQualityCheckId() {
        return qualityCheckId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}