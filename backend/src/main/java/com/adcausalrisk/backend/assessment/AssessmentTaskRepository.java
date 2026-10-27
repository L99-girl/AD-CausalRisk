package com.adcausalrisk.backend.assessment;

import java.util.List;
import java.util.Optional;

import com.adcausalrisk.backend.assessment.entity.AssessmentTask;

import org.springframework.data.jpa.repository.JpaRepository;

public interface AssessmentTaskRepository extends JpaRepository<AssessmentTask, Long> {

    Optional<AssessmentTask> findByRunId(String runId);

    List<AssessmentTask> findBySubjectIdOrderByIdDesc(Long subjectId);
}
