package com.adcausalrisk.backend.followup;

import java.util.List;
import java.util.Optional;

import com.adcausalrisk.backend.followup.entity.FollowUpPlan;

import org.springframework.data.jpa.repository.JpaRepository;

public interface FollowUpPlanRepository extends JpaRepository<FollowUpPlan, Long> {

    List<FollowUpPlan> findBySubjectIdOrderByScheduledAtAscIdAsc(Long subjectId);

    Optional<FollowUpPlan> findByIdAndSubjectId(Long id, Long subjectId);
}
