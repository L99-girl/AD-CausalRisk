package com.adcausalrisk.backend.assessment.entity;

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
 * The immutable result of one assessment, mapped onto the V1 {@code risk_assessment} table.
 *
 * <p>{@code agent_result_json} keeps the complete AgentResult the Python service returned;
 * the versions and {@code quality_status} are extracted into their own columns so reports and
 * audits can query them without parsing JSON. One row per task ({@code uq_risk_assessment_task}).
 *
 * <p>There is deliberately no risk-score column: a BLOCKED result carries no score, and the
 * score only ever exists inside the JSON (see the V1 comment on this table).
 */
@Entity
@Table(name = "risk_assessment")
public class RiskAssessment {

    /** {@code ck_risk_assessment_review_status}. */
    public enum ReviewStatus {
        PENDING,
        ACKNOWLEDGED,
        NEEDS_DATA,
        REJECTED
    }

    /** {@code ck_risk_assessment_quality_status}. */
    public enum QualityStatus {
        PASS,
        WARN,
        BLOCKED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "subject_id", nullable = false)
    private Long subjectId;

    @Column(name = "task_id", nullable = false)
    private Long taskId;

    @Column(name = "agent_result_json", nullable = false)
    private String agentResultJson;

    @Enumerated(EnumType.STRING)
    @Column(name = "review_status", nullable = false, length = 20)
    private ReviewStatus reviewStatus;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "data_version", nullable = false, length = 100)
    private String dataVersion;

    @Column(name = "model_version", nullable = false, length = 100)
    private String modelVersion;

    @Column(name = "workflow_version", nullable = false, length = 100)
    private String workflowVersion;

    @Enumerated(EnumType.STRING)
    @Column(name = "quality_status", nullable = false, length = 20)
    private QualityStatus qualityStatus;

    protected RiskAssessment() {
        // for JPA
    }

    public RiskAssessment(
            Long subjectId,
            Long taskId,
            String agentResultJson,
            QualityStatus qualityStatus,
            String dataVersion,
            String modelVersion,
            String workflowVersion,
            Instant now) {
        this.subjectId = subjectId;
        this.taskId = taskId;
        this.agentResultJson = agentResultJson;
        this.qualityStatus = qualityStatus;
        this.dataVersion = dataVersion;
        this.modelVersion = modelVersion;
        this.workflowVersion = workflowVersion;
        this.reviewStatus = ReviewStatus.PENDING;
        this.createdAt = now;
    }

    public void markReviewed(ReviewStatus status) {
        this.reviewStatus = status;
    }

    public Long getId() {
        return id;
    }

    public Long getSubjectId() {
        return subjectId;
    }

    public Long getTaskId() {
        return taskId;
    }

    public String getAgentResultJson() {
        return agentResultJson;
    }

    public ReviewStatus getReviewStatus() {
        return reviewStatus;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public String getDataVersion() {
        return dataVersion;
    }

    public String getModelVersion() {
        return modelVersion;
    }

    public String getWorkflowVersion() {
        return workflowVersion;
    }

    public QualityStatus getQualityStatus() {
        return qualityStatus;
    }
}
