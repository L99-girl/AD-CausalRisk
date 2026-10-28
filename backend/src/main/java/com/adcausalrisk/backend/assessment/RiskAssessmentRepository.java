package com.adcausalrisk.backend.assessment;

import java.util.Optional;

import com.adcausalrisk.backend.assessment.entity.RiskAssessment;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface RiskAssessmentRepository extends JpaRepository<RiskAssessment, Long> {

    Optional<RiskAssessment> findByTaskId(Long taskId);

    Optional<RiskAssessment> findByTaskIdAndSubjectId(Long taskId, Long subjectId);

    /**
     * Conditional review-status transition: only the caller that observes {@code current} may
     * write {@code next}. Two reviewers race on the same row, the database serialises them and
     * exactly one sees {@code 1}; the other gets {@code 0} and is refused instead of silently
     * overwriting the first decision.
     */
    @Modifying(clearAutomatically = true, flushAutomatically = true)
    @Query("update RiskAssessment r set r.reviewStatus = :next"
            + " where r.id = :id and r.reviewStatus = :current")
    int updateReviewStatus(
            @Param("id") Long id,
            @Param("next") RiskAssessment.ReviewStatus next,
            @Param("current") RiskAssessment.ReviewStatus current);
}
