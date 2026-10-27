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
 * One persisted assessment request, mapped onto the V1 {@code assessment_task} table.
 *
 * <p>The row exists before the Python call and keeps its {@code runId}, so a crash or a timeout
 * still leaves an auditable record that can be reconciled through {@code GET /runs/{runId}}.
 * {@code runId} is UNIQUE: a retry must reuse the original id instead of minting a second run.
 */
@Entity
@Table(name = "assessment_task")
public class AssessmentTask {

    /** {@code ck_assessment_task_status}; FAILED is a Java-side state, Python only returns COMPLETED/BLOCKED. */
    public enum Status {
        PENDING,
        RUNNING,
        COMPLETED,
        BLOCKED,
        FAILED,
        CANCELLED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "subject_id", nullable = false)
    private Long subjectId;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false, length = 20)
    private Status status;

    @Column(name = "run_id", length = 80)
    private String runId;

    @Column(name = "request_digest", nullable = false, length = 64)
    private String requestDigest;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected AssessmentTask() {
        // for JPA
    }

    public AssessmentTask(Long subjectId, String runId, String requestDigest, Instant now) {
        this.subjectId = subjectId;
        this.runId = runId;
        this.requestDigest = requestDigest;
        this.status = Status.PENDING;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void markCompleted(Instant now) {
        this.status = Status.COMPLETED;
        this.updatedAt = now;
    }

    public void markBlocked(Instant now) {
        this.status = Status.BLOCKED;
        this.updatedAt = now;
    }

    public void markFailed(Instant now) {
        this.status = Status.FAILED;
        this.updatedAt = now;
    }

    public Long getId() {
        return id;
    }

    public Long getSubjectId() {
        return subjectId;
    }

    public Status getStatus() {
        return status;
    }

    public String getRunId() {
        return runId;
    }

    public String getRequestDigest() {
        return requestDigest;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }
}
