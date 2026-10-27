package com.adcausalrisk.backend.assessment;

import java.util.Optional;

import com.adcausalrisk.backend.assessment.entity.RiskAssessment;

import org.springframework.data.jpa.repository.JpaRepository;

public interface RiskAssessmentRepository extends JpaRepository<RiskAssessment, Long> {

    Optional<RiskAssessment> findByTaskId(Long taskId);

    Optional<RiskAssessment> findByTaskIdAndSubjectId(Long taskId, Long subjectId);
}
