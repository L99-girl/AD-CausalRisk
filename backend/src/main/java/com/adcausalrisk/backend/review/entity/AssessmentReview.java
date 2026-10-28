package com.adcausalrisk.backend.review.entity;

import java.time.Instant;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One human review of an assessment (V1 {@code assessment_review}, FR-FOLLOW-01). */
@Entity
@Table(name = "assessment_review")
public class AssessmentReview {

    /** {@code ck_assessment_review_decision}. */
    public enum Decision {
        ACKNOWLEDGED,
        NEEDS_DATA,
        REJECTED
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "assessment_id", nullable = false)
    private Long assessmentId;

    @Column(name = "reviewer_id", nullable = false)
    private Long reviewerId;

    @Enumerated(EnumType.STRING)
    @Column(name = "decision", nullable = false, length = 20)
    private Decision decision;

    @Column(name = "comment", nullable = false, length = 2000)
    private String comment;

    @Column(name = "reviewed_at", nullable = false)
    private Instant reviewedAt;

    protected AssessmentReview() {
        // for JPA
    }

    public AssessmentReview(Long assessmentId, Long reviewerId, Decision decision, String comment, Instant reviewedAt) {
        this.assessmentId = assessmentId;
        this.reviewerId = reviewerId;
        this.decision = decision;
        this.comment = comment;
        this.reviewedAt = reviewedAt;
    }

    public Long getId() {
        return id;
    }

    public Long getAssessmentId() {
        return assessmentId;
    }

    public Long getReviewerId() {
        return reviewerId;
    }

    public Decision getDecision() {
        return decision;
    }

    public String getComment() {
        return comment;
    }

    public Instant getReviewedAt() {
        return reviewedAt;
    }
}
