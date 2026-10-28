package com.adcausalrisk.backend.report;

import com.adcausalrisk.backend.assessment.AssessmentController.AssessmentView;
import com.adcausalrisk.backend.assessment.AssessmentService;
import com.adcausalrisk.backend.assessment.entity.RiskAssessment;
import com.adcausalrisk.backend.common.Envelope;
import com.adcausalrisk.backend.security.AppUserPrincipal;

import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code GET /api/reports/{assessmentId}} - the report view of one assessment.
 *
 * <p>The frozen contract serves this as the same {@code Assessment} payload as
 * {@code GET /api/assessments/{assessmentId}}; the transport format (HTML/PDF/JSON) is a later
 * contract change, so no media type is negotiated here yet.
 */
@RestController
public class ReportController {

    private final AssessmentService assessmentService;

    public ReportController(AssessmentService assessmentService) {
        this.assessmentService = assessmentService;
    }

    @GetMapping("/api/reports/{assessmentId}")
    public Envelope<AssessmentView> report(
            @PathVariable Long assessmentId, Authentication authentication) {
        AppUserPrincipal principal = (AppUserPrincipal) authentication.getPrincipal();
        AssessmentService.Outcome outcome = assessmentService.findAssessment(assessmentId, principal);
        RiskAssessment assessment = outcome.assessment();
        return Envelope.success(new AssessmentView(
                assessment.getId(),
                assessment.getSubjectId(),
                assessment.getTaskId(),
                outcome.result(),
                assessment.getReviewStatus().name(),
                assessment.getCreatedAt()));
    }
}
