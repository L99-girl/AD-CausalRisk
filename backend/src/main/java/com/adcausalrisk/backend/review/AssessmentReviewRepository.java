package com.adcausalrisk.backend.review;

import java.util.List;

import com.adcausalrisk.backend.review.entity.AssessmentReview;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AssessmentReviewRepository extends JpaRepository<AssessmentReview, Long> {

    List<AssessmentReview> findByAssessmentIdOrderByReviewedAtDescIdDesc(Long assessmentId);

    long countByAssessmentId(Long assessmentId);
}
